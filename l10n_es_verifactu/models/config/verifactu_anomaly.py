# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime

class VerifactuAnomaly(models.Model):
    _name = "verifactu.anomaly"
    _description = "Anomalías VeriFactu detectadas"
    _order = "detected_at desc, id desc"

    # Contexto
    company_id = fields.Many2one(
        'res.company',
        string="Compañía",
        required=True,
        index=True,
        default=lambda self: self.env.user.company_id,
        ondelete='cascade',
    )
    move_id = fields.Many2one(
        'account.move',
        string="Factura",
        required=True,
        index=True,
        ondelete='cascade',
    )

    # Clasificación
    anomaly_type = fields.Selection([
        ('stale_pending', "Pendiente estancada"),
        ('out_of_order', "Desorden cronológico"),
    ], string="Tipo", required=True, index=True)

    severity = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Aviso'),
        ('error', 'Error'),
    ], string="Severidad", default='warning', required=True)

    message = fields.Text(string="Descripción", required=True)
    detected_at = fields.Datetime(string="Detectada", required=True, default=fields.Datetime.now)
    resolved = fields.Boolean(string="Resuelta", default=False, index=True)
    resolved_at = fields.Datetime(string="Fecha de resolución")

    # Visual
    move_name = fields.Char(related="move_id.name", string="Número", store=False)
    invoice_date = fields.Date(related="move_id.invoice_date", string="Fecha factura", store=False)
    verifactu_status = fields.Char(string="Estado VF actual", compute="_compute_vf_status", store=False)

    @api.depends('move_id')
    def _compute_vf_status(self):
        for rec in self:
            rec.verifactu_status = getattr(rec.move_id, 'verifactu_status', '') or ''

    _sql_constraints = [
        # Evita duplicados “abiertos” para la misma (move, type)
        ('uniq_open_per_move_type',
         'unique(move_id, anomaly_type, resolved)',
         "Ya existe una anomalía abierta de este tipo para la factura."),
    ]

    def action_mark_resolved(self):
        for rec in self:
            if not rec.resolved:
                rec.write({'resolved': True, 'resolved_at': fields.Datetime.now()})
