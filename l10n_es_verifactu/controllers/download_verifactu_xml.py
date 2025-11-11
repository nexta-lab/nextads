from odoo import http
from odoo.http import request
import base64

class DownloadVerifactuXMLController(http.Controller):

    @http.route('/verifactu/download/<int:invoice_id>', type='http', auth='user')
    def download_verifactu_xml(self, invoice_id, **kwargs):
        invoice = request.env['account.move'].sudo().browse(invoice_id)
        if not invoice.exists():
            return request.not_found()

        attachment = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', invoice.id),
            ('name', 'ilike', 'verifactu'),
            ('mimetype', '=', 'application/xml'),
        ], limit=1)

        if not attachment:
            return request.not_found()

        xml_data = base64.b64decode(attachment.datas)
        return request.make_response(
            xml_data,
            headers=[
                ('Content-Type', 'application/xml'),
                ('Content-Disposition', f'attachment; filename="{attachment.name}"')
            ]
        )
