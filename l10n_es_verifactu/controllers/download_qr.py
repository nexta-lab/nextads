# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import qrcode
import io
import re

class VerifactuDownloadQRController(http.Controller):

    @http.route(
        "/verifactu/download_qr/<int:invoice_id>",
        type="http",
        auth="user",
        website=True,
    )
    def download_qr(self, invoice_id, **kwargs):
        """
        Descarga un PNG con el QR de verificación para la factura indicada.
        Compat: Odoo 10–12 (account.invoice) y 13+ (account.move).
        Lógica:
          1) Intentar usar la URL persistida en verifactu_qr_url.
          2) Si no existe, regenerarla on-the-fly usando el mismo generador del mixin.
          3) Si falla, fallback a la URL legacy con el hash (truncado).
        """

        # 1) Localizar la factura en move (v13+) o invoice (v10–12)
        Invoice = request.env["account.move"].sudo()
        invoice = Invoice.browse(invoice_id)
        if not invoice.exists():
            Invoice = request.env["account.invoice"].sudo()
            invoice = Invoice.browse(invoice_id)
        if not invoice.exists():
            return request.not_found()

        # 2) Nombre/numero y hash (para fallback)
        inv_number = (getattr(invoice, "name", None) or getattr(invoice, "number", "") or "").strip()
        verifactu_hash = (getattr(invoice, "verifactu_hash", "") or "").strip()
        hash_preview = verifactu_hash[:16] if verifactu_hash else "NOHASH"

        # 3) Intentar usar la URL persistida
        verification_url = (getattr(invoice, "verifactu_qr_url", "") or "").strip()

        # 4) Si no hay URL, intentar generarla en caliente con el generador
        if not verification_url:
            try:
                # Import relativo a como lo tienes en el mixin
                try:
                    from ..verifactu.services.qr_content import VerifactuQRContentGenerator
                except Exception:
                    # Si el controlador vive en verifactu/controllers y services está en verifactu/services
                    from ..verifactu.services.qr_content import VerifactuQRContentGenerator  # fallback ruta

                # Resolver config
                Config = request.env["verifactu.endpoint.config"].sudo()
                config = Config.search([("company_id", "=", invoice.company_id.id)], limit=1)
                factura_verificable = not bool(getattr(invoice, "verifactu_noverifactu", False))

                if config:
                    gen = VerifactuQRContentGenerator(invoice, config, factura_verificable=factura_verificable)
                    verification_url = (gen.generate_content() or "").strip()

                    # Si generamos, guarda para siguientes veces (no rompas en caso de fallo)
                    if verification_url:
                        try:
                            invoice.sudo().write({"verifactu_qr_url": verification_url})
                        except Exception:
                            pass
            except Exception:
                # No abortar por aquí; caeremos a fallback legacy
                verification_url = ""

        # 5) Fallback definitivo: URL legacy por hash truncado
        if not verification_url:
            verification_url = "https://verifactu.aeat.es/verify/%s" % hash_preview

        # 6) Generar QR PNG en memoria
        qr = qrcode.QRCode(
            version=None,           # auto
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=1,
        )
        qr.add_data(verification_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        # 7) Nombre de archivo (saneado)
        safe_num = inv_number or "factura"
        safe_num = re.sub(r"[^\w\-_.]+", "_", safe_num)
        filename = "verifactu_%s.png" % safe_num

        # 8) Respuesta HTTP
        return request.make_response(
            buffer.read(),
            headers=[
                ("Content-Type", "image/png"),
                ("Content-Disposition", 'attachment; filename=%s' % filename),
            ],
        )
