# -*- coding: utf-8 -*-
from odoo import api, models

# Nombres en el menú Imprimir: el informe completo (con las páginas de marca) y el
# presupuesto solo, para no confundir las dos opciones que antes se llamaban igual.
NDS_REPORT_NAMES = {
    'sale.action_report_saleorder': {
        'es_ES': "Presupuesto completo (con portada)",
        'en_US': "Full quotation (with cover pages)",
    },
    'sale_pdf_quote_builder.action_report_saleorder_raw': {
        'es_ES': "Presupuesto sin portada",
        'en_US': "Quotation without cover pages",
    },
}


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def _nds_rename_quote_reports(self):
        installed_langs = {code for code, _name in self.env['res.lang'].get_installed()}
        for xmlid, names in NDS_REPORT_NAMES.items():
            report = self.env.ref(xmlid, raise_if_not_found=False)
            if not report:
                continue
            for lang, name in names.items():
                if lang in installed_langs:
                    report.with_context(lang=lang).name = name
