# -*- coding: utf-8 -*-
from odoo import api, models

# Campos de las páginas de marca que se rellenan solos con datos del presupuesto.
# Los que empiezan por "nds_" se dejan sin ruta: son texto libre en la pestaña Quote Builder.
NDS_QUOTATION_FIELD_PATHS = {
    'partner_id__name': 'partner_id.name',
    'name': 'name',
    'order_date': 'nds_quote_date',
    'user_id__name': 'user_id.name',
    'user_id__email': 'user_id.email',
    'amount_untaxed': 'amount_untaxed',
    'validity_date': 'validity_date',
}


class SalePdfFormField(models.Model):
    _inherit = 'sale.pdf.form.field'

    @api.model
    def _nds_assign_paths(self):
        """Asigna la ruta a los campos automáticos que aún no la tengan (no pisa cambios manuales)."""
        self.env.flush_all()
        # La fecha se mostraba con hora: se corrige la ruta antigua si sigue puesta.
        self.search([
            ('document_type', '=', 'quotation_document'),
            ('name', '=', 'order_date'),
            ('path', '=', 'date_order'),
        ]).write({'path': 'nds_quote_date'})
        fields_without_path = self.search([
            ('document_type', '=', 'quotation_document'),
            ('name', 'in', list(NDS_QUOTATION_FIELD_PATHS)),
            ('path', '=', False),
        ])
        for form_field in fields_without_path:
            form_field.path = NDS_QUOTATION_FIELD_PATHS[form_field.name]
