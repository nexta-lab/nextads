from odoo import models
import base64

class VerifactuAttachmentService:
    def __init__(self, invoice):
        self.invoice = invoice

    def attach_xml(self, signed_xml_str):
        """
        Crea y adjunta el archivo XML firmado a la factura.
        """
        self.invoice.ensure_one()
        filename = f"verifactu_{self.invoice.name.replace('/', '_')}.xml"

        attachment = self.invoice.env["ir.attachment"].create({
            "name": filename,
            "type": "binary",
            "res_model": self.invoice._name,
            "res_id": self.invoice.id,
            "datas": base64.b64encode(signed_xml_str.encode("utf-8")),
            "mimetype": "application/xml",
        })

        return attachment
