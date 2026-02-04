# =============================================================================
# Seisei Odoo 19 Central Service - Immutable Image
# =============================================================================
# This Dockerfile builds an immutable image containing:
# - All custom addons (vendor_ops_core, qr_ordering, seisei_billing, etc.)
# - Production configuration
# - Python dependencies for addons
#
# Build context must be repository root
# Build command:
#   cd seisei-odoo19-central
#   docker build -f infra/docker/Dockerfile \
#     -t ghcr.io/cameltravel666-crypto/seisei-odoo19:latest .
# =============================================================================

FROM odoo:19.0

LABEL maintainer="Seisei Platform <ops@seisei.tokyo>"
LABEL description="Odoo 19 Central Service with custom addons"
LABEL version="1.0.0"

# Switch to root for installation
USER root

# Install system dependencies
# curl: health checks
# postgresql-client: database management
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies required by custom addons
# NOTE: Odoo 19 uses Python 3.11+ on Debian 12, --break-system-packages required (PEP 668)
#
# Dependencies by addon:
# - httpx: API clients (vendor_ops_core OCR webhook)
# - qrcode: QR code generation (qr_ordering)
# - boto3: AWS S3 integration (if needed for attachments)
RUN pip3 install --no-cache-dir --break-system-packages \
    httpx==0.27.0 \
    qrcode[pil]==7.4.2 \
    && python3 -c "import httpx; print('httpx version:', httpx.__version__)"

# Create addons directory structure
RUN mkdir -p /mnt/extra-addons && chown -R odoo:odoo /mnt/extra-addons

# Copy all custom addons from addons/
# This includes:
# - vendor_ops_core (OCR billing webhook, tenant management)
# - qr_ordering (QR code ordering system)
# - seisei_billing (multi-tenant billing)
# - seisei_hr_menu (HR customization)
COPY --chown=odoo:odoo addons/vendor_ops_core/ /mnt/extra-addons/vendor_ops_core/
COPY --chown=odoo:odoo addons/qr_ordering/ /mnt/extra-addons/qr_ordering/
COPY --chown=odoo:odoo addons/seisei_billing/ /mnt/extra-addons/seisei_billing/
COPY --chown=odoo:odoo addons/seisei_hr_menu/ /mnt/extra-addons/seisei_hr_menu/

# Set correct permissions
# Directories: 755 (rwxr-xr-x)
# Files: 644 (rw-r--r--)
RUN chmod 755 /mnt/extra-addons && \
    find /mnt/extra-addons -type d -exec chmod 755 {} \; && \
    find /mnt/extra-addons -type f -exec chmod 644 {} \;

# Create configuration directory
RUN mkdir -p /etc/odoo && chown -R odoo:odoo /etc/odoo

# Health check script
RUN echo '#!/bin/bash\ncurl -f http://localhost:8069/web/health || exit 1' > /usr/local/bin/healthcheck.sh && \
    chmod +x /usr/local/bin/healthcheck.sh

# Switch back to odoo user for runtime
USER odoo

# Expose ports
# 8069: HTTP
# 8072: Longpolling (websocket)
EXPOSE 8069 8072

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD /usr/local/bin/healthcheck.sh

# Default command (inherited from base image)
# Can be overridden in docker-compose.yml for custom addons path
CMD ["odoo", "--addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons"]
