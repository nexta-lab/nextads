# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class AccountJournal(models.Model):
    _inherit = "account.journal"

    # ───────────────────────────────────────────────
    # Activación selectiva del sistema VeriFactu
    # ───────────────────────────────────────────────
    verifactu_enabled = fields.Boolean(
        string="Enviar a VeriFactu",
        default=True,
        help=_(
            "Si está marcado, las facturas emitidas desde este diario "
            "se enviarán automáticamente al sistema VeriFactu.\n\n"
            "Si se desmarca, las facturas de este diario se excluirán "
            "del proceso de envío, incluso si VeriFactu está activo a nivel global."
        ),
    )
