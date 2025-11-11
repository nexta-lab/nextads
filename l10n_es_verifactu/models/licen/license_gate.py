# l10n_es_verifactu/services/license_gate.py
from odoo import api, models
from odoo.exceptions import UserError

class VerifactuLicenseGate(models.AbstractModel):

    _name = "verifactu.license.gate"
    _description = "VeriFactu License Gate"

    @api.model
    def _is_valid(self):
        """Devuelve True si la licencia está marcada como válida y existe token."""
        lic = self.env["verifactu.license"].sudo().get_singleton_record()
        return (lic.license_status or "").lower() == "valid" and bool(lic.license_token)

    @api.model
    def ensure_valid(self, hard=True):
        """
        Aplica la política de uso:
          - hard=True  -> lanza UserError si NO es válida (bloquea la acción inmediatamente).
          - hard=False -> devuelve bool; NO lanza (útil en crons o para avisos 'soft').

        Uso típico:
            self.env["verifactu.license.gate"].ensure_valid(hard=True)
        """
        ok = self._is_valid()
        if not ok and hard:
            raise UserError(
                "⛔ Licencia de VeriFactu inválida o no configurada.\n"
                "Introduce tu clave y pulsa «Obtener/Actualizar token» en Ajustes ▸ VeriFactu."
            )
        return ok
