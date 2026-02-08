# Deployment Instructions for Calendar Fix

## Issue Summary

**Error**: `View types not defined map found in act_window action 452`

**Location**: http://13.159.193.191:8069/odoo/calendar

**Cause**: The calendar action in the database has 'map' in its view_mode, but Odoo 19 doesn't properly support the map view type.

## Solution

Created a new module `seisei_fixes` that updates the calendar action to remove the unsupported 'map' view mode.

## Deployment Steps

### Step 1: Pull Latest Code

```bash
cd /path/to/seisei-odoo19-central
git pull origin main  # or the appropriate branch
```

### Step 2: Install the Fix Module

```bash
# If using Docker
docker compose exec web odoo -d <database_name> -i seisei_fixes --stop-after-init

# If using command line directly
./odoo-bin -d <database_name> -i seisei_fixes --stop-after-init
```

### Step 3: Restart Odoo

```bash
# If using Docker
docker compose restart web

# If using systemd
sudo systemctl restart odoo
```

### Step 4: Verify the Fix

1. Navigate to http://13.159.193.191:8069/odoo/calendar
2. Verify that the page loads without errors
3. Check that you can switch between calendar, list, and form views

## Expected Results

- ✅ No JavaScript errors when accessing /odoo/calendar
- ✅ Calendar view loads properly
- ✅ Can switch between different views (calendar, list, form)

## Rollback Plan

If issues occur after deployment:

```bash
# Uninstall the module
docker compose exec web odoo shell -d <database_name>
>>> env['ir.module.module'].search([('name', '=', 'seisei_fixes')]).button_immediate_uninstall()
>>> exit()

# Restart Odoo
docker compose restart web
```

## Technical Details

**Module**: `seisei_fixes`
**Location**: `/addons/seisei_fixes/`
**Key File**: `data/fix_calendar_view_mode.xml`

**What it does**: Updates the `calendar.action_calendar_event` action record to use `calendar,list,form` instead of any view_mode that includes 'map'.

## Risk Assessment

- **Risk Level**: Low
- **Impact**: Fixes calendar access, no changes to business logic
- **Reversibility**: Easily reversible by uninstalling the module

## Notes

- This is a data-level fix that updates action window configuration
- No Python code changes
- No schema changes
- Safe to deploy during business hours
