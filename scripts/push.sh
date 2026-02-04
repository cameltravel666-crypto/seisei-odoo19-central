#!/bin/bash
# =============================================================================
# Odoo 19 Central - Push Docker Image to Registry
# =============================================================================
# This script pushes the Odoo 19 Docker image to GitHub Container Registry
# Usage: ./push.sh [tag]
#
# Prerequisites:
#   - Docker authentication to ghcr.io
#   - Image already built locally
# =============================================================================

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
IMAGE_NAME="ghcr.io/cameltravel666-crypto/seisei-odoo19"
TAG=${1:-latest}
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "local")

echo -e "${BLUE}Pushing Odoo 19 Central Image${NC}"
echo "Image: ${IMAGE_NAME}:${TAG}"
echo "Git SHA: ${GIT_SHA}"
echo ""

# Check if Docker is authenticated
if ! docker pull ghcr.io/cameltravel666-crypto/seisei-odoo19:latest > /dev/null 2>&1; then
    echo -e "${YELLOW}Warning: Not authenticated to ghcr.io${NC}"
    echo "Please run: echo \$GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin"
    echo ""
fi

# Push both tags
echo -e "${BLUE}Pushing ${IMAGE_NAME}:${TAG}...${NC}"
docker push "${IMAGE_NAME}:${TAG}"

echo -e "${BLUE}Pushing ${IMAGE_NAME}:sha-${GIT_SHA}...${NC}"
docker push "${IMAGE_NAME}:sha-${GIT_SHA}"

# Get and display image digest
echo ""
echo -e "${BLUE}Retrieving image digest...${NC}"
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${IMAGE_NAME}:${TAG}" | cut -d@ -f2)

echo ""
echo -e "${GREEN}✓ Push complete!${NC}"
echo ""
echo "Image pushed:"
echo "  Repository: ${IMAGE_NAME}"
echo "  Tag: ${TAG}"
echo "  Git SHA: sha-${GIT_SHA}"
echo "  Digest: ${DIGEST}"
echo ""
echo "Deploy command:"
echo "  ./infra/scripts/deploy.sh ${DIGEST} production \$(git config user.name)"
echo ""
