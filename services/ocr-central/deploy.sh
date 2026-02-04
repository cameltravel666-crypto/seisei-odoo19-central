#!/bin/bash
set -e

# Central OCR Service Deployment Script
# Deploys the OCR service to 13.159.193.191:8180

# Default values
SERVER_USER="ubuntu"
SERVER_HOST="13.159.193.191"
DEPLOY_PATH="~/ocr-central"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --server)
      SERVER_HOST="$2"
      shift 2
      ;;
    --user)
      SERVER_USER="$2"
      shift 2
      ;;
    --path)
      DEPLOY_PATH="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--server HOST] [--user USER] [--path PATH]"
      exit 1
      ;;
  esac
done

echo "=========================================="
echo "Central OCR Service Deployment"
echo "=========================================="
echo "Target: ${SERVER_USER}@${SERVER_HOST}"
echo "Path: ${DEPLOY_PATH}"
echo ""

# Check if we're in the correct directory
if [ ! -f "main.py" ] || [ ! -f "docker-compose.yml" ]; then
    echo "Error: Please run this script from services/ocr-central/ directory"
    exit 1
fi

# Create remote directory
echo "1. Creating remote directory..."
ssh ${SERVER_USER}@${SERVER_HOST} "mkdir -p ${DEPLOY_PATH}"

# Copy files to remote server
echo "2. Copying files to remote server..."
scp -r main.py \
       Dockerfile \
       docker-compose.yml \
       requirements.txt \
       .env.example \
       README.md \
       ${SERVER_USER}@${SERVER_HOST}:${DEPLOY_PATH}/

# Deploy on remote server
echo "3. Deploying service on remote server..."
ssh ${SERVER_USER}@${SERVER_HOST} << 'ENDSSH'
cd ~/ocr-central

# Check if .env exists, if not copy from example
if [ ! -f .env ]; then
    echo "Warning: .env file not found. Copying from .env.example"
    echo "Please edit .env and add your real API keys and passwords"
    cp .env.example .env
fi

# Pull latest images and rebuild
echo "Building and starting services..."
docker compose down
docker compose build --no-cache
docker compose up -d

# Wait for services to start
echo "Waiting for services to start..."
sleep 5

# Check service health
echo "Checking service health..."
docker compose ps
docker compose logs --tail=20 ocr-service

echo ""
echo "Deployment complete!"
echo "Service URL: http://localhost:8180"
echo "Health check: curl http://localhost:8180/health"
ENDSSH

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. SSH to server: ssh ${SERVER_USER}@${SERVER_HOST}"
echo "2. Edit .env file: cd ${DEPLOY_PATH} && nano .env"
echo "3. Restart services: docker compose restart"
echo "4. Check logs: docker compose logs -f ocr-service"
echo ""
echo "Service accessible at: http://${SERVER_HOST}:8180"
