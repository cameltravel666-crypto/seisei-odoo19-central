# Odoo 19 Central Service - Industrial Deployment Architecture

**Version**: 1.0
**Date**: 2026-02-04
**Based on**: Odoo 18 Production Deployment Pattern

---

## 📋 Overview

Odoo 19运行在独立服务器 `13.159.193.191`，提供中央管理服务：
- OCR计费webhook
- Vendor Operations管理
- 多租户计费系统

**与Odoo 18的关键区别**：
- ✅ 单一服务器部署（非多租户）
- ✅ 简化配置（无复杂路由）
- ✅ 专注中央服务功能

---

## 🏗️ Architecture

### Current State (Manual Deployment)

```
Local Development
    ↓ (manual SSH + rsync)
~/Projects/server-apps/services/odoo19-central-addons/
    ↓ (manual copy)
13.159.193.191:/opt/odoo19/extra-addons/
    ↓ (manual restart)
Odoo 19 systemd service
```

**Problems**:
- ❌ No version control on server
- ❌ No rollback capability
- ❌ No automated testing
- ❌ Manual backup required
- ❌ High risk of human error

### Target State (Industrial Deployment)

```
Git Push (main branch)
    ↓
GitHub Actions CI
    ├─> Lint & Test
    ├─> Build Docker Image
    ├─> Push to ghcr.io
    └─> Tag with sha256 digest
    ↓
Deploy Script (automated or manual trigger)
    ├─> Pre-deployment checks
    ├─> Backup current state
    ├─> Pull new image
    ├─> Deploy with digest
    ├─> Health check
    ├─> Smoke test
    └─> Rollback if failed
    ↓
Odoo 19 running in Docker
```

**Benefits**:
- ✅ Immutable deployments
- ✅ Automated rollback
- ✅ Full audit trail
- ✅ Zero-downtime updates
- ✅ Consistent with Odoo 18

---

## 📦 Deployment Components

### 1. Docker Image

**Registry**: `ghcr.io/cameltravel666-crypto/seisei-odoo19`
**Base Image**: `odoo:19.0`
**Contents**:
- All custom addons from `services/odoo19-central-addons/`
- Python dependencies
- Configuration files

**Build Command**:
```bash
cd ~/Projects/server-apps
docker build \
  -f services/odoo19-central-addons/Dockerfile \
  -t ghcr.io/cameltravel666-crypto/seisei-odoo19:latest \
  .
```

### 2. Docker Compose Stack

**Location**: `server-apps/infra/stacks/odoo19-central/`
**Services**:
- `odoo19`: Main Odoo service
- `postgres`: Database (local or RDS)

**Key Features**:
- Digest-based image references
- Health checks
- Resource limits
- Logging to CloudWatch (optional)

### 3. Deployment Script

**Location**: `server-apps/infra/scripts/deploy_odoo19.sh`
**Capabilities**:
- Pre-deployment gate checks
- Automatic backup
- Image pull and deploy
- Health verification
- Automated rollback on failure

### 4. GitHub Actions CI/CD

**Location**: `server-apps/.github/workflows/deploy-odoo19.yml`
**Triggers**:
- Push to `main` branch (paths: `services/odoo19-central-addons/**`)
- Manual workflow dispatch

**Steps**:
1. Lint Python code
2. Validate __manifest__.py files
3. Build Docker image
4. Push to GitHub Container Registry
5. Tag with git commit SHA
6. (Optional) Auto-deploy to production

---

## 🔄 Deployment Workflow

### Option A: Automated CI/CD (Recommended)

```bash
# 1. Develop locally
cd ~/Projects/server-apps/services/odoo19-central-addons
# Make changes to vendor_ops_core, etc.

# 2. Test locally (optional)
cd ~/Projects/server-apps
docker-compose -f services/odoo19-central-addons/docker-compose.dev.yml up

# 3. Commit and push
git add services/odoo19-central-addons/
git commit -m "feat(odoo19): add new billing feature"
git push origin main

# 4. GitHub Actions automatically:
#    - Runs tests
#    - Builds image: ghcr.io/.../seisei-odoo19:sha-abc1234
#    - Pushes to registry

# 5. Deploy to production (manual approval or auto)
# Option 5a: Manual trigger via GitHub UI
# Option 5b: Auto-deploy if tests pass

# 6. Verify deployment
curl http://13.159.193.191:8069/web/health
```

### Option B: Manual Deployment with Scripts

```bash
# 1. Build image locally
cd ~/Projects/server-apps
./services/odoo19-central-addons/scripts/build.sh

# 2. Push to registry
./services/odoo19-central-addons/scripts/push.sh

# 3. Deploy to server
./infra/scripts/deploy_odoo19.sh <image-digest> production

# Example:
./infra/scripts/deploy_odoo19.sh \
  sha256:abc123... \
  production \
  $(git config user.name)
```

