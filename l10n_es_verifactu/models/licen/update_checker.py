# models/verifactu_update_checker.py
# Compatible con Odoo 11 → 18
# Requiere external_dependencies en el manifest:
# "external_dependencies": { "python": ["requests", "packaging"] }

import requests
from packaging import version as _v
from datetime import timedelta
from odoo import models, fields, api, _


class VerifactuUpdateChecker(models.AbstractModel):
    _name = "verifactu.update.checker"
    _description = "Verifactu Update Checker"

    # -------------------- utilidades --------------------

    def _safe_message_post(self, rec, body):
        """Publica en chatter si el modelo lo soporta; ignora silenciosamente en caso contrario."""
        try:
            if hasattr(rec, "message_post"):
                rec.message_post(body=body, subtype_xmlid="mail.mt_note")
        except Exception:
            # No interrumpir flujo por problemas de mail.thread
            pass

    def _parse_feed(self, data):
        """
        Admite ambos esquemas:
        A) { "latest_version": "1.0.9", "changelog": [...], "release_date": "...", "download_url": "..." }
        B) { "changelog": { "latest_version": "1.0.9", "release_date": "...", "download_url": "..." } }
        Devuelve: (latest, changes_list, release_date, download_url)
        """
        changelog = data.get("changelog")
        # latest puede venir a nivel raíz o dentro de changelog (dict)
        latest = (data.get("latest_version")
                  or (changelog.get("latest_version") if isinstance(changelog, dict) else None)
                  or "")
        latest = latest.strip()

        # lista de cambios solo si es list
        changes_list = changelog if isinstance(changelog, list) else []

        # release y url pueden venir en raíz o dentro de changelog (dict)
        release_date = (data.get("release_date")
                        or (changelog.get("release_date") if isinstance(changelog, dict) else "")
                        or "")
        release_date = release_date.strip()

        download_url = (data.get("download_url")
                        or (changelog.get("download_url") if isinstance(changelog, dict) else "")
                        or "")
        download_url = download_url.strip()

        return latest, changes_list, release_date, download_url

    def _module_current_version(self, technical_name="l10n_es_verifactu"):
        mod = self.env["ir.module.module"].sudo().search([("name", "=", technical_name)], limit=1)
        curr = (mod.installed_version or mod.latest_version or "").strip()
        return curr

    def _should_check(self, lic, hours=72):
        """Evita consultar el feed más de una vez cada 'hours' horas (seguro para Odoo 11)."""
        if not lic or not lic.update_feed_url:
            return False
        if not lic.last_check:
            return True
        last = fields.Datetime.from_string(lic.last_check)
        now = fields.Datetime.from_string(fields.Datetime.now())
        return (now - last) >= timedelta(hours=hours)

    # -------------------- API CRON --------------------

    @api.model
    def check_for_updates(self):
        lic = self.env["verifactu.license"].sudo().get_singleton_record()
        feed_url = (lic.update_feed_url or "").strip()
        if not feed_url:
            return False

        try:
            resp = requests.get(feed_url, timeout=10)
            resp.raise_for_status()
            latest, changes, release_date, download_url = self._parse_feed(resp.json())

            current = self._module_current_version("l10n_es_verifactu")
            if not latest or not current:
                lic.sudo().write({"last_check": fields.Datetime.now()})
                return False

            if _v.parse(latest) > _v.parse(current):
                if lic.last_notified_version != latest:
                    # construir mensaje (sin f-strings, compatible 11)
                    lines = []
                    if changes:
                        lines.append(_("Cambios:"))
                        for item in changes[:5]:
                            lines.append("- %s" % (item,))
                    if release_date:
                        lines.append(_("Fecha de publicación: %s") % release_date)
                    if download_url:
                        lines.append(_("Descarga: %s") % download_url)

                    body = _("🔔 Nueva versión de VeriFactu disponible: %(latest)s (instalada: %(current)s)") % {
                        "latest": latest, "current": current
                    }
                    if lines:
                        body += "\n" + "\n".join(lines)

                    self._safe_message_post(lic, body)
                    lic.sudo().write({
                        "last_notified_version": latest,
                        "last_check": fields.Datetime.now(),
                        "last_error": False,
                    })
                    return True

            # actualizado o superior (posible fork)
            lic.sudo().write({"last_check": fields.Datetime.now(), "last_error": False})
            return False

        except Exception as e:
            lic.sudo().write({"last_check": fields.Datetime.now(), "last_error": str(e)})
            # no interrumpir el cron
            return False

    # -------------------- API ligera (p. ej. desde account.move) --------------------

    @api.model
    def check_and_notify_if_needed(self, invoice=None):
        """
        Consulta el feed solo si toca (cada ~72h). No lanza excepciones.
        Si quieres notificar en la factura, hazlo fuera con tu logger propio.
        """
        lic = self.env["verifactu.license"].sudo().get_singleton_record()
        if not self._should_check(lic):
            return False
        return self.check_for_updates()
