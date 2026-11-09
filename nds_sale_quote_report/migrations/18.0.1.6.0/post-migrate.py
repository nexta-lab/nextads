# -*- coding: utf-8 -*-
"""La página «Vuestra propuesta» pasa del PDF del encabezado al informe del presupuesto.

* Sustituye el PDF del encabezado por la versión de dos páginas (portada y presentación).
* Pasa los textos ya escritos en la pestaña Quote Builder a los campos nuevos de la pestaña
  «Propuesta», quitando los saltos de línea que se ponían a mano para cuadrar el texto.
* Borra los recuadros de texto que ya no existen en ningún PDF.
"""
import base64
import json
import logging
import re

from odoo import SUPERUSER_ID, api
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

# recuadro del PDF -> (campo nuevo, tipo de limpieza)
MOVES = {
    '1_Asunto_de_la_propuesta': ('nds_asunto', 'line'),
    '2_Punto_de_partida': ('nds_punto_partida', 'paragraphs'),
    '3_Que_vamos_a_hacer': ('nds_que_haremos', 'paragraphs'),
    '4_Que_incluye': ('nds_incluye', 'items'),
    '5_Nota_bajo_el_importe': ('nds_nota_importe', 'line'),
    '6_Plazo_estimado': ('nds_plazo', 'line'),
}
# Recuadros que estaban en la página 3 del encabezado y desaparecen con ella
OBSOLETE_FIELDS = [name for name in MOVES if name != '1_Asunto_de_la_propuesta'] + [
    'amount_untaxed', 'validity_date',
]
BULLETS = '—–-•*·'


def _clean(text, mode):
    text = (text or '').replace('\r\n', '\n').strip()
    if not text:
        return False
    if mode == 'line':
        return ' '.join(text.split())
    if mode == 'paragraphs':
        # Párrafos separados por línea en blanco; dentro de cada uno, las líneas cortadas a mano se unen
        paragraphs = [' '.join(block.split()) for block in re.split(r'\n\s*\n', text)]
        return '\n'.join(p for p in paragraphs if p)
    # items: una línea con guion empieza un elemento; las demás continúan el anterior
    items = []
    for line in text.split('\n'):
        line = ' '.join(line.split())
        if not line:
            continue
        if line[0] in BULLETS or not items:
            items.append(line.lstrip(BULLETS).strip())
        else:
            items[-1] = '%s %s' % (items[-1], line)
    return '\n'.join(i for i in items if i)


def _extract(mapping):
    """Saca los textos de los recuadros antiguos y los quita del JSON. Devuelve {campo: valor}."""
    values = {}
    for section in (mapping or {}).values():
        if not isinstance(section, dict):
            continue
        for doc_values in section.values():
            custom = isinstance(doc_values, dict) and doc_values.get('custom_form_fields')
            if not isinstance(custom, dict):
                continue
            for old, (new, mode) in MOVES.items():
                if old in custom:
                    cleaned = _clean(custom.pop(old), mode)
                    if cleaned and new not in values:
                        values[new] = cleaned
    return values


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    header = env.ref('nds_sale_quote_report.quotation_document_nds_header', raise_if_not_found=False)
    if header:
        with file_open('nds_sale_quote_report/static/quote_builder/nextads_encabezado.pdf', 'rb') as pdf:
            header.datas = base64.b64encode(pdf.read())
        header.name = "NextaDS · Portada y presentación"
        env.flush_all()

    orders = env['sale.order'].with_context(active_test=False).search(
        [('customizable_pdf_form_fields', '!=', False)]
    )
    migrated = 0
    for order in orders:
        raw = order.customizable_pdf_form_fields
        try:
            mapping = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        values = _extract(mapping)
        if not values:
            continue
        # No se pisa nada que ya se haya escrito en la pestaña nueva
        values = {name: value for name, value in values.items() if not order[name]}
        values['customizable_pdf_form_fields'] = json.dumps(mapping) if isinstance(raw, str) else mapping
        order.write(values)
        migrated += 1

    env.flush_all()
    env['sale.pdf.form.field'].search([
        ('document_type', '=', 'quotation_document'),
        ('name', 'in', OBSOLETE_FIELDS),
        ('quotation_document_ids', '=', False),
        ('product_document_ids', '=', False),
    ]).unlink()
    env['sale.pdf.form.field']._nds_assign_paths()
    _logger.info("nds_sale_quote_report: textos de %s presupuestos pasados a la pestaña Propuesta", migrated)
