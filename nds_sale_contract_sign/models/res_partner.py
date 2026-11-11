# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    nds_nda_signed_on = fields.Date(
        string="Acuerdo de confidencialidad firmado el",
        copy=False,
        help="Fecha en que el cliente firmó el acuerdo de confidencialidad y encargo del tratamiento. "
             "Si está informada, no se vuelve a incluir en la documentación de los nuevos pedidos.",
    )

    def _nds_has_active_mandate(self):
        """True si la empresa del contacto tiene un mandato SEPA activo."""
        self.ensure_one()
        commercial = self.commercial_partner_id
        return bool(self.env['sdd.mandate'].sudo().search_count([
            ('partner_id', 'child_of', commercial.id),
            ('state', '=', 'active'),
        ]))
