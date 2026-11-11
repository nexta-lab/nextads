# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nds_proposal_text = fields.Text(
        string="Qué hacemos en este servicio",
        translate=True,
        help="Explicación para el cliente de en qué consiste el servicio y qué hacemos nosotros. "
             "Rellena «Qué vamos a hacer» en la página «Vuestra propuesta» cuando el presupuesto no "
             "trae un texto propio. Cada salto de línea empieza un párrafo nuevo.",
    )
