# -*- coding: utf-8 -*-
from odoo import api, fields, models

class AccountMoveRectificativaMixin(models.AbstractModel):
    _name = "account.move.rectificativa.mixin"
    _description = "Mixin para detectar facturas rectificativas"

    # Decorador compatible entre versiones
    if hasattr(api, "multi"):
        # Solo versiones antiguas (<13)
        @api.multi
        def is_rectificativa(self):
            return self._compute_is_rectificativa()
    else:
        # Odoo 13+
        @api.model
        def is_rectificativa(self):
            return self._compute_is_rectificativa()

    def _compute_is_rectificativa(self):
        """Devuelve True si la factura es rectificativa (nota de crédito o abono).
        Compatible desde Odoo 10 hasta 18."""
        # En versiones antiguas, ensure_one no existía en todos los mixins
        try:
            self.ensure_one()
        except Exception:
            if len(self) != 1:
                # Si se llama sobre varios registros, devuelve True si alguno lo es
                return any(rec._compute_is_rectificativa() for rec in self)

        # ----------------------------
        # Compatibilidad Odoo 10–12
        # ----------------------------
        if 'type' in self._fields:
            if self.type in ('out_refund', 'in_refund'):
                return True
            if 'refund_invoice_id' in self._fields and self.refund_invoice_id:
                return True

        # ----------------------------
        # Compatibilidad Odoo 13+
        # ----------------------------
        if 'move_type' in self._fields:
            if self.move_type in ('out_refund', 'in_refund'):
                return True
            if 'reversed_entry_id' in self._fields and self.reversed_entry_id:
                return True

        return False

    # Alias moderno (para uso en QWeb, controladores, etc.)
    def is_refund(self):
        return self.is_rectificativa()
