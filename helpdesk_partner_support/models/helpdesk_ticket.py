from odoo import fields, models


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    partner_support = fields.Boolean(
        string='Soporte',
        related='partner_id.commercial_partner_id.support',
        store=True,
        readonly=True,
    )
