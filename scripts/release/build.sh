#!/usr/bin/env bash
# Build the website and both release images from the commit checked out.
#
#   scripts/release/build.sh
#
# Images are tagged fareflare-api:<short sha> and fareflare-worker:<short sha>; logs go
# to .fareflare/release-<short sha>/. The worker builds on the Chromium base image
# (docs/OPERATIONS.md#release-api-and-worker-images); set BROWSER_BASE to use another.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
if [ -n "$(git status --porcelain)" ]; then
  echo "The working tree has changes: commit them first, so the images match a commit." >&2
  exit 1
fi
sha=$(git rev-parse --short HEAD)
release=.fareflare/release-$sha
base=${BROWSER_BASE:-fareflare-browser-base:4892b41}
mkdir -p "$release"
if ! docker image inspect "$base" > /dev/null 2>&1; then
  echo "The browser base $base is not built here; see docs/OPERATIONS.md." >&2
  exit 1
fi
build() {
  docker buildx build --platform linux/arm64 --provenance=false --sbom=false --load "$@"
}
npm --prefix web run build > "$release/web-build.log" 2>&1
build -f Dockerfile.api -t "fareflare-api:$sha" . > "$release/api-build.log" 2>&1
build -f Dockerfile.worker --build-arg BROWSER_BASE="$base" -t "fareflare-worker:$sha" . \
  > "$release/worker-build.log" 2>&1
for kind in api worker; do
  echo "fareflare-$kind:$sha $(docker image inspect -f '{{.Id}}' "fareflare-$kind:$sha")"
done
