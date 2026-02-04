# Seisei Odoo 19 Central Service

**Version**: 1.0
**Status**: Production
**Server**: 13.159.193.191:8069

---

## 📋 Overview

Central Odoo 19 service for Seisei ERP system, managing:

- **Vendor Operations** (`vendor_ops_core`) - Core vendor management and operations
- **QR Ordering** (`qr_ordering`) - QR code-based ordering system
- **Billing System** (`seisei_billing`) - Multi-tenant billing and invoicing
- **HR Menu** (`seisei_hr_menu`) - HR menu customizations

## 🚀 Quick Start

### Option A: Automated CI/CD (Recommended)

**Trigger**: Push to `main` branch

```bash
# 1. Make changes to addons
cd addons/vendor_ops_core
# Edit files...

# 2. Commit and push
git add .
git commit -m "feat(vendor_ops): add new feature"
git push origin main

# 3. GitHub Actions automatically:
#    ✓ Lints code
#    ✓ Validates manifests
#    ✓ Builds Docker image
#    ✓ Pushes to ghcr.io
#    ✓ Deploys to production
```

**Zero-touch deployment** with full audit trail!

---

### Option B: Manual Deployment

```bash
# 1. Build image
./scripts/build.sh

# 2. Push to registry
./scripts/push.sh

# 3. Deploy to server
./infra/scripts/deploy.sh <image-digest> production <your-name>
```

---

## 📦 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  GitHub Repository (seisei-odoo19-central)                   │
│  ├── addons/              # Custom Odoo modules              │
│  ├── infra/               # Infrastructure configs           │
│  ├── scripts/             # Build & deployment scripts       │
│  └── .github/workflows/   # CI/CD automation                 │
└─────────────────────────────────────────────────────────────┘
                             │
                             │ git push
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  GitHub Actions CI/CD                                        │
│  ✓ Lint → ✓ Validate → ✓ Build → ✓ Push                   │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  ghcr.io/cameltravel666-crypto/seisei-odoo19                │
│  Image: ghcr.io/.../seisei-odoo19@sha256:abc123...          │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Production Server (13.159.193.191)                          │
│  Docker Stack:                                               │
│    - odoo19-central (Odoo 19)                               │
│    - odoo19-postgres (PostgreSQL 16)                        │
│  Ports: 8069 (HTTP), 8072 (Longpolling)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 🗂️ Repository Structure

```
seisei-odoo19-central/
├── addons/                        # Custom Odoo modules
│   ├── vendor_ops_core/           # Vendor operations core
│   ├── qr_ordering/               # QR ordering system
│   ├── seisei_billing/            # Billing module
│   └── seisei_hr_menu/            # HR menu customization
│
├── infra/                         # Infrastructure
│   ├── docker/
│   │   └── Dockerfile             # Odoo 19 image definition
│   ├── stacks/
│   │   ├── docker-compose.yml     # Production stack
│   │   └── .env.example           # Environment template
│   └── scripts/
│       └── deploy.sh              # Deployment automation
│
├── scripts/                       # Local scripts
│   ├── build.sh                   # Build Docker image
│   └── push.sh                    # Push to registry
│
├── docs/                          # Documentation
│   ├── QUICKSTART.md              # Quick start guide
│   └── DEPLOYMENT_ARCHITECTURE.md # Full architecture
│
└── .github/
    └── workflows/
        └── deploy.yml             # CI/CD pipeline
```

---

## 🛠️ Development

### Local Development

```bash
# 1. Clone repository
git clone git@github.com:cameltravel666-crypto/seisei-odoo19-central.git
cd seisei-odoo19-central

# 2. Make changes to addons
cd addons/vendor_ops_core
# Edit files...

# 3. Test locally (optional)
./scripts/build.sh test
docker run -it --rm \
  -e DB_HOST=localhost \
  -e DB_USER=odoo \
  -e DB_PASSWORD=odoo \
  ghcr.io/cameltravel666-crypto/seisei-odoo19:test

# 4. Commit and push
git add .
git commit -m "feat: description"
git push origin main
```

### Testing Before Production

```bash
# Build and test locally
./scripts/build.sh test
docker run -it --rm \
  -e DB_HOST=localhost \
  -e DB_USER=odoo \
  -e DB_PASSWORD=odoo \
  ghcr.io/cameltravel666-crypto/seisei-odoo19:test \
  odoo --test-enable --stop-after-init
```

---

## 📊 Deployment Status

### Production Environment

- **URL**: http://13.159.193.191:8069
- **Databases**: ERP, Test1204, Trading, odoo19, odoo_Japantemplate_v1, seisei19
- **Custom Addons**: 4 modules installed
- **Container**: odoo19-central + odoo19-postgres

### Check Deployment

```bash
# SSH to server
ssh -i ~/Projects/Pem/"odoo 19 owner Server.pem" ubuntu@13.159.193.191

# Check status
docker ps | grep odoo19
docker logs odoo19-central --tail 100

# Check health
curl http://localhost:8069/web/health
```

---

## 🔄 Rollback

### Automatic Rollback

Health checks fail → Auto-rollback to last good image

### Manual Rollback

```bash
# SSH to server
ssh ubuntu@13.159.193.191

# Find last good deployment
cat /srv/deployments/odoo19/last_good_sha

# Redeploy
sudo /srv/scripts/deploy.sh sha256:<digest> production rollback
```

---

## 🔒 Security

- ✅ `.env` file NOT in Git (use `.env.example`)
- ✅ Strong passwords configured
- ✅ SSH keys properly secured
- ✅ GitHub Actions secrets configured
- ✅ Private repository
- ✅ Digest-based image deployment

---

## 📚 Documentation

- [Quick Start Guide](docs/QUICKSTART.md) - Step-by-step deployment guide
- [Deployment Architecture](docs/DEPLOYMENT_ARCHITECTURE.md) - Full architecture documentation
- [GitHub Actions Workflow](.github/workflows/deploy.yml) - CI/CD configuration

---

## 🆘 Troubleshooting

### Deployment Failed

```bash
# Check GitHub Actions logs
# Go to: https://github.com/cameltravel666-crypto/seisei-odoo19-central/actions

# Check server logs
ssh ubuntu@13.159.193.191
docker logs odoo19-central --tail 100
cat /srv/deployments/odoo19/history.log
```

### Service Not Responding

```bash
# On server
docker ps | grep odoo19
docker logs odoo19-central
docker restart odoo19-central
```

---

## 📞 Support

- **Repository**: https://github.com/cameltravel666-crypto/seisei-odoo19-central
- **Server**: 13.159.193.191:8069
- **Deployment History**: `/srv/deployments/odoo19/history.log` (on server)

---

## 📝 License

Private - Seisei Internal Use Only

---

**Last Updated**: 2026-02-04
**Maintained by**: Seisei Development Team
