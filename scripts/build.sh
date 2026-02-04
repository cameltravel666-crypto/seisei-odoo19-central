#!/bin/bash
# =============================================================================
# Odoo 19 Central - Build Docker Image
# =============================================================================
# This script builds the Odoo 19 Docker image locally
# Usage: ./build.sh [tag]
# =============================================================================

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
IMAGE_NAME="ghcr.io/cameltravel666-crypto/seisei-odoo19"
TAG=${1:-latest}
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "local")

echo -e "${BLUE}Building Odoo 19 Central Image${NC}"
echo "Image: ${IMAGE_NAME}:${TAG}"
echo "Git SHA: ${GIT_SHA}"
echo ""

# Navigate to repository root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}/.."

# Build image
echo -e "${BLUE}Building Docker image...${NC}"
docker build \
  -f infra/docker/Dockerfile \
  -t "${IMAGE_NAME}:${TAG}" \
  -t "${IMAGE_NAME}:sha-${GIT_SHA}" \
  --build-arg BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
  --build-arg GIT_SHA="${GIT_SHA}" \
  .

echo ""
echo -e "${GREEN}✓ Build complete!${NC}"
echo ""
echo "Image tags:"
echo "  - ${IMAGE_NAME}:${TAG}"
echo "  - ${IMAGE_NAME}:sha-${GIT_SHA}"
echo ""
echo "Next steps:"
echo "  1. Test locally: docker run --rm ${IMAGE_NAME}:${TAG}"
echo "  2. Push to registry: ./scripts/push.sh ${TAG}"
echo ""
