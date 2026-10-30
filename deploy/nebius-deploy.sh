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
#         RECREATE=1 ./deploy/nebius-deploy.sh
#             replace an existing endpoint so new env vars (e.g. TAVILY_API_KEY) apply; the URL changes
set -euo pipefail

APP=${APP:-autofixai}
PLATFORM=${PLATFORM:-cpu-d3}
PRESET=${PRESET:-4vcpu-16gb}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

env_value() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | cut -d= -f2- || true; }
NEBIUS_API_KEY=${NEBIUS_API_KEY:-$(env_value NEBIUS_API_KEY)}
TAVILY_API_KEY=${TAVILY_API_KEY:-$(env_value TAVILY_API_KEY)}
[ -n "$NEBIUS_API_KEY" ] || { echo "NEBIUS_API_KEY not set (add it to .env)"; exit 1; }

# Registry and endpoint live in the same project, so the endpoint can pull without credentials.
nb() { nebius "$@" ${PROJECT_ID:+--parent-id "$PROJECT_ID"}; }

# Look a resource up by name. Prints its ID, or nothing if it doesn't exist; any other error
# (expired login, network) stops the script rather than being mistaken for "not found".
find_id() {
  local out
  if out=$(nb "$@" --name "$APP" --format jsonpath='{.metadata.id}' 2>&1 </dev/null); then
    echo "$out"
  elif ! grep -q "NotFound" <<<"$out"; then
    echo "Lookup failed: $out" >&2
    echo "If your login expired, run 'nebius iam whoami' to sign in again, then re-run." >&2
    exit 1
  fi
}

echo "==> Container registry"
REGISTRY_ID=$(find_id registry get-by-name)
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
ENDPOINT_ID=$(find_id ai endpoint get-by-name)
# Environment variables can't be changed on an existing endpoint, so RECREATE=1 replaces it.
# The replacement gets a new public URL.
if [ -n "$ENDPOINT_ID" ] && [ "${RECREATE:-0}" = "1" ]; then
  echo "    Deleting $ENDPOINT_ID to recreate it with the current environment"
  nebius ai endpoint delete "$ENDPOINT_ID"
  ENDPOINT_ID=""
fi
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
    ${TAVILY_API_KEY:+--env "TAVILY_API_KEY=$TAVILY_API_KEY"} \
    --env "AUTOFIX_PUBLIC_MODE=1" \
    --env "AUTOFIX_WORKERS=2"
  ENDPOINT_ID=$(nb ai endpoint get-by-name --name "$APP" --format jsonpath='{.metadata.id}')
else
  echo "    Endpoint exists ($ENDPOINT_ID); new image pushed under the same tag."
  echo "    Restart the endpoint (console or CLI) so it pulls the new image."
fi

echo "==> Public URL"
nebius ai endpoint get "$ENDPOINT_ID" --format json | grep -o '"https://[^"]*"' | head -1 | tr -d '"'
