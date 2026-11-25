#!/usr/bin/env bash
# Push the images built for the commit checked out and point production's tfvars at them.
#
#   scripts/release/push.sh
#
# An image whose local ID is the digest production already runs is not pushed: it is
# unchanged (a web-only change never changes the worker). Each pushed image must come
# back from ECR with the digest it has here; only when every push checks out are the
# digests written into infra/production.auto.tfvars.json, after a backup of it in
# .fareflare/release-<short sha>/. Nothing is deployed: that is terraform's job.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
sha=$(git rev-parse --short HEAD)
release=.fareflare/release-$sha
tfvars=infra/production.auto.tfvars.json
region=${AWS_REGION:-us-east-1}

variable() { if [ "$1" = api ]; then echo api_image_uri; else echo image_uri; fi; }
repository() {
  if [ "$1" = api ]; then terraform -chdir=infra output -raw api_repository_url
  else terraform -chdir=infra output -raw repository_url; fi
}

changed=()
for kind in api worker; do
  local_id=$(docker image inspect -f '{{.Id}}' "fareflare-$kind:$sha")
  deployed=$(jq -r ".$(variable "$kind")" "$tfvars")
  if [ "$local_id" = "${deployed##*@}" ]; then
    echo "$kind unchanged, not pushed ($local_id)"
  else
    changed+=("$kind")
  fi
done
if [ ${#changed[@]} -eq 0 ]; then
  echo "Production already runs both images: nothing to push or deploy."
  exit 0
fi

mkdir -p "$release"
[ -f "$release/production.auto.tfvars.before.json" ] ||
  cp "$tfvars" "$release/production.auto.tfvars.before.json"
tag=fareflare-$sha-$(date -u +%Y%m%dT%H%M%SZ)
echo "$tag" > "$release/tag.txt"
registry=$(repository api)
registry=${registry%%/*}
command aws ecr get-login-password --region "$region" |
  docker login --username AWS --password-stdin "$registry" > /dev/null
filter=.
arguments=()
for kind in "${changed[@]}"; do
  url=$(repository "$kind")
  docker tag "fareflare-$kind:$sha" "$url:$tag"
  docker push "$url:$tag" > "$release/$kind-push.log" 2>&1
  digest=$(command aws ecr describe-images --region "$region" --repository-name "${url#*/}" \
    --image-ids imageTag="$tag" --query 'imageDetails[0].imageDigest' --output text)
  local_id=$(docker image inspect -f '{{.Id}}' "fareflare-$kind:$sha")
  if [ "$digest" != "$local_id" ]; then
    echo "ECR reports '$digest' for $kind, not $local_id: tfvars left unchanged." >&2
    exit 1
  fi
  echo "$kind pushed $url:$tag $digest"
  arguments+=(--arg "$kind" "$url@$digest")
  filter="$filter | .$(variable "$kind") = \$$kind"
done
jq "${arguments[@]}" "$filter" "$tfvars" > "$release/tfvars.new.json"
mv "$release/tfvars.new.json" "$tfvars"
echo "tfvars now name: ${changed[*]}"
