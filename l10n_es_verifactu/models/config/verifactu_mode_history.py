# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class VerifactuModeHistory(models.Model):
    _name = "verifactu.mode.history"
    _description = "Histórico de cambios de modo VeriFactu"
    _order = "change_date desc"

    mode = fields.Selection([
        ('verifactu', 'Modo VeriFactu'),
        ('no_verifactu', 'Modo No VeriFactu'),
    ], string="Modo activado", required=True)

    change_date = fields.Datetime(
        string="Fecha de cambio",
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )

    user_id = fields.Many2one(
        'res.users',
        string="Usuario",
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
        ondelete='restrict',
    )


    company_id = fields.Many2one(
        'res.company',
        string="Compañía",
        default=lambda self: self.env.user.company_id,
        required=True,
        readonly=True,
        ondelete='cascade',
    )

    notes = fields.Char(string="Comentario", readonly=True)
