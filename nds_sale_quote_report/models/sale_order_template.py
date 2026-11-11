# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrderTemplate(models.Model):
    _inherit = 'sale.order.template'

    # Textos por defecto de la página «Vuestra propuesta» para los presupuestos de esta plantilla
    nds_punto_partida = fields.Text(string="Punto de partida", translate=True)
    nds_que_haremos = fields.Text(string="Qué vamos a hacer", translate=True)
    nds_incluye = fields.Text(string="Qué incluye", translate=True,
                              help="Un elemento por línea.")
