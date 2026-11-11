# -*- coding: utf-8 -*-
import re

from odoo import Command, api, fields, models

# Marcas internas de las descripciones que no se enseñan al cliente: «(horas)», «(hora)», «(h)»
NDS_INTERNAL_MARKS = re.compile(r'\s*\((?:horas?|h)\)', re.IGNORECASE)

# Pedidos que no son presupuestos comerciales hechos a mano: tienda online,
# renovaciones y ampliaciones de suscripciones. A estos no se les añaden las páginas de marca.
NDS_SKIP_DEFAULT_DOCS_FIELDS = ('website_id', 'subscription_id', 'origin_order_id')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    nds_quote_date = fields.Date(
        string="Fecha del presupuesto (sin hora)",
        compute='_compute_nds_quote_date',
        help="Fecha del pedido sin la hora, para la portada del PDF de marca.",
    )

    # Textos de la portada y de la página «Vuestra propuesta» (pestaña Propuesta del presupuesto)
    nds_asunto = fields.Char(
        string="Asunto de la propuesta",
        help="Aparece en la portada, debajo del nombre del cliente.",
    )
    nds_punto_partida = fields.Text(
        string="Punto de partida",
        help="Qué necesita el cliente. Escribid seguido: cada salto de línea empieza un párrafo nuevo.",
    )
    nds_que_haremos = fields.Text(
        string="Qué vamos a hacer",
        help="Cómo lo vamos a resolver. Cada salto de línea empieza un párrafo nuevo.",
    )
    nds_incluye = fields.Text(
        string="Qué incluye",
        help="Un elemento por línea. No hace falta poner guiones: la lista se dibuja sola.",
    )
    nds_nota_importe = fields.Char(
        string="Nota bajo el importe",
        help="Por ejemplo, horas y precio por hora, o lo que no está incluido.",
    )
    nds_plazo = fields.Char(string="Plazo estimado")
    nds_proposal_missing = fields.Boolean(
        string="Falta «Qué vamos a hacer»", compute='_compute_nds_proposal_missing')

    @api.depends('nds_que_haremos', 'sale_order_template_id', 'order_line.product_id')
    def _compute_nds_proposal_missing(self):
        for order in self:
            order.nds_proposal_missing = order._nds_proposal_missing()

    @api.depends('date_order')
    def _compute_nds_quote_date(self):
        for order in self:
            order.nds_quote_date = (
                fields.Datetime.context_timestamp(order, order.date_order).date()
                if order.date_order else False
            )

    # ------------------------------------------------------------ página «Vuestra propuesta»
    # ------------------------------------------------------------ textos de presentación
    @api.model
    def _nds_clean_title(self, text):
        """Quita las marcas internas de la descripción, como «(horas)», al presentarla al cliente."""
        text = NDS_INTERNAL_MARKS.sub('', text or '')
        return ' '.join(text.split())

    def _nds_line_parts(self, line):
        """(título, [detalle]) de una línea: título sin repetir el producto y sin marcas internas."""
        pname = line.product_id.display_name or ''
        text = (line.name or '').strip()
        if pname and text.startswith(pname) and text[len(pname):].strip():
            text = text[len(pname):].strip()
        rows = [row.strip() for row in text.split('\n')]
        rows = [row for row in rows if row]
        if not rows:
            return self._nds_clean_title(pname), []
        return self._nds_clean_title(rows[0]), rows[1:]

    def _nds_effective_text(self, field_name):
        """Texto de la propuesta: el del presupuesto o, si está vacío, el de su plantilla y sus productos."""
        self.ensure_one()
        if self[field_name]:
            return self[field_name]
        template = self.sale_order_template_id
        if template and field_name in template._fields and template[field_name]:
            return template[field_name]
        if field_name == 'nds_que_haremos':
            texts = []
            for product in self.order_line.filtered(lambda l: not l.display_type).product_id.product_tmpl_id:
                if product.nds_proposal_text and product.nds_proposal_text not in texts:
                    texts.append(product.nds_proposal_text)
            return '\n'.join(texts)
        if field_name == 'nds_incluye':
            titles = []
            for line in self.order_line.filtered(lambda l: not l.display_type and l.product_id):
                title = self._nds_line_parts(line)[0]
                if title and title not in titles:
                    titles.append(title)
            return '\n'.join(titles)
        return ''

    def _nds_paragraphs(self, field_name):
        """Párrafos del texto: cada línea no vacía es un párrafo."""
        self.ensure_one()
        text = self._nds_effective_text(field_name) or ''
        return [' '.join(line.split()) for line in text.splitlines() if line.strip()]

    def _nds_items(self):
        """Elementos de «Qué incluye», sin los guiones o viñetas que se hayan escrito a mano."""
        self.ensure_one()
        items = []
        for line in (self._nds_effective_text('nds_incluye') or '').splitlines():
            line = self._nds_clean_title(' '.join(line.split()).lstrip('—–-•*·').strip())
            if line:
                items.append(line)
        return items

    def _nds_has_proposal(self):
        """La página «Vuestra propuesta» va siempre que el presupuesto lleve la portada de marca:
        si no hay textos propios, se completa con los de la plantilla, los productos y las líneas."""
        self.ensure_one()
        has_header = any(doc.document_type == 'header' for doc in self.quotation_document_ids)
        return has_header and bool(
            self._nds_paragraphs('nds_punto_partida') or self._nds_paragraphs('nds_que_haremos')
            or self._nds_items())

    def _nds_proposal_missing(self):
        """Avisos para el comercial: textos de la propuesta que se están rellenando solos o faltan."""
        self.ensure_one()
        return not self.nds_que_haremos and not self._nds_effective_text('nds_que_haremos')

    def _nds_note_groups(self):
        """Condiciones en bloques (título de cláusula + su texto) para que no se separen al paginar."""
        self.ensure_one()
        from markupsafe import Markup
        html = str(self.note or '')
        parts = re.split(r'(?=<p[^>]*>\s*<(?:strong|b)>)', html)
        return [Markup(part) for part in parts if part.strip()]

    def _nds_portal_branded(self):
        """El enlace del presupuesto se muestra con el diseño de marca si lleva la portada de NextaDS."""
        self.ensure_one()
        header = self.env.ref('nds_sale_quote_report.quotation_document_nds_header', raise_if_not_found=False)
        return bool(header) and header in self.sudo().quotation_document_ids

    @api.model
    def _nds_default_quote_documents(self):
        """Encabezado y pie de marca de NextaDS, si siguen existiendo y están activos."""
        documents = self.env['quotation.document']
        for xmlid in ('nds_sale_quote_report.quotation_document_nds_header',
                      'nds_sale_quote_report.quotation_document_nds_footer'):
            document = self.env.ref(xmlid, raise_if_not_found=False)
            if document and document.active:
                documents |= document
        return documents

    @staticmethod
    def _nds_has_documents(value):
        """True si los valores de quotation_document_ids traen algún documento."""
        if not value:
            return False
        for command in value:
            if isinstance(command, int):
                return True
            if isinstance(command, (list, tuple)):
                if command[0] == Command.SET and command[2]:
                    return True
                if command[0] in (Command.LINK, Command.CREATE):
                    return True
        return False

    @api.model_create_multi
    def create(self, vals_list):
        """Los presupuestos nuevos llevan marcadas por defecto las páginas de marca."""
        documents = self._nds_default_quote_documents()
        if documents and not self.env.context.get('nds_skip_default_quote_documents'):
            for vals in vals_list:
                if self._nds_has_documents(vals.get('quotation_document_ids')):
                    continue
                if any(vals.get(field_name) for field_name in NDS_SKIP_DEFAULT_DOCS_FIELDS):
                    continue
                company_id = vals.get('company_id') or self.env.company.id
                allowed = documents.filtered(
                    lambda doc: not doc.company_id or doc.company_id.id == company_id
                )
                if allowed:
                    vals['quotation_document_ids'] = [Command.set(allowed.ids)]
        return super().create(vals_list)
