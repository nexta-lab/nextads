# -*- coding: utf-8 -*-
# (c) 2024 Nexta - Jaume Basiero <jbasiero@nextads.es>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/a
{
    'name': "CRM CNAE",

    'summary': """
        Este módulo añade los campos del CNAE en la vista leads del CRM
    """,

    'description': """
        Este módulo añade los campos del CNAE en la vista leads del CRM

    """,

    'author': "NextaDS",
    'website': "http://www.nextads.es",
    'license': "LGPL-3",

    'category': 'Stock',
    'version': '16.0.0.1',

    'depends': ['crm'],

    'data': [
        'views/view_crm_lead_form_cnae.xml',
    ],
}