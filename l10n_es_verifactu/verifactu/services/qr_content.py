# verifactu/services/qr_content.py

import logging
from io import BytesIO
from urllib.parse import urlencode, urlparse

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from odoo import fields
from odoo.exceptions import UserError

from ..utils.verifactu_xml_validator import VerifactuXMLValidator  # ✅ limpiar NIF

_logger = logging.getLogger(__name__)


class VerifactuQRContentGenerator:
    def __init__(self, invoice, config, factura_verificable=True):
        self.invoice = invoice
        self.config = config
        self.factura_verificable = factura_verificable

    # ---------- Helpers compat 11–18 ----------
    def _get_invoice_number(self, invoice):
        """Odoo 11/12: number ; Odoo 13+: name"""
        return getattr(invoice, 'number', None) or getattr(invoice, 'name', None)

    def _get_invoice_date(self, invoice):
        """Odoo 11/12: date_invoice ; Odoo 14+: invoice_date"""
        return getattr(invoice, 'date_invoice', None) or getattr(invoice, 'invoice_date', None)

    def _is_test_environment(self):
        """Detecta TEST si el host del endpoint contiene 'prewww' (p.ej. prewww2)."""
        url = (self.config.endpoint_url or "").strip()
        host = urlparse(url).netloc or ""
        return 'prewww' in host

    # ---------- API pública ----------
    def generate_content(self):
        invoice = self.invoice
        invoice.ensure_one()

        # Emisor (NIF) desde la compañía
        company = invoice.company_id
        company_vat_raw = (company.vat or "").strip()
        emisor_nif = VerifactuXMLValidator.clean_nif_es(company_vat_raw) if company_vat_raw else ""
        if not emisor_nif:
            raise UserError("La compañía no tiene un NIF configurado. Es obligatorio para generar el QR.")

        num_serie = self._get_invoice_number(invoice)
        if not num_serie:
            raise UserError("La factura no tiene número asignado.")

        if not self.config.endpoint_url:
            raise UserError("Para generar el QR es necesario configurar el endpoint.")

        # Fecha (fallback sin write para evitar bucle)
        fecha_obj = self._get_invoice_date(invoice)
        if not fecha_obj:
            _logger.warning(
                f"[VeriFactu QR] La factura {num_serie or '[sin número]'} no tenía fecha de expedición, "
                "usando la actual como fallback."
            )
            fecha_obj = fields.Date.context_today(invoice)

        # Parámetros QR
        fecha = fecha_obj.strftime("%d-%m-%Y")
        importe = f"{invoice.amount_total:.2f}"

        query = urlencode({
            "nif": emisor_nif,
            "numserie": num_serie,
            "fecha": fecha,
            "importe": importe
        }, encoding='utf-8')

        # Selección de URL oficial (TEST vs PROD) y (Verifactu vs NoVerifactu)
        is_test = self._is_test_environment()
        if self.factura_verificable:
            qr_url_base = (
                "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR"
                if is_test else
                "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR"
            )
        else:
            qr_url_base = (
                "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQRNoVerifactu"
                if is_test else
                "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQRNoVerifactu"
            )

        return f"{qr_url_base}?{query}"

    def generate_qr_binary(self):
        content = self.generate_content()
        qr = qrcode.QRCode(
            error_correction=ERROR_CORRECT_M,
            box_size=4,
            border=1
        )
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image(fill="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
