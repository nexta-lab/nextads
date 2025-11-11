# models/verifactu_requirement_wizard.py

from odoo import models, fields, api, _
from odoo.exceptions import UserError

class VerifactuRequirementWizard(models.TransientModel):
    _name = "verifactu.requirement.wizard"
    _description = "Requerimiento para modo No VeriFactu"

    ref_requerimiento = fields.Char(string="Referencia de Requerimiento", required=True)

    def confirm(self):
        """Aplica el código a las facturas activas y recarga la vista."""
        # Soporta una o varias facturas seleccionadas
        active_ids = self.env.context.get("active_ids") or []
        if not active_ids:
            raise UserError(_("No se encontró ninguna factura activa."))

        moves = self.env["account.move"].browse(active_ids).exists()
        if not self.ref_requerimiento or not self.ref_requerimiento.strip():
            raise UserError(_("Indica el código del requerimiento."))

        ref = self.ref_requerimiento.strip()

        # Escribe el requerimiento en cada factura seleccionada
        # y marca como no generado para forzar nueva generación en el flujo No VeriFactu
        for move in moves:
            move.write({
                "verifactu_requerimiento": ref,
                "verifactu_generated": False,
            })
            # Nota en el chatter
            move.message_post(
                body=_("⚠️ Se ha establecido el código de requerimiento para envío en modo No VeriFactu: <b>%s</b>.") % ref
            )

        # Si era una sola factura, recárgala; si eran varias, cierra el wizard
        if len(moves) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": "account.move",
                "view_mode": "form",
                "res_id": moves.id,
                "target": "current",
            }
        return {"type": "ir.actions.act_window_close"}
