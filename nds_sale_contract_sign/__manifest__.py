# -*- coding: utf-8 -*-
# (c) 2026 Nexta Digital Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
{
    'name': "Contrato y SEPA para firmar al aceptar el presupuesto",
    'summary': "Al aceptar un presupuesto en el portal, prepara la documentación que corresponda "
               "(acuerdo de confidencialidad, contratos de servidor y de soporte y orden SEPA) y "
               "la envía para firmar con Firma electrónica desde el propio presupuesto.",
    'description': """
Cuando el cliente acepta y firma el presupuesto en el portal:

* Se genera un único PDF con los documentos que correspondan:
  - Acuerdo de confidencialidad y encargo del tratamiento, si el cliente aún no lo tiene firmado.
  - Contrato de servidor y copias de seguridad, si el presupuesto lleva productos de alojamiento.
  - Contrato de soporte, mantenimiento y mejoras, si lleva productos de soporte.
  - Página de firmas de las dos partes.
  - Orden de domiciliación SEPA, si hay cuotas recurrentes y el cliente no tiene un mandato activo.
* Se crea la solicitud de firma (app Firma) con el cliente como primer firmante y NextaDS como
  segundo, y se publica el enlace en el historial del presupuesto (portal y correo).
* Al completarse la firma, el PDF firmado se adjunta al pedido, se anota la fecha del acuerdo
  de confidencialidad en el cliente y, si hay SEPA, se crea la cuenta bancaria y el mandato en
  borrador con una actividad para validarlo.

El tipo de contrato de cada servicio se indica en la ficha del producto (pestaña Ventas).
También se puede enviar a mano con el botón «Enviar documentación para firmar».
""",
    'author': "Nexta Digital Solutions",
    'website': "https://www.nextads.es",
    'license': "LGPL-3",
    'category': 'Sales/Sales',
    'version': '18.0.1.0.0',
    'depends': [
        'nds_sale_quote_report',
        'sale_subscription',
        'account_sepa_direct_debit',
        'sign',
    ],
    'data': [
        'data/company_data.xml',
        'report/contract_report.xml',
        'views/product_views.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/sale_portal_templates.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'nds_sale_contract_sign/static/src/scss/contract_report.scss',
        ],
        'web.assets_frontend': [
            'nds_sale_contract_sign/static/src/scss/portal_sign.scss',
        ],
    },
    'installable': True,
    'application': False,
}
