from odoo import models
from ..services.anomaly_detector import VerifactuAnomalyDetector


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    def detect_anomalies_cron(self):
        """
        Llamado automáticamente por el CRON: detecta anomalías en las facturas VeriFactu.
        """
        VerifactuAnomalyDetector(self.env).detect()

    def action_enable_anomaly_cron(self):
        """
        Botón para activar el CRON de detección de anomalías.
        """
        VerifactuAnomalyDetector(self.env).enable_cron()

    def action_disable_anomaly_cron(self):
        """
        Botón para desactivar el CRON de detección de anomalías.
        """
        VerifactuAnomalyDetector(self.env).disable_cron()

    def toggle_anomaly_cron(self):
        for record in self:
            detector = VerifactuAnomalyDetector(self.env)
            if record.anomaly_cron_enabled:
                detector.disable_cron()
                record.anomaly_cron_enabled = False
            else:
                detector.enable_cron()
                record.anomaly_cron_enabled = True