---

## 🛠️ Implementation Plan

### Phase 1: Docker Migration (Week 1)

**Goal**: Move from systemd to Docker Compose

1. Create Dockerfile for Odoo 19
2. Create docker-compose.yml
3. Test locally
4. Deploy to 13.159.193.191 (Docker-based)
5. Verify all services work

**Deliverables**:
- `services/odoo19-central-addons/Dockerfile`
- `infra/stacks/odoo19-central/docker-compose.yml`
- Migration guide

### Phase 2: Deployment Scripts (Week 2)

**Goal**: Automated deployment with safety checks

1. Create deploy_odoo19.sh (based on deploy.sh)
2. Add backup script
3. Add health check script
4. Add rollback capability
5. Test on staging environment (if available)

**Deliverables**:
- `infra/scripts/deploy_odoo19.sh`
- `infra/scripts/backup-odoo19.sh`
- `infra/scripts/health-check-odoo19.sh`

### Phase 3: CI/CD Pipeline (Week 3)

**Goal**: Automated build and test

1. Create GitHub Actions workflow
2. Add linting and validation
3. Add automated image build
4. Add image push to ghcr.io
5. Add deployment trigger (manual approval)

**Deliverables**:
- `.github/workflows/deploy-odoo19.yml`
- `.github/workflows/test-odoo19.yml`

### Phase 4: Production Hardening (Week 4)

**Goal**: Production-ready deployment

1. Add secrets management (AWS SSM)
2. Add CloudWatch logging
3. Add monitoring and alerts
4. Add disaster recovery plan
5. Document runbooks

**Deliverables**:
- Production deployment guide
- DR runbook
- Monitoring dashboard

---

## 🔒 Security & Compliance

### Secrets Management

**Development**:
- `.env.example` - Template with placeholder values
- `.env` - Local secrets (gitignored)

**Production**:
- AWS Systems Manager Parameter Store
- Docker secrets or env_file from secure location
- No secrets in Git repository

### Access Control

**SSH Keys**:
- Production: `~/Projects/Pem/"odoo 19 owner Server.pem"`
- Limited to deployer user (TBD)

**Docker Registry**:
- GitHub Container Registry (ghcr.io)
- Authentication via GitHub PAT
- Pull-only access for deployment

### Audit Trail

**Deployment History**:
- Location: `/srv/deployments/odoo19/history.log`
- Format: `timestamp | version | env | status | operator`
- Retention: 90 days minimum

---

## 📊 Monitoring & Alerting

### Health Checks

**Application**:
- Endpoint: `http://13.159.193.191:8069/web/health`
- Frequency: Every 30 seconds
- Timeout: 10 seconds

**Database**:
- PostgreSQL connection check
- Query performance monitoring

**System**:
- CPU usage < 80%
- Memory usage < 85%
- Disk usage < 80%

### Logging

**Application Logs**:
- Docker logs: `docker logs odoo19-central`
- Optional: CloudWatch Logs

**Access Logs**:
- Odoo access logs
- API request logs (OCR webhook)

---

## 🔄 Rollback Procedures

### Automated Rollback

If health checks fail after deployment:
```bash
# Automatic rollback to last known good image
docker-compose down
docker-compose up -d --force-recreate
```

### Manual Rollback

```bash
# 1. Find last good deployment
cat /srv/deployments/odoo19/last_good_sha

# 2. Redeploy with last good digest
./infra/scripts/deploy_odoo19.sh sha256:<last-good-digest> production rollback
```

---

## 📚 Related Documentation

- **Odoo 18 Deployment**: Proven production pattern
- **OCR Central Service**: Docker-based deployment reference
- **Vendor Bridge**: Similar service deployment
- **Global Rules**: `~/Projects/Claude_global_v2.md`

---

## ✅ Success Criteria

**Phase 1 Complete**:
- [ ] Odoo 19 running in Docker
- [ ] All addons loaded correctly
- [ ] OCR webhook functional
- [ ] Database connected

**Phase 2 Complete**:
- [ ] One-command deployment
- [ ] Automatic backup before deploy
- [ ] Rollback capability tested
- [ ] Health checks passing

**Phase 3 Complete**:
- [ ] Git push triggers CI
- [ ] Image automatically built
- [ ] Manual deployment approval
- [ ] Zero-downtime updates

**Phase 4 Complete**:
- [ ] Production monitoring active
- [ ] Alerts configured
- [ ] DR plan tested
- [ ] Team trained on procedures

---

**Next Steps**: Create Dockerfile and docker-compose.yml (Phase 1)
