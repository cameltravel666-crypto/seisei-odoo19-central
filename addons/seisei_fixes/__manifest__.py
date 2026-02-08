# -*- coding: utf-8 -*-
{
    'name': 'Seisei Fixes',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Technical fixes for Seisei Odoo deployment',
    'description': """
Seisei Technical Fixes
======================
This module contains technical fixes and patches for the Seisei Odoo deployment.

Fixes included:
- Remove invalid 'map' view mode from calendar action to prevent JavaScript errors
    """,
    'author': 'Seisei',
    'website': 'https://seisei.io',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'calendar',
    ],
    'data': [
        'data/fix_calendar_view_mode.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
