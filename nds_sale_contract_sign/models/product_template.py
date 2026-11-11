# -*- coding: utf-8 -*-
from odoo import fields, models

NDS_CONTRACT_TYPES = [
    ('hosting', "Servidor y copias de seguridad"),
    ('support', "Soporte, mantenimiento y mejoras de Odoo"),
]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nds_contract_type = fields.Selection(
        NDS_CONTRACT_TYPES,
        string="Contrato al aceptar",
        help="Contrato que se incluye en la documentación para firmar cuando un presupuesto con este "
             "producto se acepta. Vacío: el producto no lleva contrato propio.",
    )
