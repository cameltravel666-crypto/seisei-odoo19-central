# -*- coding: utf-8 -*-
from odoo import models


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def read(self, fields=None):
        records = super().read(fields=fields)
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
