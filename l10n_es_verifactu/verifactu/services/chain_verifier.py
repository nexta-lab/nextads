from odoo.exceptions import UserError
from odoo import _, fields
from ..services.logger import VerifactuLogger

class VerifactuChainVerifier:
    def __init__(self, invoice):
        self.invoice = invoice

    def verify(self):
        invoice = self.invoice
        invoice.ensure_one()
        logger = VerifactuLogger(invoice)

        try:
            if not invoice.verifactu_previous_hash:
                logger.log(f"✅ Encadenamiento verificado para la primera factura {invoice.name} (sin hash anterior)")
                return True

            # Buscar factura anterior válida
            previous_invoice = invoice.env["account.move"].search(
                [
                    ("verifactu_hash", "!=", False),
                    ("move_type", "in", ("out_invoice", "out_refund")),
                    ("id", "!=", invoice.id),
                    "|", "|",
                    ("verifactu_processed", "=", True),
                    ("verifactu_sent", "=", True),
                    ("verifactu_sent_with_errors", "=", True),
                ],
                order="invoice_date desc, id desc"
            ).filtered(lambda inv: inv.invoice_date and inv.invoice_date <= invoice.invoice_date)

            if previous_invoice and previous_invoice[0].verifactu_hash == invoice.verifactu_previous_hash:
                logger.log(
                    f"✅ Encadenamiento verificado para la factura {invoice.name}.\n"
                    f"Hash anterior esperado: {invoice.verifactu_previous_hash}\n"
                    f"Hash real de la factura previa ({previous_invoice[0].name}): {previous_invoice[0].verifactu_hash}"
                )
                return True
            else:
                logger.log(
                    f"🛑 Encadenamiento NO verificado para la factura {invoice.name}.\n"
                    f"Hash anterior esperado: {invoice.verifactu_previous_hash or '—'}\n"
                    f"Hash real de la factura previa: {previous_invoice[0].verifactu_hash if previous_invoice else 'Factura previa no encontrada'}"
                )
                return False

        except Exception as e:
            logger.log(f"🛑 Error al verificar el encadenamiento: {str(e)}")
            raise UserError(_(f"Error al verificar el encadenamiento: {str(e)}"))