# -*- coding: utf-8 -*-
"""Recuadros de texto de la portada con nombres claros.

Sustituye el PDF del encabezado de marca por la versión con los nuevos nombres y
pasa los textos ya escritos en los presupuestos a esos nombres, para no perderlos.
"""
import base64
import json
import logging

from odoo import SUPERUSER_ID, api
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

RENAMES = {
    'nds_titulo': '1_Asunto_de_la_propuesta',
    'nds_punto_partida': '2_Punto_de_partida',
    'nds_que_haremos': '3_Que_vamos_a_hacer',
    'nds_incluye': '4_Que_incluye',
    'nds_nota_importe': '5_Nota_bajo_el_importe',
    'nds_plazo': '6_Plazo_estimado',
}


def _rename_keys(mapping):
    """Renombra las claves antiguas dentro de {'header'|'footer'|'line': {doc: {'custom_form_fields': {...}}}}."""
    changed = False
    for section in (mapping or {}).values():
        if not isinstance(section, dict):
            continue
        for doc_values in section.values():
            if not isinstance(doc_values, dict):
                continue
            custom = doc_values.get('custom_form_fields')
            if not isinstance(custom, dict):
                continue
            for old, new in RENAMES.items():
                if old in custom:
                    custom.setdefault(new, custom[old])
                    del custom[old]
                    changed = True
    return changed


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    header = env.ref('nds_sale_quote_report.quotation_document_nds_header', raise_if_not_found=False)
    if header:
        with file_open('nds_sale_quote_report/static/quote_builder/nextads_encabezado.pdf', 'rb') as pdf:
            header.datas = base64.b64encode(pdf.read())
        env.flush_all()

    orders = env['sale.order'].with_context(active_test=False).search(
        [('quotation_document_ids', '!=', False)]
    )
    migrated = 0
    for order in orders:
        raw = order.customizable_pdf_form_fields
        if not raw:
            continue
        mapping = json.loads(raw) if isinstance(raw, str) else raw
        if _rename_keys(mapping):
            order.customizable_pdf_form_fields = json.dumps(mapping) if isinstance(raw, str) else mapping
            migrated += 1

    env.flush_all()
    env['sale.pdf.form.field'].search([
        ('document_type', '=', 'quotation_document'),
        ('name', 'in', list(RENAMES)),
        ('quotation_document_ids', '=', False),
        ('product_document_ids', '=', False),
    ]).unlink()
    _logger.info("nds_sale_quote_report: textos de %s presupuestos pasados a los nuevos nombres", migrated)
