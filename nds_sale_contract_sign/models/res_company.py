# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    nds_contract_signer_id = fields.Many2one(
        'res.users',
        string="Firmante de los contratos",
        help="Persona que firma la documentación en nombre de la empresa, después del cliente.",
    )
    nds_contract_representative = fields.Char(
        string="Representante legal",
        help="Nombre que aparece en los contratos, por ejemplo «D. Juan Vicente Romero Barril».",
    )
    nds_contract_representative_title = fields.Char(
        string="Cargo del representante",
        help="Por ejemplo «administrador».",
    )
    nds_contract_city = fields.Char(
        string="Lugar de firma",
        help="Localidad que figura en el encabezamiento de los contratos.",
    )
    nds_contract_support_email = fields.Char(
        string="Correo de soporte para contratos",
        help="Dirección a la que el cliente envía las peticiones de soporte (contrato de soporte).",
    )
