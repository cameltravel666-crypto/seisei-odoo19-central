# -*- coding: utf-8 -*-
from odoo import models


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def read(self, fields=None):
        records = super().read(fields=fields)
        available_view_types = {
            selection[0] for selection in self.env["ir.ui.view"]._fields["type"].selection
        }
        if "map" not in available_view_types:
            for action in records:
                view_mode = action.get("view_mode")
                if view_mode:
                    parts = [mode for mode in view_mode.split(",") if mode != "map"]
                    if len(parts) != len(view_mode.split(",")):
                        action["view_mode"] = ",".join(parts)
                views = action.get("views")
                if views:
                    filtered_views = [view for view in views if view and view[1] != "map"]
                    if len(filtered_views) != len(views):
                        action["views"] = filtered_views
        return records


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    def get_views(self, views, options=None):
        available_view_types = {
            selection[0] for selection in self._fields["type"].selection
        }
        sanitized_views = views
        if "map" not in available_view_types and views:
            sanitized_views = [view for view in views if view and len(view) > 1 and view[1] != "map"]

        result = super().get_views(sanitized_views, options=options)

        if "map" not in available_view_types and result.get("views"):
            result["views"] = {
                view_type: data for view_type, data in result["views"].items() if view_type != "map"
            }
        return result
