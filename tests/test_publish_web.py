"""Static files reach S3 with the type and caching the application would give them."""

import boto3
import pytest
from moto import mock_aws

from fareflare.publish_web import main, publish

BUCKET = "fareflare-web-test"


@pytest.fixture
def aws(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        cloudfront = boto3.client("cloudfront", region_name="us-east-1")
        distribution = cloudfront.create_distribution(
            DistributionConfig={
                "CallerReference": "test",
                "Comment": "",
                "Enabled": True,
                "Origins": {
                    "Quantity": 1,
                    "Items": [
                        {
                            "Id": "web",
                            "DomainName": "example.com",
                            "CustomOriginConfig": {
                                "HTTPPort": 80,
                                "HTTPSPort": 443,
                                "OriginProtocolPolicy": "https-only",
                            },
                        }
                    ],
                },
                "DefaultCacheBehavior": {
                    "TargetOriginId": "web",
                    "ViewerProtocolPolicy": "https-only",
                },
            }
        )["Distribution"]["Id"]
        yield s3, cloudfront, distribution


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html>")
    (tmp_path / "main-ABC12345.js").write_text("void 0;")
    (tmp_path / "styles-ABC12345.css").write_text("body{}")
    (tmp_path / "main-ABC12345.js.map").write_text("private sources")
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "site.webmanifest").write_text("{}")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "phone.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "font-ABC12345.woff2").write_bytes(b"font")
    return tmp_path


def test_publishes_only_public_files_with_their_type_and_caching(aws, dist):
    s3, _, _ = aws
    result = publish(dist, BUCKET, s3)
    assert sorted(result["uploaded"]) == [
        "assets/phone.webp",
        "main-ABC12345.js",
        "media/font-ABC12345.woff2",
        "site.webmanifest",
        "styles-ABC12345.css",
    ]
    head = lambda key: s3.head_object(Bucket=BUCKET, Key=key)  # noqa: E731
    assert head("main-ABC12345.js")["CacheControl"] == "public, max-age=31536000, immutable"
    assert head("main-ABC12345.js")["ContentType"] == "text/javascript"
    assert head("assets/phone.webp")["ContentType"] == "image/webp"
    assert head("assets/phone.webp")["CacheControl"] == "public, max-age=3600"
    assert head("media/font-ABC12345.woff2")["ContentType"] == "font/woff2"
    assert head("site.webmanifest")["ContentType"] == "application/manifest+json"


def test_a_second_release_uploads_changes_keeps_old_files_and_invalidates_artwork(aws, dist):
    s3, cloudfront, distribution = aws
    publish(dist, BUCKET, s3)
    (dist / "main-ABC12345.js").unlink()
    (dist / "main-NEW99999.js").write_text("void 1;")
    (dist / "assets" / "phone.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBP new")
    result = publish(dist, BUCKET, s3, cloudfront=cloudfront, distribution=distribution)
    assert sorted(result["uploaded"]) == ["assets/phone.webp", "main-NEW99999.js"]
    assert result["unchanged"] == 3
    assert result["invalidated"] == ["/assets/phone.webp"] and result["invalidation"]
    # A page from the previous release can still load its script.
    assert s3.head_object(Bucket=BUCKET, Key="main-ABC12345.js")["ContentLength"] == 7
    assert publish(dist, BUCKET, s3)["uploaded"] == []


def test_refuses_a_folder_that_is_not_a_built_website(aws, tmp_path):
    s3, _, _ = aws
    with pytest.raises(ValueError, match="not a built website"):
        publish(tmp_path, BUCKET, s3)


def test_dry_run_changes_nothing(aws, dist, capsys):
    s3, _, _ = aws
    assert main(["--bucket", BUCKET, "--dist", str(dist), "--dry-run"]) == 0
    assert "Would upload 5 files" in capsys.readouterr().out
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET)
