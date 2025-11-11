# models/verifactu_license.py
# Compatible Odoo 11 → 18

from odoo import models, fields, api

DEFAULT_FEED = "https://verifactu-7fc70-default-rtdb.europe-west1.firebasedatabase.app/update/latest.json"
DEFAULT_SERVER = "https://us-central1-verifactu-7fc70.cloudfunctions.net/issueLicense"


class VerifactuLicense(models.Model):
    _name = "verifactu.license"
    _description = "Licencia VeriFactu"
    _rec_name = "license_key"

    # --- Datos de licencia ---
    license_key = fields.Char(string="Clave de licencia")
    license_token = fields.Text(string="Token de licencia (JWT)", copy=False)
    license_status = fields.Selection(
        [
            ("valid", "Válida"),
            ("grace", "Gracia"),
            ("invalid", "Inválida"),
            ("expired", "Expirada"),
        ],
        default="invalid",
        readonly=True,
    )

    # --- Trazas / control ---
    last_check = fields.Datetime(readonly=True)
    next_check = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    # --- Límites / expiración ---
    max_companies = fields.Integer(readonly=True)
    expiry = fields.Datetime(readonly=True)

    # --- Actualizaciones y servidor de licencias ---
    update_feed_url = fields.Char(
        string="URL del feed de actualizaciones",
        default=DEFAULT_FEED,
    )
    verifactu_license_server_url = fields.Char(
        string="URL del servidor de licencias",
        help="Servicio HTTPS que emite y firma los tokens de licencia (JWT).",
        default=DEFAULT_SERVER,
    )
    last_notified_version = fields.Char(readonly=True)

    updates_cron_enabled = fields.Boolean(
        string="Activar comprobación periódica de actualizaciones",
        default=True,
        help="Si está desactivado, el cron no notificará actualizaciones.",
    )

    # Solo para mostrar el token truncado (no almacena el valor)
    license_token_display = fields.Char(
        string="Token (JWT)",
        compute="_compute_license_token_display",
        readonly=True,
    )

    @api.model
    def get_singleton_record(self):
        """Devuelve/crea el único registro de configuración de licencia (modo singleton)."""
        rec = self.sudo().search([], limit=1)
        if not rec:
            rec = self.sudo().create({})
        # Defaults para registros antiguos
        vals = {}
        if not rec.update_feed_url:
            vals["update_feed_url"] = DEFAULT_FEED
        if not rec.verifactu_license_server_url:
            vals["verifactu_license_server_url"] = DEFAULT_SERVER
        if vals:
            rec.sudo().write(vals)
        return rec

    def _compute_license_token_display(self):
        """Trunca el JWT para mostrar de forma segura (compatible 11→18)."""
        for rec in self:
            tok = (rec.license_token or "").strip()
            if tok and len(tok) > 24:
                # Evitar f-strings por compatibilidad con Python 3.5 (Odoo 11)
                rec.license_token_display = tok[:12] + "..." + tok[-12:]
            elif tok:
                rec.license_token_display = tok  # por si es muy corto
            else:
                rec.license_token_display = u"— generado por servidor —"
