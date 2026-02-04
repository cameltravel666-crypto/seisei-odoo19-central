#!/bin/bash
# =============================================================================
# Odoo 19 Central Service Deployment Script
# =============================================================================
# Usage: ./deploy_odoo19.sh <image-digest> [environment] [operator]
#
# Parameters:
#   image-digest - Docker image SHA256 digest (required)
#   environment  - production or test (default: production)
#   operator     - GitHub username or manual operator (default: manual)
#
# Examples:
#   ./deploy_odoo19.sh sha256:abc123... production ops-team
#   ./deploy_odoo19.sh sha256:abc123...
# =============================================================================

set -eo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
STACK_NAME="odoo19-central"
STACK_DIR="/srv/stacks/odoo19-central"
SCRIPTS_DIR="/srv/scripts"
HISTORY_LOG="/srv/deployments/odoo19/history.log"
LAST_GOOD_FILE="/srv/deployments/odoo19/last_good_sha"
BACKUP_DIR="/srv/backups/odoo19"

# Parameters
IMAGE_DIGEST=$1
ENV=${2:-production}
OPERATOR=${3:-manual}

# Logging functions
log() { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }
info() { log "${BLUE}INFO${NC}: $1"; }
success() { log "${GREEN}SUCCESS${NC}: $1"; }
warn() { log "${YELLOW}WARN${NC}: $1"; }
error() { log "${RED}ERROR${NC}: $1"; }

usage() {
    cat << EOF
Odoo 19 Central Service Deployment Script v1.0

Usage: $0 <image-digest> [environment] [operator]

Parameters:
  image-digest  Docker image SHA256 digest (required)
                Format: sha256:abc123...
  environment   production or test (default: production)
  operator      GitHub username or manual operator (default: manual)

Examples:
  $0 sha256:abc123def456... production deploy-bot
  $0 sha256:abc123def456...

Notes:
  - Image must be already pushed to ghcr.io/cameltravel666-crypto/seisei-odoo19
  - Deployment will create automatic backup before proceeding
  - Health checks will run after deployment
  - Automatic rollback on failure

EOF
    exit 1
}

