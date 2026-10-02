from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    support = fields.Boolean(
        string='Soporte',
        tracking=True,
        help='Indica si el cliente tiene soporte activo.',
    )
