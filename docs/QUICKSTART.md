# Odoo 19 Central Service - Quick Start Guide

**Version**: 1.0
**Last Updated**: 2026-02-04

---

## 🚀 Quick Start - 3 Ways to Deploy

### Option A: Automated CI/CD (Recommended for Production)

**Trigger**: Push to `main` branch

```bash
# 1. Make changes to Odoo 19 addons
cd ~/Projects/server-apps/services/odoo19-central-addons/vendor_ops_core
# Edit Python files, add features, etc.

# 2. Commit and push
git add .
git commit -m "feat(odoo19): add new billing feature"
git push origin main

# 3. GitHub Actions automatically:
#    ✓ Lints code
#    ✓ Validates manifests
#    ✓ Builds Docker image
#    ✓ Pushes to ghcr.io
#    ✓ Deploys to production (with approval)

# 4. Monitor deployment
# Go to: https://github.com/your-repo/actions
```

**Result**: Zero-touch deployment with full audit trail

---

### Option B: Manual Deployment with Scripts

**Use Case**: Quick deployments, testing, or CI/CD not set up yet

```bash
# 1. Build image
cd ~/Projects/server-apps
./services/odoo19-central-addons/scripts/build.sh

# 2. Push to registry
./services/odoo19-central-addons/scripts/push.sh

# 3. Deploy to server
# (Script will output the deploy command with digest)
./infra/scripts/deploy_odoo19.sh sha256:abc123... production your-name
```

**Duration**: ~5-10 minutes
**Safety**: Automatic backup, health checks, rollback on failure

---

### Option C: Direct Server Deployment (Legacy, Not Recommended)

**Use Case**: Emergency fixes only

```bash
# SSH to server
ssh -i ~/Projects/Pem/"odoo 19 owner Server.pem" ubuntu@13.159.193.191

# Manual steps (not recommended - use Docker instead)
cd /opt/odoo19/extra-addons
# Make changes
sudo systemctl restart odoo19
```

**⚠️ Warning**: No version control, no rollback, high risk

---

## 📦 Initial Setup (One-Time)

### 1. Prepare Server

```bash
# SSH to 13.159.193.191
ssh -i ~/Projects/Pem/"odoo 19 owner Server.pem" ubuntu@13.159.193.191

# Create directories
sudo mkdir -p /srv/stacks/odoo19-central
sudo mkdir -p /srv/deployments/odoo19
sudo mkdir -p /srv/backups/odoo19
sudo mkdir -p /srv/scripts

# Copy stack configuration
# (from local: server-apps/infra/stacks/odoo19-central/)
```

### 2. Configure Environment

```bash
# On server: Create .env file
cd /srv/stacks/odoo19-central
sudo nano .env

# Fill in actual values (see .env.example)
ODOO19_IMAGE=ghcr.io/cameltravel666-crypto/seisei-odoo19
ODOO19_IMAGE_DIGEST=sha256:... # Will be set by deployment script
DB_PASSWORD=<strong-password>
ADMIN_PASSWORD=<admin-password>
OCR_WEBHOOK_KEY=seisei-ocr-webhook-2026
```

### 3. Initialize Database (First Deployment Only)

```bash
# On server
cd /srv/stacks/odoo19-central

# Start services
docker-compose up -d

# Initialize Odoo database
docker exec -it odoo19-central odoo \
  --init=base,vendor_ops_core,qr_ordering,seisei_billing,seisei_hr_menu \
  --stop-after-init

# Restart
docker-compose restart
```

---

## 🛠️ Development Workflow

### Local Development

```bash
# 1. Clone repository
cd ~/Projects/server-apps

# 2. Make changes to addons
cd services/odoo19-central-addons/vendor_ops_core

# 3. Test locally (optional)
docker-compose -f docker-compose.dev.yml up

# 4. Commit when ready
git add .
git commit -m "feat: description"
git push origin main
```

### Testing Before Production

```bash
# Build and test locally first
./services/odoo19-central-addons/scripts/build.sh test
docker run -it --rm \
  -e DB_HOST=localhost \
  -e DB_USER=odoo \
  -e DB_PASSWORD=odoo \
  ghcr.io/cameltravel666-crypto/seisei-odoo19:test \
  odoo --test-enable --stop-after-init
```

---

## 🔍 Monitoring & Verification

### Check Deployment Status

```bash
# On server
ssh ubuntu@13.159.193.191

# Check running containers
docker ps | grep odoo19

# Check logs
docker logs odoo19-central --tail 100 -f

# Check deployment history
cat /srv/deployments/odoo19/history.log | tail -10
```

### Health Checks

```bash
# HTTP health endpoint
curl http://13.159.193.191:8069/web/health

# Database connection
docker exec odoo19-central psql -h postgres -U odoo -d odoo19 -c "SELECT 1"

# Module status
docker exec odoo19-central odoo shell << 'EOF'
env['ir.module.module'].search([
    ('name', 'in', ['vendor_ops_core', 'qr_ordering', 'seisei_billing'])
]).mapped(lambda m: f"{m.name}: {m.state}")
EOF
```

---

## 🔄 Rollback Procedures

### Automatic Rollback

**Trigger**: Health checks fail after deployment

The deployment script automatically rolls back to the last known good image.

### Manual Rollback

