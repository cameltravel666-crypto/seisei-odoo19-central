# -*- coding: utf-8 -*-
from odoo import models


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def read(self, fields=None):
        # Always ensure view_mode and views are included for proper filtering
        # We need these fields to filter out unsupported view types like 'map'
        if fields is not None:
            fields_list = list(fields) if isinstance(fields, (list, tuple)) else [fields]
            # Add view_mode and views if not already present
            if 'view_mode' not in fields_list:
                fields_list.append('view_mode')
            if 'views' not in fields_list:
                fields_list.append('views')
            records = super().read(fields=fields_list)
        else:
            records = super().read(fields=fields)
        
        # Check which view types are available in the system
        available_view_types = {
            selection[0] for selection in self.env["ir.ui.view"]._fields["type"].selection
        }
        
        # Filter out unsupported view types (like 'map' if not installed)
        if "map" not in available_view_types:
            for action in records:
                # Filter view_mode field
                view_mode = action.get("view_mode")
                if view_mode and isinstance(view_mode, str):
                    parts = [mode.strip() for mode in view_mode.split(",") if mode.strip() != "map"]
                    action["view_mode"] = ",".join(parts)
                
                # Filter views field (list of tuples: [(view_id, view_type), ...])
                views = action.get("views")
                if views and isinstance(views, list):
                    filtered_views = [view for view in views if view and len(view) >= 2 and view[1] != "map"]
                    action["views"] = filtered_views
        
        return records
