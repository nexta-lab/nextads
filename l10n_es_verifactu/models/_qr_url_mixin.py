# -*- coding: utf-8 -*-
# verifactu/models/_qr_url_mixin.py
# Compatible Odoo 10 → 18

from odoo import models, fields, api, release

def _major_version():
    """
    Devuelve el mayor de versión como int de forma segura en Odoo 10→18.
    """
    try:
        ver = getattr(release, 'major_version', None) or getattr(release, 'version', '') or ''
        return int(str(ver).split('.')[0])
    except Exception:
        # Si no podemos detectar, asumimos moderno para no romper carga en >=13
        return 13

class VerifactuQRUrlMixin(models.AbstractModel):
    _name = "verifactu.qr.url.mixin"
    _description = "Mixin para almacenar URL de QR VeriFactu"

    verifactu_qr_url = fields.Char(string="VeriFactu QR URL", readonly=True, copy=False)

    # --------------- Helpers ---------------

    def _vf_resolve_config(self, company_id):
        return self.env["verifactu.endpoint.config"].sudo().search(
            [("company_id", "=", company_id)], limit=1
        )

    def _vf_is_noverifactu(self, inv):
        # Ajusta si tienes un flag específico para "modo no VeriFactu"
        return bool(getattr(inv, "verifactu_noverifactu", False))

    def _vf_generate_and_store_qr_url(self):
        """
        Genera la URL del QR y la guarda en verifactu_qr_url.
        No lanza excepciones (no interrumpe post/open).
        """
        # Import diferido para no romper carga si cambias rutas
        try:
            from ..verifactu.services.qr_content import VerifactuQRContentGenerator
        except Exception:
            VerifactuQRContentGenerator = None

        for inv in self:
            try:
                config = self._vf_resolve_config(inv.company_id.id)
                if not config or not VerifactuQRContentGenerator:
                    inv.sudo().write({"verifactu_qr_url": False})
                    continue

                factura_verificable = not self._vf_is_noverifactu(inv)
                gen = VerifactuQRContentGenerator(
                    inv, config, factura_verificable=factura_verificable
                )
                url = gen.generate_content()  # debe devolver str/Unicode
                inv.sudo().write({"verifactu_qr_url": (url or "").strip() or False})
            except Exception:
                inv.sudo().write({"verifactu_qr_url": False})
                continue

    # --------------- Acciones comunes ---------------

    def action_open_verifactu_qr_url(self):
        self.ensure_one()
        url = (self.verifactu_qr_url or "").strip()
        if not url:
            return False
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }

    def action_regenerate_verifactu_qr_url(self):
        self.ensure_one()
        try:
            self._vf_generate_and_store_qr_url()
        except Exception:
            pass
        return True


# =========================================================
# v13+ (account.move) — se ejecuta en posteo (action_post)
# =========================================================
if _major_version() >= 13:

    class AccountMove_VerifactuQR(models.Model):
        _inherit = ["account.move", "verifactu.qr.url.mixin"]
        _name = "account.move"

        def action_post(self):
            res = super(AccountMove_VerifactuQR, self).action_post()
            try:
                # Generar/actualizar QR URL tras posteo
                self._vf_generate_and_store_qr_url()
            except Exception:
                pass
            return res

# =========================================================
# v10–v12 (account.invoice) — se ejecuta al validar (open)
# =========================================================
else:

    class AccountInvoice_VerifactuQR(models.Model):
        _inherit = ["account.invoice", "verifactu.qr.url.mixin"]
        _name = "account.invoice"

        def action_invoice_open(self):
            res = super(AccountInvoice_VerifactuQR, self).action_invoice_open()
            try:
                # Generar/actualizar QR URL al validar
                self._vf_generate_and_store_qr_url()
            except Exception:
                pass
            return res
