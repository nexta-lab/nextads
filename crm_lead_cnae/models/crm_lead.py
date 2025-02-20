from odoo import models, fields

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    cnae_vat = fields.Char(string="Identificacion Fiscal")
    cnae_code = fields.Char(string="CNAE")
    company_status = fields.Char(string="Situacion de la empresa")
    employee_count = fields.Integer(string="Numero de Empleados")
    incorporation_date = fields.Date(string="Fecha de constitucion")
    capital_social = fields.Float(string="Capital Social", digits=(12,2))
    annual_revenue = fields.Float(string="Facturacion Anual", digits=(12,2))
    last_balance_year = fields.Integer(string="Año del ultimo balance")