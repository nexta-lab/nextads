# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models

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

    @api.depends('date_order')
    def _compute_nds_quote_date(self):
        for order in self:
            order.nds_quote_date = (
                fields.Datetime.context_timestamp(order, order.date_order).date()
                if order.date_order else False
            )

    # ------------------------------------------------------------ página «Vuestra propuesta»
    def _nds_paragraphs(self, field_name):
        """Párrafos del texto: cada línea no vacía es un párrafo."""
        self.ensure_one()
        text = self[field_name] or ''
        return [' '.join(line.split()) for line in text.splitlines() if line.strip()]

    def _nds_items(self):
        """Elementos de «Qué incluye», sin los guiones o viñetas que se hayan escrito a mano."""
        self.ensure_one()
        items = []
        for line in (self.nds_incluye or '').splitlines():
            line = ' '.join(line.split()).lstrip('—–-•*·').strip()
            if line:
                items.append(line)
        return items

    def _nds_has_proposal(self):
        """La página se imprime si el presupuesto lleva el encabezado de marca y algún texto."""
        self.ensure_one()
        has_header = any(doc.document_type == 'header' for doc in self.quotation_document_ids)
        return has_header and any(
            self[name] for name in ('nds_punto_partida', 'nds_que_haremos', 'nds_incluye')
        )

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
