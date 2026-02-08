# Pull Request Summary

## Summary / 摘要
Fix calendar JavaScript error by removing unsupported 'map' view mode from calendar action. Created new `seisei_fixes` module to apply this fix.

修复日历 JavaScript 错误，通过移除日历操作中不支持的 'map' 视图模式。创建了新的 `seisei_fixes` 模块来应用此修复。

## Issue Link / 关联问题
- Closes #[Prod Change] - Calendar error "View types not defined map found in act_window action 452"

## Risk / 风险
**P0 - Low Risk / 低风险**

- Only updates action window configuration (data-level fix)
- No Python code changes
- No database schema changes
- Easily reversible by uninstalling the module
- Safe to deploy during business hours

只更新操作窗口配置（数据级修复）
- 无 Python 代码更改
- 无数据库模式更改
- 通过卸载模块即可轻松回滚
- 可在营业时间安全部署

## Scope / 影响范围
**Systems/Modules:**
- `/addons/seisei_fixes/` - New technical fixes module
- Calendar module action configuration

**Affected URLs:**
- http://13.159.193.191:8069/odoo/calendar

**影响范围:**
- 新增技术修复模块
- 日历模块操作配置
- 日历访问 URL

## Do-Not-Touch / 禁止触碰
- ✅ No secrets or credentials
- ✅ No billing engine changes
- ✅ No infrastructure or deploy logic changes
- ✅ No data retention policy changes

## Verification / 验证方式

### Pre-Installation (Expected Failure)
1. Navigate to http://13.159.193.191:8069/odoo/calendar
2. Expect error: "View types not defined map found in act_window action 452"

### Installation Steps
```bash
docker compose exec web odoo -d <database> -i seisei_fixes --stop-after-init
docker compose restart web
```

### Post-Installation (Expected Success)
1. Navigate to http://13.159.193.191:8069/odoo/calendar
2. ✅ Page loads without JavaScript errors
3. ✅ Calendar view displays properly
4. ✅ Can switch between calendar, list, and form views
5. ✅ No console errors in browser DevTools

### 验证步骤
安装前：访问日历页面应显示错误
安装后：
- 页面正常加载无 JavaScript 错误
- 日历视图正确显示
- 可在日历、列表、表单视图间切换
- 浏览器控制台无错误

## Rollback / 回滚方案

### Method 1: Uninstall Module
```bash
docker compose exec web odoo shell -d <database>
>>> env['ir.module.module'].search([('name', '=', 'seisei_fixes')]).button_immediate_uninstall()
>>> exit()
docker compose restart web
```

### Method 2: Revert PR
```bash
git revert <commit-hash>
git push origin main
# Redeploy
```

**Rollback Time:** < 5 minutes
**回滚时间：** 5分钟内

## Evidence / 证据

### Error Message
```
Odoo客户端错误
UncaughtPromiseError
Uncaught Promise > View types not defined map found in act_window action 452

Error: View types not defined map found in act_window action 452
    at _executeActWindowAction (http://13.159.193.191:8069/web/assets/67978db/web.assets_web.min.js:10640:26)
    at doAction (http://13.159.193.191:8069/web/assets/67978db/web.assets_web.min.js:10665:8)
    at async Object.selectMenu (http://13.159.193.191:8069/web/assets/67978db/web.assets_web.min.js:10861:1)
```

### Root Cause
The calendar action in Odoo 19 database includes 'map' in its view_mode, but the 'map' view type is not properly supported in Odoo 19.

日历操作在 Odoo 19 数据库中包含 'map' 视图模式，但 Odoo 19 不支持此视图类型。

### Solution
- Created `seisei_fixes` module
- Updates `calendar.action_calendar_event` to use `calendar,list,form` view modes only
- Removes unsupported 'map' view mode

创建了 `seisei_fixes` 模块
- 更新日历操作仅使用 `calendar,list,form` 视图模式
- 移除不支持的 'map' 视图模式

## Files Changed
```
A  addons/seisei_fixes/__init__.py
A  addons/seisei_fixes/__manifest__.py
A  addons/seisei_fixes/README.md
A  addons/seisei_fixes/data/fix_calendar_view_mode.xml
A  DEPLOYMENT_CALENDAR_FIX.md
```

## Technical Details

**Module Structure:**
```
seisei_fixes/
├── __init__.py                          # Module init
├── __manifest__.py                       # Module manifest
├── README.md                            # Module documentation
└── data/
    └── fix_calendar_view_mode.xml       # Calendar action fix
```

**Key Change:**
```xml
<record id="calendar.action_calendar_event" model="ir.actions.act_window">
    <field name="view_mode">calendar,list,form</field>
</record>
```

## Deployment Timeline
- **Change Window:** 2025-02-08
- **Estimated Downtime:** None (hot deployable)
- **Deployment Time:** < 2 minutes

## Approvals / 审批
- [ ] Owner approval obtained / 已获得Owner审批
- [ ] Security review completed / 已完成安全审核
- [ ] Rollback plan reviewed / 回滚方案已评审
