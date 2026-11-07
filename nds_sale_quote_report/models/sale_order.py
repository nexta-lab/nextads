# -*- coding: utf-8 -*-
from odoo import api, fields, models


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
