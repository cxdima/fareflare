"""Upload the built website's static files to the bucket CloudFront serves them from.

Scripts, styles, fonts and artwork come from S3 through CloudFront, so a cache miss
costs an S3 read rather than a Lambda invocation that may have to start cold. Pages
still come from the application, which renders them per request.

    python -m fareflare.publish_web --bucket NAME [--dist web/dist] [--distribution ID]

Run it after building the website and before the new API image goes live, so every
file a new page names is already in place. Nothing is ever deleted: someone with the
previous release open keeps loading its scripts. Unchanged files are skipped. Files
whose names do not change with their content (``/assets``) are invalidated in
CloudFront when they change, when ``--distribution`` is given.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

import boto3

from fareflare import static_files


def published(client, bucket: str) -> dict[str, str]:
    """Key → MD5 of what the bucket already holds (S3's ETag for a plain upload)."""
    etags: dict[str, str] = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for item in page.get("Contents", []):
            etags[item["Key"]] = item["ETag"].strip('"')
    return etags


def publish(
    dist: Path,
    bucket: str,
    client,
    *,
    cloudfront=None,
    distribution: str | None = None,
    dry_run: bool = False,
) -> dict:
    if not (dist / "index.html").is_file() or not any(dist.glob("main-*.js")):
        raise ValueError(f"{dist} is not a built website; run npm --prefix web run build")
    existing = published(client, bucket)
    uploaded, unchanged, changed_paths = [], 0, []
    for url, path in sorted(static_files.public_files(dist).items()):
        key = url.lstrip("/")
        body = path.read_bytes()
        if existing.get(key) == hashlib.md5(body, usedforsecurity=False).hexdigest():
            unchanged += 1
            continue
        uploaded.append(key)
        if key in existing and not static_files.fingerprinted(path):
            changed_paths.append(url)
        if dry_run:
            continue
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=static_files.media_type(path) or "application/octet-stream",
            CacheControl=static_files.cache_control(path),
        )
    invalidation = None
    if changed_paths and distribution and cloudfront is not None and not dry_run:
        # More than a handful of changed artwork files: one wildcard costs the same.
        paths = changed_paths if len(changed_paths) <= 10 else ["/assets/*"]
        invalidation = cloudfront.create_invalidation(
            DistributionId=distribution,
            InvalidationBatch={
                "Paths": {"Quantity": len(paths), "Items": paths},
                "CallerReference": f"publish-web-{time.time_ns()}",
            },
        )["Invalidation"]["Id"]
    return {
        "uploaded": uploaded,
        "unchanged": unchanged,
        "invalidated": changed_paths if invalidation else [],
        "invalidation": invalidation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fareflare.publish_web", description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--dist", type=Path, default=Path("web/dist"))
    parser.add_argument("--distribution", help="CloudFront distribution to invalidate")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = publish(
        args.dist,
        args.bucket,
        boto3.client("s3", region_name=args.region),
        cloudfront=boto3.client("cloudfront", region_name=args.region),
        distribution=args.distribution,
        dry_run=args.dry_run,
    )
    print(
        f"{'Would upload' if args.dry_run else 'Uploaded'} {len(result['uploaded'])} files, "
        f"{result['unchanged']} unchanged"
        + (f"; invalidated {', '.join(result['invalidated'])}" if result["invalidated"] else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
