# -*- coding: utf-8 -*-
from odoo import models


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def read(self, fields=None):
        # Track which fields we add for filtering so we can remove them later
        fields_to_remove = []
        
        # Always ensure view_mode and views are included for proper filtering
        # We need these fields to filter out unsupported view types like 'map'
        if fields is not None:
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
                    # Split, strip whitespace, and filter out 'map'
                    parts = [mode for mode in (m.strip() for m in view_mode.split(",")) if mode != "map"]
                    action["view_mode"] = ",".join(parts)
                
                # Filter views field
                # Views are tuples: (view_id, view_type) where view_id is int or False
                views = action.get("views")
                if views and isinstance(views, list):
                    # Filter out any views with 'map' type
                    # Check len >= 2 to ensure tuple has both view_id and view_type
                    filtered_views = [view for view in views if view and len(view) >= 2 and view[1] != "map"]
                    action["views"] = filtered_views
        
        # Remove fields that were not originally requested to maintain API contract
        if fields_to_remove:
            for action in records:
                for field in fields_to_remove:
                    action.pop(field, None)
        
        return records
