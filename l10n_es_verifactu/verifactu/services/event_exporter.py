import base64
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from odoo.exceptions import UserError
from odoo import _

class VerifactuEventExporter:
    def __init__(self, invoice):
        self.invoice = invoice

    def export(self):
        try:
            events = self.invoice.env["verifactu.event.log"].search([
                ('company_id', '=', self.invoice.company_id.id)
            ])

            xml_content = self._generate_event_xml(events)
            file_name = f'verifactu_events_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xml'

            attachment = self.invoice.env["ir.attachment"].create({
                "name": file_name,
                "type": "binary",
                "res_model": "account.move",
                "res_id": self.invoice.id,
                "datas": base64.b64encode(xml_content.encode("utf-8")),
                "mimetype": "application/xml",
            })

            self.invoice.message_post(body=_(
                f"📦 Exportación de registros de eventos generados: {file_name}"
            ))

            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{attachment.id}?download=true",
                "target": "new",
            }

        except Exception as e:
            self.invoice.message_post(body=_(
                f"🛑 Error al exportar registros de eventos: {str(e)}"
            ))
            raise UserError(_(f"Error al exportar registros de eventos: {str(e)}"))

    def _generate_event_xml(self, events):
        root = ET.Element("Eventos")
        for event in events:
            evento_element = ET.SubElement(root, "Evento")
            ET.SubElement(evento_element, "Timestamp").text = event.timestamp.strftime("%Y-%m-%dT%H:%M:%S")
            ET.SubElement(evento_element, "Mensaje").text = event.name
        rough_string = ET.tostring(root, "utf-8")
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")
