# -*- coding: utf-8 -*-
"""Página 2 de la portada: «Quiénes somos» justificado y nuevo texto de «Lo más estándar posible».

El registro del encabezado es noupdate: se sustituye aquí su PDF por el del módulo.
Los campos del formulario (asunto, referencia, fecha, cliente y comercial) no cambian.
"""
import base64
import logging

from odoo import SUPERUSER_ID, api
from odoo.tools import file_open

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    header = env.ref('nds_sale_quote_report.quotation_document_nds_header', raise_if_not_found=False)
    if not header:
        return
    with file_open('nds_sale_quote_report/static/quote_builder/nextads_encabezado.pdf', 'rb') as pdf:
        header.datas = base64.b64encode(pdf.read())
    env.flush_all()
    env['sale.pdf.form.field']._nds_assign_paths()
    _logger.info("nds_sale_quote_report: PDF de la portada actualizado")
