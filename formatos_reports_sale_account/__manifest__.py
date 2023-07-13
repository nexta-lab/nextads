# -*- coding: utf-8 -*-
# (c) 2023 Nexta - Jaume Basiero <jbasiero@nextads.es>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/a
{
    'name': "Formatos para reports en Ventas y facturación",

    'summary': """
        Este módulo añade modificaciones a los siguientes reports:
            · Presupuesto / Pedido
            · Factura""",

    'description': """
        Este módulo añade modificaciones a los siguientes reports:
            · Presupuesto / Pedido
            · Factura

            
    """,

    'author': "NextaDS",
    'website': "http://www.nextads.es",
    'license': "LGPL-3",

    'category': 'Account',
    'version': '15.2.5',

    'depends': ['sale_management',
                'sale',
                'stock',
                'account',
                'web',
                'repair'
                ],

    'data': [
        'report/report_pedido.xml',
        'report/report_invoice_document_nds.xml',

    ],
     'css': [
            'static/src/css/report_style.css',
        ],

}
