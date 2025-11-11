from odoo import api, SUPERUSER_ID
from odoo.tools.safe_eval import safe_eval
from odoo.exceptions import UserError
from odoo.modules.module import get_module_resource

from ..services.logger import VerifactuLogger


class VerifactuAnomalyDetector:
    CRON_XML_ID = "l10n_es_verifactu.ir_cron_detect_anomalies"

    def __init__(self, env):
        self.env = env

    def detect(self):
        """
        Detecta anomalías en facturas enviadas y procesadas.
        """
        anomalies = []
        invoices = self.env["account.move"].search(
            [
                ("verifactu_sent", "=", True),
                ("verifactu_sent_with_errors", "=", True),
                ("verifactu_processed", "=", True),
            ]
        )

        for invoice in invoices:
            if not invoice.verify_integrity():
                VerifactuLogger(invoice).log(
                    f"🛑 Anomalía detectada al verificar la integridad de la factura {invoice.name}"
                )
                anomalies.append(invoice)

        # Evento global del sistema
        msg = (
            f"🛑 Detectadas anomalías en {len(anomalies)} facturas."
            if anomalies
            else "✅ No se detectaron anomalías en los registros de facturación."
        )

        self._log_system_event(msg)
        return anomalies

    def _log_system_event(self, message):
        """
        Registrar un mensaje general del sistema como log del módulo.
        """
        self.env["ir.logging"].create(
            {
                "name": "Verifactu",
                "type": "server",
                "dbname": self.env.cr.dbname,
                "level": "INFO",
                "message": message,
                "path": "verifactu",
                "func": "detect_anomalies",
                "line": 0,
            }
        )

    def enable_cron(self):
        """
        Activa el CRON de detección de anomalías si existe.
        """
        cron = self._get_cron()
        if cron:
            cron.write({"active": True})
        else:
            raise UserError("⚠️ No se encontró el CRON para detectar anomalías.")

    def disable_cron(self):
        """
        Desactiva el CRON de detección de anomalías.
        """
        cron = self._get_cron()
        if cron:
            cron.write({"active": False})
        else:
            raise UserError("⚠️ No se encontró el CRON para detectar anomalías.")

    def is_cron_enabled(self):
        cron = self._get_cron()
        return cron.active if cron else False

    def _get_cron(self):
        """
        Devuelve el objeto ir.cron correspondiente al XML-ID configurado.
        """
        try:
            return self.env.ref(self.CRON_XML_ID)
        except Exception:
            return None
