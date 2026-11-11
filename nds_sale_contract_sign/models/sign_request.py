# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SignRequest(models.Model):
    _inherit = 'sign.request'

    def write(self, vals):
        to_watch = self.filtered(lambda r: r.state != 'signed') if vals.get('state') == 'signed' else self.browse()
        res = super().write(vals)
        if to_watch:
            to_watch._nds_process_signed_orders()
        return res

    def _nds_process_signed_orders(self):
        orders = self.env['sale.order'].sudo().search([('nds_sign_request_id', 'in', self.ids)])
        for order in orders:
            request = order.nds_sign_request_id
            try:
                with self.env.cr.savepoint():
                    order._nds_after_contract_signed(request)
            except Exception:  # noqa: BLE001 - la firma ya está hecha; no se bloquea por esto
                _logger.exception("nds_sale_contract_sign: error al procesar la firma de %s", order.name)
                order.message_post(
                    body="La documentación está firmada, pero no se ha podido adjuntar o procesar "
                         "automáticamente (SEPA). Revisad la solicitud de firma.",
                    subtype_xmlid='mail.mt_note',
                )
