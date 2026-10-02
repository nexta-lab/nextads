{
    'name': 'Helpdesk Partner Support',
    'summary': 'Checkbox de soporte activo en contactos y tickets de helpdesk',
    'author': 'NextaDS',
    'website': 'http://www.nextads.es',
    'license': 'LGPL-3',
    'category': 'Services/Helpdesk',
    'version': '18.0.1.0.0',
    'depends': ['helpdesk'],
    'data': [
        'views/res_partner_views.xml',
        'views/helpdesk_ticket_views.xml',
    ],
    'installable': True,
}
