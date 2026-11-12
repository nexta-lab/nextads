# -*- coding: utf-8 -*-
"""Rellena la pestaña Propuesta de los presupuestos abiertos (borrador y enviados) con el texto
automático, para que se pueda retocar sobre el propio presupuesto. Lo ya escrito se respeta."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

FIELDS = ('nds_punto_partida', 'nds_que_haremos', 'nds_incluye',
          'nds_punto_partida_auto', 'nds_que_haremos_auto', 'nds_incluye_auto')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env['sale.order'].with_context(active_test=False).search([('state', 'in', ('draft', 'sent'))])
    for name in FIELDS:
        env.add_to_compute(orders._fields[name], orders)
    env.flush_all()
    _logger.info("nds_sale_quote_report: pestaña Propuesta rellena en %s presupuestos abiertos", len(orders))
