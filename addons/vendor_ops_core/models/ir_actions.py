# -*- coding: utf-8 -*-
from odoo import models


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def read(self, fields=None):
        # Track if we need to add fields for filtering
        original_fields = fields
        fields_to_remove = []
        
        # Always ensure view_mode and views are included for proper filtering
        # We need these fields to filter out unsupported view types like 'map'
        if fields is not None:
            # Convert fields to list if it's not already
            if isinstance(fields, str):
                fields_list = [fields]
            else:
                fields_list = list(fields)
            
            # Add view_mode and views if not already present
            if 'view_mode' not in fields_list:
                fields_list.append('view_mode')
                fields_to_remove.append('view_mode')
            if 'views' not in fields_list:
                fields_list.append('views')
                fields_to_remove.append('views')
            
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
                # Filter view_mode field (comma-separated string of view types)
                view_mode = action.get("view_mode")
                if view_mode and isinstance(view_mode, str):
                    parts = [mode.strip() for mode in view_mode.split(",") if mode.strip() != "map"]
                    action["view_mode"] = ",".join(parts)
                
                # Filter views field (list of tuples: [(view_id, view_type), ...])
                # Each tuple contains view_id (int or False) and view_type (str)
                views = action.get("views")
                if views and isinstance(views, list):
                    filtered_views = [view for view in views if view and len(view) >= 2 and view[1] != "map"]
                    action["views"] = filtered_views
        
        # Remove fields that were not originally requested
        if fields_to_remove:
            for action in records:
                for field in fields_to_remove:
                    action.pop(field, None)
        
        return records
