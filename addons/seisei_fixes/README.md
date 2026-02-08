# Seisei Fixes Module

Technical fixes module for Seisei Odoo 19 deployment.

## Purpose

This module contains technical fixes and patches to resolve issues in the Seisei Odoo deployment.

## Fixes Included

### 1. Calendar View Mode Fix

**Issue**: `View types not defined map found in act_window action 452`

**Symptom**: When accessing `/odoo/calendar`, a JavaScript error occurs:
```
UncaughtPromiseError
Uncaught Promise > View types not defined map found in act_window action 452
Error: View types not defined map found in act_window action 452
```

**Cause**: The calendar action in Odoo contains 'map' in its view_mode field, but the 'map' view type is not properly defined or supported in Odoo 19.

**Solution**: This module updates the calendar action to use only supported view modes: `calendar,list,form` (removing 'map').

## Installation

### Prerequisites

- Odoo 19
- `calendar` module installed (usually part of base Odoo)

### Install via Docker

```bash
docker compose exec web odoo -d <database> -i seisei_fixes --stop-after-init
docker compose restart web
```

### Install via Command Line

```bash
./odoo-bin -d <database> -i seisei_fixes --stop-after-init
```

### Upgrade Existing Installation

```bash
docker compose exec web odoo -d <database> -u seisei_fixes --stop-after-init
docker compose restart web
```

## Verification

After installing this module:

1. Navigate to `/odoo/calendar` in your browser
2. The calendar view should load without errors
3. You should be able to switch between calendar, list, and form views

## Rollback

If needed, you can uninstall this module:

```bash
# Via Odoo shell
docker compose exec web odoo shell -d <database>
>>> env['ir.module.module'].search([('name', '=', 'seisei_fixes')]).button_immediate_uninstall()
```

Note: Uninstalling will revert the calendar action to its previous state, which may cause the error to reappear if the underlying issue hasn't been resolved elsewhere.

## Files

```
seisei_fixes/
├── __init__.py
├── __manifest__.py
├── README.md
└── data/
    └── fix_calendar_view_mode.xml  # Fixes calendar action view_mode
```

## License

LGPL-3

## Version History

- **19.0.1.0.0**: Initial release with calendar view mode fix