```bash
# Find last good deployment
ssh ubuntu@13.159.193.191
cat /srv/deployments/odoo19/last_good_sha

# Redeploy with specific digest
sudo /srv/scripts/deploy_odoo19.sh sha256:<last-good-digest> production rollback
```

---

## 📊 Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Local Development (~/Projects/server-apps)                 │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ services/odoo19-central-addons/                       │  │
│  │   ├── vendor_ops_core/                                │  │
│  │   ├── qr_ordering/                                    │  │
│  │   ├── seisei_billing/                                 │  │
│  │   └── seisei_hr_menu/                                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                        │                                     │
│                        │ git push                            │
│                        ▼                                     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  GitHub Actions CI/CD                                        │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Lint & Test │──▶│ Build Image  │──▶│ Push to ghcr.io  │  │
│  └─────────────┘  └──────────────┘  └──────────────────┘  │
│                                                │             │
│                                                ▼             │
│                    ghcr.io/cameltravel666-crypto/           │
│                    seisei-odoo19@sha256:abc123...           │
│                                                │             │
└────────────────────────────────────────────────┼─────────────┘
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  Production Server (13.159.193.191)                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ /srv/stacks/odoo19-central/                           │  │
│  │   ├── docker-compose.yml                              │  │
│  │   └── .env (with IMAGE_DIGEST)                        │  │
│  └──────────────────────────────────────────────────────┘  │
│                        │                                     │
│                        ▼                                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Docker Containers                                      │  │
│  │   ├── odoo19-central (Odoo 19 service)                │  │
│  │   └── odoo19-postgres (Database)                      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  Services:                                                   │
│    - HTTP: :8069                                            │
│    - Longpolling: :8072                                     │
│    - OCR Webhook: /api/ocr/webhook                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 📚 Key Files Reference

| File | Purpose | Location |
|------|---------|----------|
| **Dockerfile** | Image definition | `services/odoo19-central-addons/Dockerfile` |
| **docker-compose.yml** | Stack configuration | `infra/stacks/odoo19-central/docker-compose.yml` |
| **.env.example** | Configuration template | `infra/stacks/odoo19-central/.env.example` |
| **deploy_odoo19.sh** | Deployment script | `infra/scripts/deploy_odoo19.sh` |
| **build.sh** | Build script | `services/odoo19-central-addons/scripts/build.sh` |
| **push.sh** | Registry push script | `services/odoo19-central-addons/scripts/push.sh` |
| **deploy-odoo19.yml** | GitHub Actions workflow | `.github/workflows/deploy-odoo19.yml` |
| **DEPLOYMENT_ARCHITECTURE.md** | Full architecture docs | `services/odoo19-central-addons/DEPLOYMENT_ARCHITECTURE.md` |

---

## 🔒 Security Checklist

- [ ] `.env` file created on server (not in Git)
- [ ] Strong passwords for DB_PASSWORD and ADMIN_PASSWORD
- [ ] OCR_WEBHOOK_KEY matches between Odoo 18 and Odoo 19
- [ ] SSH keys properly secured (`~/Projects/Pem/`)
- [ ] GitHub Actions secrets configured (ODOO19_SSH_KEY)
- [ ] Docker registry authentication (ghcr.io)

---

## 🎯 Next Steps

1. **Complete Initial Setup** (if not done)
   - [ ] Create `/srv/stacks/odoo19-central/` on server
   - [ ] Configure `.env` file
   - [ ] Run first deployment

2. **Test Deployment Pipeline**
   - [ ] Make a small change to README
   - [ ] Push to main branch
   - [ ] Verify GitHub Actions runs
   - [ ] Confirm deployment to server

3. **Configure Monitoring** (Optional)
   - [ ] Set up CloudWatch Logs
   - [ ] Configure alerts
   - [ ] Create dashboard

4. **Team Training**
   - [ ] Share this guide with team
   - [ ] Document custom procedures
   - [ ] Create runbooks for common issues

---

## 🆘 Troubleshooting

### Deployment Failed

```bash
# Check deployment logs
ssh ubuntu@13.159.193.191
cat /srv/deployments/odoo19/history.log

# Check container logs
docker logs odoo19-central --tail 100

# Manual rollback if needed
sudo /srv/scripts/deploy_odoo19.sh $(cat /srv/deployments/odoo19/last_good_sha) production rollback
```

### GitHub Actions Failing

1. Check workflow run in GitHub UI
2. Verify `ODOO19_SSH_KEY` secret is set
3. Check lint errors in Python code
4. Validate `__manifest__.py` syntax

### Service Not Responding

```bash
# On server
docker-compose -f /srv/stacks/odoo19-central/docker-compose.yml ps
docker-compose -f /srv/stacks/odoo19-central/docker-compose.yml logs
docker-compose -f /srv/stacks/odoo19-central/docker-compose.yml restart
```

---

## 📞 Support

- **Documentation**: `services/odoo19-central-addons/DEPLOYMENT_ARCHITECTURE.md`
- **Deployment History**: `/srv/deployments/odoo19/history.log` (on server)
- **Logs**: `docker logs odoo19-central`
- **Global Rules**: `~/Projects/Claude_global_v2.md`

---

**Ready to Deploy?** Start with Option A (Automated CI/CD) for production-grade deployments!
