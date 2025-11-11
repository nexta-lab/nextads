# -*- coding: utf-8 -*-
from odoo import models, fields


class VerifactuStatusLog(models.Model):
    _name = "verifactu.status.log"
    _description = "Histórico de cambios de estado VeriFactu"
    _order = "date desc"

    # ────────────────────────────────
    # Campos base
    # ────────────────────────────────
    invoice_id = fields.Many2one(
        "account.move",
        string="Factura",
        required=True,
        ondelete="cascade",
    )

    def _default_selection_status(self):
        """Compatibilidad completa Odoo 10–18 + añade estados internos."""
        try:
            field = self.env["account.move"]._fields.get("verifactu_status")
            if field and getattr(field, "selection", None):
                base_selection = list(field.selection)
            else:
                base_selection = []
        except Exception:
            base_selection = []

        # Fallback estático si no había campo en account.move
        if not base_selection:
            base_selection = [
                ("draft", "Borrador"),
                ("sent", "Enviado"),
                ("accepted_with_errors", "Aceptado con errores"),
                ("error", "Error"),
            ]

        # 🔧 Añadimos estados internos para el cálculo de hash (no visibles para AEAT)
        extra = [
            ("hash_generated", "Sin enviar"),
        ]

        # Evitamos duplicados
        seen = set(x[0] for x in base_selection)
        for k, v in extra:
            if k not in seen:
                base_selection.append((k, v))

        return base_selection


    status = fields.Selection(
        selection=_default_selection_status,
        string="Estado",
        required=True,
    )

    date = fields.Datetime(
        string="Fecha",
        default=lambda self: fields.Datetime.now(),
        required=True,
    )

    user_id = fields.Many2one(
        "res.users",
        string="Usuario",
        default=lambda self: self.env.user,
    )

    notes = fields.Text(
        string="Notas (opcional)",
        help="Mensaje complementario sobre el cambio de estado.",
    )

    # ────────────────────────────────
    # Campos de trazabilidad VeriFactu
    # ────────────────────────────────
    hash_actual = fields.Char(
        string="Hash actual",
        size=64,
        help="Huella criptográfica calculada para este estado.",
    )

    hash_previo = fields.Char(
        string="Hash previo",
        size=64,
        help="Huella de la factura anterior en el encadenamiento VeriFactu.",
    )

    # ────────────────────────────────
    # Nuevos campos de auditoría AEAT
    # ────────────────────────────────
    xml_soap = fields.Binary(
        string="XML SOAP",
        help="Copia del XML SOAP enviado o generado para esta factura.",
    )

    aeat_code = fields.Integer(
        string="Código AEAT",
        help="Código de respuesta devuelto por la AEAT (por ejemplo, 4102, 2000, 3000…).",
    )
