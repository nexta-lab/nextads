from odoo import models, fields

class VerifactuEventLog(models.Model):
    _name = "verifactu.event.log"
    _description = "Log de eventos de VeriFactu"

    name = fields.Char(string="Mensaje del evento")
    invoice_id = fields.Many2one("account.move", string="Factura relacionada")
    timestamp = fields.Datetime(string="Fecha y hora", default=fields.Datetime.now)
    company_id = fields.Many2one("res.company", string="Compañía", required=True, default=lambda self: self.env.company)

