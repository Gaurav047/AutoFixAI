#!/usr/bin/env bash
# Build AutoFixAI, push it to Nebius Container Registry, and serve it from a Nebius Serverless Endpoint.
#
# Prerequisites (Linux, macOS or WSL):
#   - Nebius CLI installed and logged in:  nebius profile create
#   - Docker running
#   - NEBIUS_API_KEY in ../.env (Token Factory key the app uses for Nemotron)
#
# Usage:  ./deploy/nebius-deploy.sh            (re-run after code changes to push a new image)
#         PROJECT_ID=project-... ./deploy/nebius-deploy.sh
#             deploy into a specific project/region, e.g. one where the tenant has non-GPU vCPU quota
set -euo pipefail

APP=${APP:-autofixai}
PLATFORM=${PLATFORM:-cpu-d3}
PRESET=${PRESET:-4vcpu-16gb}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

NEBIUS_API_KEY=${NEBIUS_API_KEY:-$(grep -E '^NEBIUS_API_KEY=' "$ROOT/.env" | cut -d= -f2-)}
[ -n "$NEBIUS_API_KEY" ] || { echo "NEBIUS_API_KEY not set (add it to .env)"; exit 1; }

# Registry and endpoint live in the same project, so the endpoint can pull without credentials.
nb() { nebius "$@" ${PROJECT_ID:+--parent-id "$PROJECT_ID"}; }

echo "==> Container registry"
REGISTRY_ID=$(nb registry get-by-name --name "$APP" --format jsonpath='{.metadata.id}' 2>/dev/null || true)
if [ -z "$REGISTRY_ID" ]; then
  REGISTRY_ID=$(nb registry create --name "$APP" --format jsonpath='{.metadata.id}')
fi
REGISTRY_FQDN=$(nebius registry get "$REGISTRY_ID" --format jsonpath='{.status.registry_fqdn}')
IMAGE="$REGISTRY_FQDN/${REGISTRY_ID#registry-}/$APP:latest"
echo "    $IMAGE"

echo "==> Build and push"
nebius registry configure-helper >/dev/null
docker build --platform linux/amd64 -t "$IMAGE" "$ROOT"
docker push "$IMAGE"

echo "==> Serverless endpoint"
ENDPOINT_ID=$(nb ai endpoint get-by-name --name "$APP" --format jsonpath='{.metadata.id}' 2>/dev/null || true)
if [ -z "$ENDPOINT_ID" ]; then
  nb ai endpoint create \
    --name "$APP" \
    --image "$IMAGE" \
    --platform "$PLATFORM" \
    --preset "$PRESET" \
    --disk-size 50Gi \
    --container-port 8000 \
    --auth none \
    --env "NEBIUS_API_KEY=$NEBIUS_API_KEY" \
    --env "AUTOFIX_PUBLIC_MODE=1" \
    --env "AUTOFIX_WORKERS=2"
  ENDPOINT_ID=$(nb ai endpoint get-by-name --name "$APP" --format jsonpath='{.metadata.id}')
else
  echo "    Endpoint exists ($ENDPOINT_ID); new image pushed under the same tag."
  echo "    Restart the endpoint (console or CLI) so it pulls the new image."
fi

echo "==> Public URL"
nebius ai endpoint get "$ENDPOINT_ID" --format json | grep -o '"https://[^"]*"' | head -1 | tr -d '"'
