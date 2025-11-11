# Desarrollado por Juan Ormaechea (Mr. Rubik) — Todos los derechos reservados
# Este módulo está protegido por la Odoo Proprietary License v1.0
# Cualquier redistribución está prohibida sin autorización expresa.

class VerifactuNotifier:
    def __init__(self, invoice):
        self.invoice = invoice

    def notify(self, title, message, type="info"):
        """
        Lanza una notificación toast en el frontend de Odoo.

        :param title: Título de la notificación
        :param message: Mensaje a mostrar
        :param type: Tipo ('success', 'warning', 'danger', 'info')
        :return: Diccionario estándar de retorno para controladores Odoo (útil en botones)
        """
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": type,
                "sticky": False,
            },
        }
