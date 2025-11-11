# -*- coding: utf-8 -*-
import requests
from packaging import version  # ➜ añade "packaging" en external_dependencies del manifest
from odoo import models, fields, api, _
from datetime import timedelta

# Import tolerante del logger (ruta relativa estándar del módulo)
try:
    from ..verifactu.services.logger import VerifactuLogger
except Exception:
    VerifactuLogger = None


class VerifactuUpdateChecker(models.AbstractModel):
    _name = "verifactu.update.checker"
    _description = "Verifactu Update Checker"

    # ───────────────────────────────────────────────
    # Control de frecuencia de chequeo
    # ───────────────────────────────────────────────
    def _should_check(self, lic):
        """Evita pedir el feed demasiado a menudo (por defecto: cada 72 h)."""
        if not lic or not lic.update_feed_url:
            return False
        if not lic.last_check:
            return True
        return fields.Datetime.now() - lic.last_check >= timedelta(hours=72)

    # ───────────────────────────────────────────────
    # Aviso visual no bloqueante (según versión Odoo)
    # ───────────────────────────────────────────────
    def _notify_user(self, message, title=None):
        """
        Muestra un aviso visual persistente si la versión de Odoo lo soporta.
        No bloquea la interfaz ni interrumpe procesos automáticos.
        """
        user = self.env.user
        try:
            notify = getattr(user, "notify_info", None)
            if callable(notify):
                try:
                    # Odoo 16–18: sticky mantiene el toast visible hasta cerrar
                    notify(
                        message=message,
                        title=title or _("Actualización disponible"),
                        sticky=True,
                    )
                except TypeError:
                    # Odoo 14–15: sin sticky (toast temporal)
                    notify(
                        message=message,
                        title=title or _("Actualización disponible"),
                    )
                return
        except Exception:
            pass

        # Fallback: si no hay notify_* (Odoo ≤13), deja el mensaje en el chatter
        try:
            user.message_post(body=message, subtype_xmlid="mail.mt_note")
        except Exception:
            pass

    # ───────────────────────────────────────────────
    # Chequeo simple (manual o programado)
    # ───────────────────────────────────────────────
    @api.model
    def check_for_updates(self):
        lic = self.env["verifactu.license"].sudo().get_singleton_record()
        feed_url = (lic.update_feed_url or "").strip()
        if not feed_url:
            return False

        try:
            resp = requests.get(feed_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            latest = (data.get("latest_version") or "").strip()
            changelog = data.get("changelog", [])
            release_date = data.get("release_date")
            download_url = data.get("download_url")

            # versión actual instalada
            module = self.env["ir.module.module"].sudo().search(
                [("name", "=", "l10n_es_verifactu")], limit=1
            )
            current = (getattr(module, "installed_version", "") or "").strip()
            if not latest or not current:
                return False

            if version.parse(latest) > version.parse(current):
                if lic.last_notified_version != latest:
                    # Construcción del mensaje
                    changes = ""
                    if changelog:
                        if "basestring" in dir(__builtins__):
                            lines = [
                                u"- %s"
                                % (
                                    unicode(x)
                                    if not isinstance(x, basestring)
                                    else x
                                )
                                for x in changelog[:10]
                            ]
                        else:
                            lines = [u"- %s" % str(x) for x in changelog[:10]]
                        changes = u"\n" + u"\n".join(lines)

                    extra = ""
                    if release_date:
                        extra += _("\nFecha de publicación: %s") % release_date
                    if download_url:
                        extra += _("\nDescarga: %s") % download_url

                    msg = _("🔔 Nueva versión disponible: %s (actual: %s)%s%s") % (
                        latest,
                        current,
                        changes,
                        extra,
                    )

                    try:
                        lic.message_post(body=msg, subtype_xmlid="mail.mt_note")
                    except Exception:
                        pass

                    lic.write(
                        {
                            "last_notified_version": latest,
                            "last_check": fields.Datetime.now(),
                            "last_error": False,
                        }
                    )

                    # Aviso visual persistente
                    self._notify_user(msg, title=_("Actualización VeriFactu"))

            else:
                lic.write(
                    {
                        "last_check": fields.Datetime.now(),
                        "last_error": False,
                    }
                )
            return True

        except Exception as e:
            lic.write(
                {
                    "last_check": fields.Datetime.now(),
                    "last_error": str(e),
                }
            )
            try:
                lic.message_post(
                    body=_("⚠️ Error comprobando actualizaciones: %s") % str(e),
                    subtype_xmlid="mail.mt_note",
                )
            except Exception:
                pass
            return False

    # ───────────────────────────────────────────────
    # Chequeo con notificación contextual (factura)
    # ───────────────────────────────────────────────
    @api.model
    def check_and_notify_if_needed(self, invoice=None):
        """
        Consulta el feed (si toca) y notifica si hay versión nueva.
        Si se pasa una factura, registra el aviso en su chatter;
        si no, lo hace en el registro de licencia y muestra un toast.
        """
        lic = self.env["verifactu.license"].sudo().get_singleton_record()
        try:
            if not self._should_check(lic):
                return False

            module = self.env["ir.module.module"].sudo().search(
                [("name", "=", "l10n_es_verifactu")], limit=1
            )
            current = (getattr(module, "installed_version", "") or "").strip()
            if not current:
                lic.write({"last_check": fields.Datetime.now()})
                return False

            # petición al feed
            resp = requests.get(lic.update_feed_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            latest = (data.get("latest_version") or "").strip()
            changelog = data.get("changelog", [])
            release_date = (data.get("release_date") or "").strip()
            download_url = (data.get("download_url") or "").strip()

            if not latest:
                lic.write({"last_check": fields.Datetime.now()})
                return False

            if version.parse(latest) > version.parse(current) and lic.last_notified_version != latest:
                # Construir mensaje corto
                lines = []
                if changelog:
                    lines.append(_("Cambios:"))
                    if "basestring" in dir(__builtins__):
                        lines += [
                            u"- %s"
                            % (
                                unicode(i)
                                if not isinstance(i, basestring)
                                else i
                            )
                            for i in changelog[:5]
                        ]
                    else:
                        lines += [u"- %s" % str(i) for i in changelog[:5]]
                if release_date:
                    lines.append(_("Fecha de publicación: %s") % release_date)
                if download_url:
                    lines.append(_("Descarga: %s") % download_url)

                body = (
                    _("🔔 Nueva versión de VeriFactu disponible: %s (instalada: %s)")
                    % (latest, current)
                    + (u"\n" + u"\n".join(lines) if lines else u"")
                    + u"\n\n"
                    + _("Se recomienda actualizar para cumplir correctamente con la normativa.")
                )

                # Registrar en chatter o logger
                if invoice:
                    try:
                        if VerifactuLogger:
                            VerifactuLogger(invoice).log(body)
                        else:
                            invoice.message_post(body=body)
                    except Exception:
                        pass
                else:
                    try:
                        lic.message_post(body=body, subtype_xmlid="mail.mt_note")
                    except Exception:
                        pass

                # Actualiza estado
                lic.write(
                    {
                        "last_notified_version": latest,
                        "last_check": fields.Datetime.now(),
                        "last_error": False,
                    }
                )

                # Aviso visual persistente
                self._notify_user(body, title=_("Actualización VeriFactu"))
                return True

            lic.write(
                {
                    "last_check": fields.Datetime.now(),
                    "last_error": False,
                }
            )
            return False

        except Exception as e:
            lic.write(
                {
                    "last_check": fields.Datetime.now(),
                    "last_error": str(e),
                }
            )
            return False
