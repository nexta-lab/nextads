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

    @api.depends('date_order')
    def _compute_nds_quote_date(self):
        for order in self:
            order.nds_quote_date = (
                fields.Datetime.context_timestamp(order, order.date_order).date()
                if order.date_order else False
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
