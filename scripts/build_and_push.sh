#!/usr/bin/env bash
# Build and push all 5 demo images to Docker Hub.
#
#   docker.io/$DOCKERHUB_USER/blast-radius-checkout:1.0.0
#   docker.io/$DOCKERHUB_USER/blast-radius-checkout:1.0.1-broken
#   docker.io/$DOCKERHUB_USER/blast-radius-inventory:1.0.0
#   docker.io/$DOCKERHUB_USER/blast-radius-payment:1.0.0
#   docker.io/$DOCKERHUB_USER/blast-radius-notification:1.0.0
#
# Usage:
#   ./scripts/build_and_push.sh                     # build + push all
#   PUSH=0 ./scripts/build_and_push.sh              # build only, no push
#   BUILD_BROKEN=0 ./scripts/build_and_push.sh      # skip the broken checkout build
#   DOCKERHUB_USER=someoneelse ./scripts/build_and_push.sh
#
# Make sure you've run `docker login` first if PUSH=1.

set -euo pipefail

DOCKERHUB_USER="${DOCKERHUB_USER:-pritishharness}"
PUSH="${PUSH:-1}"
BUILD_BROKEN="${BUILD_BROKEN:-1}"
PLATFORM="${PLATFORM:-linux/amd64}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found in PATH" >&2
  exit 1
fi

build_one() {
  local svc="$1"
  local tag="$2"
  shift 2
  local image="$DOCKERHUB_USER/blast-radius-$svc:$tag"

  echo
  echo "==> build $image"
  docker build \
    --platform "$PLATFORM" \
    -f "services/$svc/Dockerfile" \
    -t "$image" \
    "$@" \
    .

  if [[ "$PUSH" == "1" ]]; then
    echo "==> push  $image"
    docker push "$image"
  fi
}

echo "Docker Hub user: $DOCKERHUB_USER"
echo "Platform:        $PLATFORM"
echo "Push enabled:    $PUSH"
echo "Build broken:    $BUILD_BROKEN"

# Healthy 1.0.0 builds for all four services
build_one inventory     1.0.0
build_one payment       1.0.0
build_one notification  1.0.0
build_one checkout      1.0.0

# Broken build of checkout - same source code, but BROKEN=1 baked in
# via build args so the image tag is the source of truth for behavior.
if [[ "$BUILD_BROKEN" == "1" ]]; then
  build_one checkout 1.0.1-broken \
    --build-arg SERVICE_VERSION=1.0.1-broken \
    --build-arg BROKEN=1
fi

echo
echo "Done."
if [[ "$PUSH" == "1" ]]; then
  echo "Images now available:"
  echo "  docker.io/$DOCKERHUB_USER/blast-radius-inventory:1.0.0"
  echo "  docker.io/$DOCKERHUB_USER/blast-radius-payment:1.0.0"
  echo "  docker.io/$DOCKERHUB_USER/blast-radius-notification:1.0.0"
  echo "  docker.io/$DOCKERHUB_USER/blast-radius-checkout:1.0.0"
  if [[ "$BUILD_BROKEN" == "1" ]]; then
    echo "  docker.io/$DOCKERHUB_USER/blast-radius-checkout:1.0.1-broken"
  fi
fi