validate_digest() {
    if [[ ! "$IMAGE_DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]]; then
        error "Invalid image digest format: $IMAGE_DIGEST"
        error "Expected format: sha256:abc123def456... (64 hex characters)"
        exit 1
    fi
}

record_deployment() {
    local status=$1
    mkdir -p "$(dirname $HISTORY_LOG)"
    echo "$(date -Iseconds) | ${STACK_NAME} | ${IMAGE_DIGEST} | ${ENV} | ${status} | ${OPERATOR}" >> $HISTORY_LOG
}

save_last_good() {
    mkdir -p "$(dirname $LAST_GOOD_FILE)"
    echo "$IMAGE_DIGEST" > "$LAST_GOOD_FILE"
}

get_last_good() {
    cat "$LAST_GOOD_FILE" 2>/dev/null || echo ""
}

# Pre-deployment gate checks
gate_check() {
    info "Running pre-deployment gate checks..."

    # Check Docker
    if ! docker info &>/dev/null; then
        error "Docker is not running"
        exit 1
    fi

    # Check disk space
    local disk_usage=$(df -h /srv 2>/dev/null | awk 'NR==2 {print $5}' | sed 's/%//' || echo "0")
    if [[ $disk_usage -gt 85 ]]; then
        error "Disk usage is ${disk_usage}% (>85%). Aborting."
        exit 1
    fi

    # Check memory
    local mem_available=$(free -m 2>/dev/null | awk 'NR==2 {print $7}' || echo "1024")
    if [[ $mem_available -lt 512 ]]; then
        error "Available memory is ${mem_available}MB (<512MB). Aborting."
        exit 1
    fi

    # Check if stack directory exists
    if [[ ! -d "${STACK_DIR}" ]]; then
        error "Stack directory not found: ${STACK_DIR}"
        exit 1
    fi

    # Check if .env file exists
    if [[ ! -f "${STACK_DIR}/.env" ]]; then
        error ".env file not found in ${STACK_DIR}"
        error "Please create .env from .env.example first"
        exit 1
    fi

    success "Gate checks passed"
}

# Backup current state
backup_state() {
    info "Creating backup before deployment..."
    mkdir -p "$BACKUP_DIR"

    local backup_name="odoo19-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
    local backup_path="${BACKUP_DIR}/${backup_name}"

    # Backup current docker-compose.yml and .env
    cd "$STACK_DIR"
    tar -czf "$backup_path" docker-compose.yml .env 2>/dev/null || true

    # Backup database (if postgres is running locally)
    if docker ps | grep -q "odoo19-postgres"; then
        info "Backing up PostgreSQL database..."
        docker exec odoo19-postgres pg_dump -U odoo odoo19 > "${BACKUP_DIR}/odoo19-db-$(date +%Y%m%d-%H%M%S).sql" 2>/dev/null || warn "Database backup failed"
    fi

    success "Backup created: ${backup_path}"

    # Keep only last 10 backups
    ls -t ${BACKUP_DIR}/odoo19-backup-*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm
}

# Pull image with digest
pull_image() {
    info "Pulling image with digest: ${IMAGE_DIGEST}..."

    local image_ref="ghcr.io/cameltravel666-crypto/seisei-odoo19@${IMAGE_DIGEST}"

    if ! docker pull "$image_ref"; then
        error "Failed to pull image: ${image_ref}"
        error "Please verify:"
        error "  1. Image exists in registry"
        error "  2. Docker is authenticated to ghcr.io"
        error "  3. Digest is correct"
        exit 1
    fi

    success "Image pulled successfully"
}

# Update .env with new digest
update_env() {
    info "Updating .env with new image digest..."

    cd "$STACK_DIR"

    # Backup current .env
    cp .env .env.backup

    # Update digest in .env
    sed -i.bak "s|^ODOO19_IMAGE_DIGEST=.*|ODOO19_IMAGE_DIGEST=${IMAGE_DIGEST}|" .env
    sed -i.bak "s|^DEPLOY_TIMESTAMP=.*|DEPLOY_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")|" .env
    sed -i.bak "s|^DEPLOY_OPERATOR=.*|DEPLOY_OPERATOR=${OPERATOR}|" .env

    rm -f .env.bak

    success ".env updated"
}

# Deploy stack
deploy_stack() {
    info "Deploying ${STACK_NAME}..."

    cd "$STACK_DIR"

    # Recreate containers with new image
    docker-compose down
    docker-compose up -d --force-recreate

    success "Deployment initiated"
}

# Health check
health_check() {
    info "Waiting for services to start..."
    sleep 10

    local max_attempts=30
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        info "Health check attempt $attempt/$max_attempts..."

        # Check if container is running
        if ! docker ps | grep -q "odoo19-central"; then
            error "Odoo 19 container is not running"
            return 1
        fi

        # Check health endpoint
        if curl -f -s http://localhost:8069/web/health > /dev/null 2>&1; then
            success "Health check passed"
            return 0
        fi

        sleep 10
        ((attempt++))
    done

    error "Health check failed after ${max_attempts} attempts"
    return 1
}

# Smoke test
smoke_test() {
    info "Running smoke tests..."

    # Test 1: Database connection
    if ! docker exec odoo19-central psql -h postgres -U odoo -d odoo19 -c "SELECT 1" > /dev/null 2>&1; then
        error "Database connection test failed"
        return 1
    fi
    success "✓ Database connection OK"

    # Test 2: Web interface
    if ! curl -f -s http://localhost:8069/web/login > /dev/null 2>&1; then
        error "Web interface test failed"
        return 1
    fi
    success "✓ Web interface OK"

    # Test 3: API endpoint (OCR webhook)
    if ! curl -f -s http://localhost:8069/api/ocr/webhook > /dev/null 2>&1; then
        warn "OCR webhook endpoint may not be ready (this is OK if module not installed)"
    else
        success "✓ OCR webhook endpoint OK"
    fi

    success "Smoke tests passed"
    return 0
}

# Rollback to last known good
rollback() {
    local last_good=$(get_last_good)

    if [[ -z "$last_good" ]]; then
        error "No last known good deployment found"
        error "Manual intervention required"
        exit 1
    fi

    warn "Rolling back to last known good: ${last_good}..."

    # Restore .env backup
    if [[ -f "${STACK_DIR}/.env.backup" ]]; then
        cp "${STACK_DIR}/.env.backup" "${STACK_DIR}/.env"
    fi

    # Redeploy with last good digest
    cd "$STACK_DIR"
    sed -i "s|^ODOO19_IMAGE_DIGEST=.*|ODOO19_IMAGE_DIGEST=${last_good}|" .env

    docker-compose down
    docker-compose up -d --force-recreate

    sleep 15

    if health_check; then
        success "Rollback successful"
        record_deployment "rollback-success"
    else
        error "Rollback failed - manual intervention required"
        record_deployment "rollback-failed"
        exit 1
    fi
}

# Main deployment flow
main() {
    echo "============================================"
    info "Odoo 19 Central Service Deployment"
    info "Image Digest: ${IMAGE_DIGEST}"
    info "Environment: ${ENV}"
    info "Operator: ${OPERATOR}"
    echo "============================================"

    validate_digest
    gate_check
    backup_state
    pull_image
    update_env

    record_deployment "deploy-start"

    if deploy_stack; then
        record_deployment "deploy-complete"

        if health_check; then
            record_deployment "health-pass"

            if smoke_test; then
                save_last_good
                record_deployment "success"
                success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                success "✓ Deployment completed successfully!"
                success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

                # Show deployment info
                info "Deployment Summary:"
                info "  Image: ghcr.io/cameltravel666-crypto/seisei-odoo19@${IMAGE_DIGEST}"
                info "  Environment: ${ENV}"
                info "  Operator: ${OPERATOR}"
                info "  Timestamp: $(date)"

                # Show running containers
                echo ""
                info "Running containers:"
                docker-compose -f "${STACK_DIR}/docker-compose.yml" ps

                exit 0
            else
                error "Smoke tests failed"
                record_deployment "smoke-fail"
                warn "Initiating rollback..."
                rollback
                exit 1
            fi
        else
            error "Health check failed"
            record_deployment "health-fail"
            warn "Initiating rollback..."
            rollback
            exit 1
        fi
    else
        error "Deployment failed"
        record_deployment "deploy-fail"
        exit 1
    fi
}

# Validate arguments
if [[ -z "$IMAGE_DIGEST" ]]; then
    usage
fi

# Run main deployment
main
