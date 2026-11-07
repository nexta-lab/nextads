# -*- coding: utf-8 -*-
# (c) 2026 Nexta Digital Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
{
    'name': "Presupuesto con diseño de marca NextaDS",
    'summary': "Rediseña el PDF del presupuesto / pedido de venta con la identidad de NextaDS "
               "para que encaje con las páginas del PDF Quote Builder.",
    'description': """
Cambia solo el informe de presupuesto / pedido de venta (no facturas ni albaranes):

* Cabecera propia con el logotipo y la referencia del documento.
* Pie con los datos legales de la empresa, banda de color y paginación.
* Bloque de datos (cliente, número, fecha, validez, comercial, plan de suscripción).
* Tabla de líneas con el título de cada servicio destacado y la descripción debajo.
* Totales y condiciones con la tipografía de la marca (Inter y Source Serif 4, OFL).
* Formato de papel propio para el informe de presupuesto y la factura proforma.
* Encabezado (portada, presentación y propuesta) y pie de marca para el PDF Quote Builder.
""",
    'author': "Nexta Digital Solutions",
    'website': "https://www.nextads.es",
    'license': "LGPL-3",
    'category': 'Sales/Sales',
    'version': '18.0.1.3.0',
    'depends': [
        'sale_management',
        'sale_pdf_quote_builder',
    ],
    'data': [
        'report/paperformat.xml',
        'report/external_layout.xml',
        'report/sale_order_report.xml',
        'data/quotation_documents.xml',
        'data/form_field_paths.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'nds_sale_quote_report/static/src/scss/quote_report.scss',
        ],
    },
    'installable': True,
    'application': False,
}
