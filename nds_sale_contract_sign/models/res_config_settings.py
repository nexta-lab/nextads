# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nds_contract_signer_id = fields.Many2one(
        related='company_id.nds_contract_signer_id', readonly=False)
    nds_contract_representative = fields.Char(
        related='company_id.nds_contract_representative', readonly=False)
    nds_contract_representative_title = fields.Char(
        related='company_id.nds_contract_representative_title', readonly=False)
    nds_contract_city = fields.Char(
        related='company_id.nds_contract_city', readonly=False)
    nds_contract_support_email = fields.Char(
        related='company_id.nds_contract_support_email', readonly=False)
