import logging

_logger = logging.getLogger(__name__)

class VerifactuLogger:
    def __init__(self, invoice):
        self.invoice = invoice
        self.env = invoice.env

    def log(self, message):
        """
        Registra un evento en verifactu.event.log y lo vincula a la factura.
        """
        self.invoice.ensure_one()

        # 1. Crear registro del evento
        event = self.env["verifactu.event.log"].create({
            "name": message,
            "company_id": self.invoice.company_id.id,
        })

        # 2. Añadir al campo many2many
        self.invoice.write({
            "verifactu_event_logs": [(4, event.id)],
        })

        # 3. Registrar también en el log del sistema
        _logger.info(message)

        # 4. Añadir comentario visible en chatter
        self.invoice.message_post(
            body=message,
            message_type="comment"
        )

        return event
