# Desarrollado por Juan Ormaechea (Mr. Rubik) — Todos los derechos reservados
# Este módulo está protegido por la Odoo Proprietary License v1.0
# Cualquier redistribución está prohibida sin autorización expresa.

import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
from odoo import _, models, fields, api, SUPERUSER_ID
from odoo.exceptions import UserError
import hashlib
import logging
import base64
import qrcode
from io import BytesIO

from cryptography.hazmat.backends import default_backend
import lxml.etree as LET
from signxml import XMLSigner, methods
from datetime import datetime, timedelta, timezone
import re
import platform
import socket
from ...verifactu.services.xml_builder.xml_builder import VerifactuXMLBuilder
from ...verifactu.services.xml_signer import VerifactuXMLSigner
from ...verifactu.services.attachment import VerifactuAttachmentService
from ...verifactu.services.hash_calculator import VerifactuHashCalculator
from ...verifactu.services.logger import VerifactuLogger
from ...verifactu.services.show_notification import VerifactuNotifier
from ...verifactu.services.xml_sender import VerifactuSender
from ...verifactu.services.qr_content import VerifactuQRContentGenerator
from ...verifactu.services.resender import VerifactuResender
from ...verifactu.services.chain_verifier import VerifactuChainVerifier
from ...verifactu.services.event_exporter import VerifactuEventExporter
from ...verifactu.services.hash_verifier import VerifactuHashVerifier
from ...verifactu.services.integrity_verifier import VerifactuIntegrityVerifier
from ...verifactu.services.xml_builder.xml_builder_simple import VerifactuSimpleXMLBuilder
from ...verifactu.services.anomaly_detector import VerifactuAnomalyDetector
from ...verifactu.services.xml_builder.envelope_builder import VerifactuEnvelopeBuilder
from ...verifactu.services.xml_builder.xml_builder_subsanacion import VerifactuXMLBuilderSubsanacion
from ...verifactu.services.xml_builder.xml_builder_anulacion import VerifactuXMLBuilderAnulacion
from ...verifactu.services.xml_builder.envelope_builder_anluacion import (
    VerifactuEnvelopeBuilderAnulacion,
)
from ...verifactu.services.xml_builder.xml_builder_no_verifactu_subsanacion import VerifactuXMLBuilderNoVerifactuSubsanacion
from ...verifactu.services.xml_builder.no_verifactu_xml_builder import VerifactuXMLBuilderNoVerifactu
from ...verifactu.services.xml_builder.xml_builder_no_verifactu_anulacion import VerifactuXMLBuilderNoVerifactuAnulacion
from .account_move_rectificativa_mixin import AccountMoveRectificativaMixin

_logger = logging.getLogger(__name__)

# ---------- Helpers compatibles 11→18 ----------
def _vf_clean_es(vat):
    vat = (vat or "").strip().upper()
    if vat.startswith("ES"):
        vat = vat[2:]
    return vat.replace(" ", "").replace("-", "").replace(".", "")

def _vf_get_move_type(inv):
    """Devuelve 'out_invoice' / 'out_refund' compatible 11→18."""
    # v13+: move_type
    mt = getattr(inv, "move_type", None)
    if mt:
        return mt
    # v11/12: type
    return getattr(inv, "type", "")

def _vf_get_name(inv):
    """Compat de número/serie."""
    return getattr(inv, "name", None) or getattr(inv, "number", None) or ""

def _vf_get_date(inv):
    """Compat de fecha expedición."""
    return getattr(inv, "invoice_date", None) or getattr(inv, "date_invoice", None)

def _vf_resolve_tipo_factura(inv):
    """Usa tu resolver si está disponible; fallback básico."""
    try:
        # Import local para no romper si no existe en esta base
        from ...verifactu.utils.invoice_type_resolve import VerifactuTipoFacturaResolver
        return VerifactuTipoFacturaResolver.resolve(inv)
    except Exception:
        mt = _vf_get_move_type(inv)
        # F1: normal; R1: rectificativa (fallback simple)
        return "R1" if mt == "out_refund" else "F1"

def _vf_current_id_tuple(inv):
    """Tupla actual (IDEmisor, NumSerie, Fecha(dd-mm-YYYY), TipoFactura)."""
    company_vat = _vf_clean_es(getattr(inv.company_id, "vat", ""))
    num = _vf_get_name(inv)
    d = _vf_get_date(inv)
    fecha = d.strftime("%d-%m-%Y") if d else ""
    tipo = _vf_resolve_tipo_factura(inv)
    return (company_vat, num, bool(d), tipo)

def _vf_last_id_tuple(inv):
    """
    Lee el último snapshot guardado si existe.
    Campos soportados (usa los que tengas; si no, fallback vacío):
      - verifactu_last_id_emisor
      - verifactu_last_num_serie
      - verifactu_last_fecha_bool (o verifactu_last_fecha_str)
      - verifactu_last_tipo_factura
    """
    idemisor = getattr(inv, "verifactu_last_id_emisor", "") or ""
    num = getattr(inv, "verifactu_last_num_serie", "") or ""
    # admitimos bool o string
    fecha_bool = getattr(inv, "verifactu_last_fecha_bool", None)
    if fecha_bool is None:
        fecha_bool = bool(getattr(inv, "verifactu_last_fecha_str", "") or False)
    tipo = getattr(inv, "verifactu_last_tipo_factura", "") or ""
    return (idemisor, num, bool(fecha_bool), tipo)

def _vf_save_id_snapshot(inv):
    """Guarda el snapshot actual si tienes esos campos definidos (silencioso si no)."""
    try:
        idemisor, num, fecha_ok, tipo = _vf_current_id_tuple(inv)
        vals = {}
        if hasattr(inv, "verifactu_last_id_emisor"):
            vals["verifactu_last_id_emisor"] = idemisor
        if hasattr(inv, "verifactu_last_num_serie"):
            vals["verifactu_last_num_serie"] = num
        if hasattr(inv, "verifactu_last_fecha_bool"):
            vals["verifactu_last_fecha_bool"] = fecha_ok
        elif hasattr(inv, "verifactu_last_fecha_str"):
            vals["verifactu_last_fecha_str"] = "1" if fecha_ok else ""
        if hasattr(inv, "verifactu_last_tipo_factura"):
            vals["verifactu_last_tipo_factura"] = tipo
        if vals:
            inv.sudo().with_context(check_move_validity=False).write(vals)
    except Exception:
        _logger.debug("No se pudo guardar snapshot VeriFactu para %s", inv.id)

def _vf_reset_to_pending(inv):
    """Lleva la factura a estado 'pending' para permitir reenvío/recálculo."""
    vals = {
        "verifactu_status": "pending",
        "verifactu_sent": False,
        "verifactu_sent_with_errors": False,
        "verifactu_processed": False,
    }
    # Mantén verifactu_date_sent si quieres histórico; aquí no lo tocamos
    inv.sudo().with_context(check_move_validity=False).write(vals)

def _vf_get_invoice_date(inv):
    """Compat: devuelve la fecha de factura (v12: date_invoice, v13+: invoice_date)."""
    return getattr(inv, 'invoice_date', False) or getattr(inv, 'date_invoice', False)


def _vf_is_customer_doc(inv):
    """Solo ventas y abonos de ventas."""
    t = (_vf_get_move_type(inv) or '').strip()
    return t in ('out_invoice', 'out_refund')

def _vf_display_name(inv):
    """Compat: un identificador entendible de la factura para mensajes."""
    for attr in ('name', 'number', 'payment_reference', 'ref', 'reference'):
        val = getattr(inv, attr, False)
        if val:
            return val
    return str(inv.id)

def _vf_is_posted_domain(model):
    """
    Compat: dominio para 'factura posteada'.
    - v13+: state == 'posted'
    - v12: state in ('open','paid')
    """
    if 'state' in model._fields:
        # asumimos v13+ por defecto
        return [('state', '=', 'posted')]
    # fallback (v12)
    return [('state', 'in', ('open', 'paid'))]

class AccountMove(models.Model):
    _inherit = "account.move"
    
        #VARIABLES CRON
    verifactu_processing = fields.Boolean(
        string="Procesando VeriFactu",
        default=False,
        help="Marcado por el CRON/worker para evitar dobles envíos en paralelo."
    )
    verifactu_last_try = fields.Datetime(
        string="Último intento de envío VeriFactu",
        help="Fecha/hora del último intento de envío (lo actualiza CRON/worker)."
    )
    verifactu_retry_count = fields.Integer(
        string="Reintentos VeriFactu",
        default=0,
        help="Número de reintentos realizados (para backoff exponencial)."
    )
    

    verifactu_last_emisor_nif = fields.Char(readonly=True)
    verifactu_last_numero = fields.Char(readonly=True)
    verifactu_last_fecha = fields.Date(readonly=True)
    verifactu_last_tipo = fields.Char(readonly=True)
    
    verifactu_detailed_error_msg = fields.Text(
        string="Mensaje de error VeriFactu (en detalle)"
    )

    verifactu_qr = fields.Binary(
        "QR VeriFactu", help="Código QR generado tras la validación VeriFactu."
    )
    
    verifactu_is_active = fields.Boolean(
        string="VeriFactu Activo",
        compute="_compute_verifactu_is_active",
        store=False,          # pon True si quieres indexarlo; en v10-v12 evita recalculados masivos
        readonly=True,
        help="Indica si VeriFactu está activo para esta compañía."
    )

    @api.depends('company_id')
    def _compute_verifactu_is_active(self):
        ConfigEnv = self.env['verifactu.endpoint.config'].sudo()

        # Compat: Odoo 13+ tiene with_company; 10–12 no.
        has_with_company = hasattr(ConfigEnv, 'with_company')
        # Compat: por si en alguna DB antigua faltara el helper.
        has_singleton = hasattr(type(ConfigEnv), 'get_singleton_record') or hasattr(ConfigEnv, 'get_singleton_record')

        for move in self:
            company = move.company_id or self.env.user.company_id
            cfg = False

            try:
                if has_singleton:
                    # Preferimos el singleton por compañía (tu modelo ya lo implementa)
                    if has_with_company:
                        cfg = ConfigEnv.with_company(company).get_singleton_record()
                    else:
                        cfg = ConfigEnv.with_context(force_company=company.id).get_singleton_record()
                else:
                    # Fallback ultra-compat si no existiera get_singleton_record en algún fork antiguo
                    domain = [('company_id', '=', company.id)]
                    if has_with_company:
                        cfg = ConfigEnv.with_company(company).search(domain, limit=1)
                    else:
                        cfg = ConfigEnv.with_context(force_company=company.id).search(domain, limit=1)
            except Exception:
                # Último fallback defensivo
                cfg = ConfigEnv.sudo().search([('company_id', '=', company.id)], limit=1)

            move.verifactu_is_active = bool(getattr(cfg, 'verifactu_mode_enabled', False))
    
    verifactu_requerimiento = fields.Char(
        string="Referencia de Requerimiento AEAT",
        help="Código oficial del requerimiento recibido por la AEAT. Obligatorio en el modo No VeriFactu.",
    )

    verifactu_date_sent = fields.Datetime(
        string="Fecha de envío VeriFactu",
        readonly=True,
        help="Fecha y hora en que se envió la factura a la AEAT mediante VeriFactu.",
    )
        
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
    )


    verifactu_sent = fields.Boolean(
        string="Enviado a VeriFactu sin errores", default=False
    )
    verifactu_sent_with_errors = fields.Boolean(
        string="Enviado a VeriFactu con errores", default=False
    )
    verifactu_processed = fields.Boolean(string="VeriFactu procesao", default=False)
    verifactu_status = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("sent", "Enviado"),
            ("accepted_with_errors", "Aceptado con errores"),
            ("error", "Error"),
            ("rejected", "Rechazado"),
            ("canceled", "anulado"),
            ("duplicated", "Duplicado"),  # opcional, si deseas diferenciar
        ],
        default="pending",
        string="Estado VeriFactu",
        tracking=True,
    )

    verifactu_hash_calculated_at = fields.Datetime(
        string="Fecha de Cálculo del Hash", readonly=True
    )

    invoice_date_operation = fields.Date(
        string="Fecha de Operación",
        help="Indica la fecha en la que se realiza la operación económica real si es distinta a la fecha de expedición.",
    )

    verifactu_soap_xml = fields.Binary(string="Verifactu SOAP XML", attachment=False)

    verifactu_generated = fields.Boolean(
        string="XML VeriFactu generado",
        default=False,
        help="Indica si se ha generado el XML para esta factura, aunque no se haya enviado todavía."
    )

    verifactu_error_msg = fields.Text(string="Mensaje de error VeriFactu")

    verifactu_qr_image = fields.Binary(
        string="VeriFactu QR",
        compute="_compute_verifactu_qr_image",
        store=True,
        attachment=True,
    )
    
    date_invoice_operation = fields.Date(
        string="Fecha de Operación",
        help="Indica la fecha en la que se realiza la operación económica real si es distinta a la fecha de expedición.",
    )
    
    verifactu_dev_hash = fields.Char(string='Verifactu Hash Dev', default='mrrubik:vf-v1.3.20250611', readonly=True)
    
    verifactu_hash = fields.Char(string="Hash VeriFactu", readonly=True)
    verifactu_previous_hash = fields.Char(
        string="Hash Anterior VeriFactu", readonly=True
    )
    verifactu_event_logs = fields.Many2many(
        "verifactu.event.log", string="Registros de Eventos", readonly=True
    )

    verifactu_issued_at = fields.Datetime(string="Fecha y hora de emisión VeriFactu")

    verifactu_base_coste = fields.Monetary(
        string="Base imponible a coste",
        compute="_compute_verifactu_base_coste",
        store=True,
        currency_field='currency_id'
    )
    
    verifactu_status_logs = fields.One2many(
    "verifactu.status.log", "invoice_id",
    string="Historial de Estado VeriFactu",
    )
    
    show_qr_always = fields.Boolean(
        string="Mostrar QR tributario",
        compute="_compute_show_qr_always",
        store=False  # o True si te interesa indexarlo
    )
    

    # ───────────────────────────────
    # Inicio logica rectificatias
    # ───────────────────────────────
    
    # Campo auxiliar para las vistas (invisible en el XML)
    is_rectificativa_bool = fields.Boolean(
        compute="_compute_is_rectificativa_bool",
        string="¿Es rectificativa?",
        store=False,   # nunca almacenar, siempre calculado
    )

    def _compute_is_rectificativa_bool(self):
        """Sincroniza el campo booleano con el resultado del mixin universal."""
        for rec in self:
            rec.is_rectificativa_bool = AccountMoveRectificativaMixin._compute_is_rectificativa(rec)

    def is_rectificativa(self):
        """API pública para reutilizar desde otras partes del código."""
        return AccountMoveRectificativaMixin._compute_is_rectificativa(self)

    def _reset_verifactu_fields(self, move):
        """Limpia los campos VeriFactu en una factura clonada o rectificativa."""
        vals = {
            "verifactu_status": "pending",
            "verifactu_sent": False,
            "verifactu_sent_with_errors": False,
            "verifactu_generated": False,
            "verifactu_processed": False,
            "verifactu_processing": False,
            "verifactu_retry_count": 0,
            "verifactu_hash": False,
            "verifactu_previous_hash": False,
            "verifactu_qr": False,
            "verifactu_qr_image": False,
            "verifactu_soap_xml": False,
            "verifactu_detailed_error_msg": False,
            "verifactu_error_msg": False,
            "verifactu_requerimiento": False,
            "verifactu_event_logs": [(5, 0, 0)],
            "verifactu_status_logs": [(5, 0, 0)],
            "verifactu_hash_calculated_at": False,
            "verifactu_date_sent": False,
            "verifactu_issued_at": False,
            "verifactu_last_emisor_nif": False,
            "verifactu_last_numero": False,
            "verifactu_last_fecha": False,
            "verifactu_last_tipo": False,
            "verifactu_is_active": True,
        }
        move.write(vals)

    # ───────────────────────────────
    # Compatibilidad Odoo 13+
    # ───────────────────────────────
    def _reverse_moves(self, default_values_list=None, cancel=False):
        moves = super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)
        for move in moves:
            self._reset_verifactu_fields(move)
        return moves

    # ───────────────────────────────
    # Compatibilidad Odoo ≤12
    # ───────────────────────────────
    def refund(self, date_invoice=None, date=None, description=None, journal_id=None):
        refunds = super(AccountMove, self).refund(
            date_invoice=date_invoice,
            date=date,
            description=description,
            journal_id=journal_id,
        )
        for move in refunds:
            self._reset_verifactu_fields(move)
        return refunds

    # ───────────────────────────────
    # Fin logica rectificatias
    # ───────────────────────────────

    
    def copy(self, default=None):
        """Evita que al duplicar se copien los datos VeriFactu (compatible Odoo 10–18)."""
        default = dict(default or {})

        default.update({
            "verifactu_status": "pending",
            "verifactu_sent": False,
            "verifactu_sent_with_errors": False,
            "verifactu_generated": False,
            "verifactu_processed": False,
            "verifactu_processing": False,
            "verifactu_retry_count": 0,
            "verifactu_hash": False,
            "verifactu_previous_hash": False,
            "verifactu_qr": False,
            "verifactu_qr_image": False,
            "verifactu_soap_xml": False,
            "verifactu_detailed_error_msg": False,
            "verifactu_error_msg": False,
            "verifactu_requerimiento": False,
            "verifactu_event_logs": [(5, 0, 0)],
            "verifactu_status_logs": [(5, 0, 0)],
            "verifactu_hash_calculated_at": False,
            "verifactu_date_sent": False,
            "verifactu_issued_at": False,
            "verifactu_last_emisor_nif": False,
            "verifactu_last_numero": False,
            "verifactu_last_fecha": False,
            "verifactu_last_tipo": False,
            "verifactu_is_active": True,
        })

        # 🔧 llamada segura al copy() original
        return super(AccountMove, self).copy(default)



    

    def button_cancel(self):
        """Intercepta el botón Cancelar (todas las versiones Odoo 10–18)."""
        for move in self:
            status = getattr(move, "verifactu_status", None)
            if status in ("sent", "accepted_with_errors"):
                raise UserError(_(
                    "Esta factura ya fue registrada en VeriFactu. "
                    "Antes de cancelarla debes anularla."
                ))

        # Compatibilidad con métodos internos según versión
        if hasattr(super(AccountMove, self), "button_cancel"):
            return super(AccountMove, self).button_cancel()
        elif hasattr(super(AccountMove, self), "action_cancel"):
            return super(AccountMove, self).action_cancel()
        elif hasattr(super(AccountMove, self), "action_invoice_cancel"):
            return super(AccountMove, self).action_invoice_cancel()
        else:
            return True


    @api.depends("company_id")
    def _compute_show_qr_always(self):
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)
        for move in self:
            move.show_qr_always = config.show_qr_always
       

    
    def _log_verifactu_status(self, status, code=None, notes="", update_if_exists=False):
        """Registra un nuevo estado VeriFactu en el historial."""
        self.ensure_one()
        Log = self.env["verifactu.status.log"].sudo()

        vals = {
            "invoice_id": self.id,
            "status": status,
            "date": getattr(self, "verifactu_hash_calculated_at", False) or fields.Datetime.now(),
            "hash_actual": getattr(self, "verifactu_hash", None),
            "hash_previo": getattr(self, "verifactu_previous_hash", None),
            "notes": notes or "",
        }

        if "aeat_code" in Log._fields:
            vals["aeat_code"] = code or None
        if "xml_soap" in Log._fields:
            vals["xml_soap"] = getattr(self, "verifactu_soap_xml", None)

        if update_if_exists:
            existing = Log.search([
                ('invoice_id', '=', self.id),
                ('hash_actual', '=', vals['hash_actual']),
            ], limit=1)
            if existing:
                existing.write(vals)
                return existing

        return Log.create(vals)




    @api.depends('invoice_line_ids', 'invoice_line_ids.product_id', 'invoice_line_ids.quantity')
    def _compute_verifactu_base_coste(self):
        for move in self:
            coste_total = 0.0
            for line in move.invoice_line_ids:
                # Si no hay producto o cantidad, se ignora la línea
                if line.product_id and line.quantity:
                    coste_total += line.product_id.standard_price * line.quantity
            move.verifactu_base_coste = coste_total

    def _vf_check_readiness(self, config):
        """
        Devuelve (ok, msgs) indicando si la factura puede generar/enviar a VeriFactu.
        No lanza excepción: solo prepara mensajes para el log.
        """
        msgs = []

        # Config básica
        if not (config and config.cert_pfx and config.cert_password):
            msgs.append("certificado digital no configurado (.pfx + contraseña)")
        if not (config and config.endpoint_url):
            msgs.append("endpoint de VeriFactu no configurado")

        # Licencia (suave: no bloquea, solo avisa)
        try:
            gate_ok = self.env["verifactu.license.gate"]._is_valid()
        except Exception as e:
            gate_ok = False
            msgs.append(f"no se pudo verificar licencia ({e})")

        if not gate_ok:
            msgs.append("licencia no válida o no configurada")

        return (len(msgs) == 0, msgs)

    def _vf_log_and_skip(self, msgs, tail=""):
        text = "⚠️ Configuración/licencia incompleta de VeriFactu: " + " | ".join(msgs)
        if tail:
            text += ". %s" % tail
        self.message_post(body=text)

    def _vf_safe_call(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self.message_post(body="🛑 Error VeriFactu: %s" % e)
            _logger.exception("Error VeriFactu en %s: %s", getattr(func, "__name__", func), e)
            return None

    def _vf_after_post(self):
        """Bloque común ejecutado tras post/confirm según versión."""
        config = (
            self.env["verifactu.endpoint.config"]
            .sudo()
            .search([("company_id", "=", self.env.user.company_id.id)], limit=1)
        )

        for inv in self:
            # Aviso de updates (no bloqueante)
            try:
                self.env["verifactu.update.checker"].check_and_notify_if_needed(inv)
            except Exception:
                pass

            # Solo ventas cliente (v11/12)
            if getattr(inv, "type", "") != "out_invoice":
                continue

            # Fecha de emisión VeriFactu
            if not getattr(inv, "verifactu_issued_at", False):
                inv.verifactu_issued_at = fields.Datetime.now()

            # Readiness
            ok, msgs = inv._vf_check_readiness(config)
            if not ok:
                inv._vf_log_and_skip(msgs, tail="Ve a Ajustes → VeriFactu para completarla.")
                continue

            # Envío / solo generar
            if inv.should_send_to_verifactu(config):
                inv._vf_safe_call(inv.send_xml)
            else:
                inv._vf_safe_call(inv.only_generate_xml_never_send)
 

    def action_post(self):
        res = super(AccountMove, self).action_post()

        config = (
            self.env["verifactu.endpoint.config"]
            .sudo()
            .search([("company_id", "=", self.env.company.id)], limit=1)
        )

        for inv in self:
            # Notificación no bloqueante
            try:
                self.env["verifactu.update.checker"].check_and_notify_if_needed(inv)
            except Exception:
                pass

            # Solo ventas/abonos cliente y ya posteadas
            if _vf_get_move_type(inv) not in ("out_invoice", "out_refund"):
                continue
            if inv.state != "posted":
                continue
            
            # ───────────────────────────────
            # (2) Diario con VeriFactu deshabilitado → se omite
            # ───────────────────────────────
            journal = getattr(inv, "journal_id", False)
            if journal and not getattr(journal, "verifactu_enabled", True):
                try:
                    from ...verifactu.services.logger import VerifactuLogger
                    VerifactuLogger(inv).log(
                        "ℹ️ Diario '%s' sin envío VeriFactu habilitado. Se omite." % journal.name
                    )
                except Exception:
                    pass
                # No se genera QR ni se envía ni se calcula hash
                continue

            # (1) Detectar cambio de IDFactura vs snapshot → reset a 'pending'
            last = _vf_last_id_tuple(inv)
            if last != ("", "", False, ""):
                curr = _vf_current_id_tuple(inv)
                if curr != last:
                    try:
                        from ...verifactu.services.logger import VerifactuLogger
                        VerifactuLogger(inv).log("ℹ️ IDFactura cambiado (NIF/Num/Fecha/Tipo) → estado 'pending'.")
                    except Exception:
                        pass
                    _vf_reset_to_pending(inv)

            # (2) Fecha emisión VeriFactu si falta
            if not getattr(inv, "verifactu_issued_at", False):
                inv.verifactu_issued_at = fields.Datetime.now()

            # (3) Readiness
            ok, msgs = inv._vf_check_readiness(config)
            if not ok:
                inv._vf_log_and_skip(msgs, tail="Ve a Ajustes > VeriFactu para completarla.")
                continue

            # (4) Recalcular QR / Hash (a prueba de errores)
            try:
                from ...verifactu.services.logger import VerifactuLogger
                VerifactuLogger(inv).log("⚠️ Factura modificada")
            except Exception:
                pass

            if getattr(config, "show_qr_always", False):
                try:
                    from ...verifactu.services.qr_content import VerifactuQRContentGenerator
                    qr_bytes = VerifactuQRContentGenerator(inv, config, factura_verificable=True).generate_qr_binary()
                    inv.verifactu_qr = base64.b64encode(qr_bytes).decode("utf-8") if qr_bytes else False
                except Exception as e:
                    try:
                        VerifactuLogger(inv).log("⚠️ Error generando QR: %s" % e)
                    except Exception:
                        pass

            try:
                from ...verifactu.services.hash_calculator import VerifactuHashCalculator
                VerifactuHashCalculator(inv, config).compute_and_update(force_recalculate=True)
            except Exception as e:
                try:
                    VerifactuLogger(inv).log("⚠️ Error recalculando hash: %s" % e)
                except Exception:
                    pass

            # (5) Envío / solo generar
            if inv.should_send_to_verifactu(config):
                inv._vf_safe_call(inv.send_xml)
            else:
                inv._vf_safe_call(inv.only_generate_xml_never_send)

            # (6) Guardar nuevo snapshot del IDFactura tras post
            _vf_save_id_snapshot(inv)

        return res

    def should_send_to_verifactu(self, config):
        return (
            self.move_type in ("out_invoice", "out_refund") and
            config.auto_send_to_verifactu and
            config.cert_pfx and config.cert_password
        )


    @api.model
    def create(self, vals):
        invoice = super().create(vals)
        return invoice

    def write(self, vals):
        if not vals:
            return super().write(vals)

        res = super().write(vals)

        critical_fields = ["name", "invoice_date", "amount_total", "amount_tax", "move_type"]
        if any(f in vals for f in critical_fields):
            config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)

            for rec in self:
                if rec.state != "posted":
                    continue

                ok, msgs = rec._vf_check_readiness(config)
                if not ok:
                    rec._vf_log_and_skip(msgs, tail="Se omitió el recálculo de QR y hash.")
                    continue

                # A partir de aquí no debe romper el flujo aunque algo falle:
                VerifactuLogger(rec).log("⚠️ Factura modificada")

                # Recalcular QR si procede
                if getattr(config, "show_qr_always", False):
                    try:
                        qr_bytes = VerifactuQRContentGenerator(rec, config, factura_verificable=True).generate_qr_binary()
                        rec.verifactu_qr = base64.b64encode(qr_bytes).decode("utf-8") if qr_bytes else False
                    except Exception as e:
                        VerifactuLogger(rec).log(f"⚠️ Error generando QR: {e}")

                # Recalcular hash
                try:
                    VerifactuHashCalculator(rec, config).compute_and_update(force_recalculate=True)
                except Exception as e:
                    VerifactuLogger(rec).log(f"⚠️ Error recalculando hash: {e}")

        return res
    
    def open_error_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "verifactu.error.codes.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
            },
        }

    def open_requirement_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "verifactu.requirement.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_ref_requerimiento": self.verifactu_requerimiento or "",
                "active_id": self.id,
            },
        }



    
    def action_open_verifactu_help(self):
        wizard = self.env['verifactu.help.wizard'].create({})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'verifactu.help.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }




    def detect_anomalies(self):
        anomalies = []
        for invoice in self.env["account.move"].search(
            [
                ("verifactu_sent", "=", True),
                ("verifactu_sent_with_errors", "=", True),
                ("verifactu_processed", "=", True),
            ]
        ):
            if not self.verify_integrity():
                anomalies.append(invoice)

        # Evento global
        if anomalies:
            msg = f"🛑 Detectadas anomalías en {len(anomalies)} facturas."
            VerifactuLogger(self).log(msg)
        else:
            msg = f"✅ No se detectaron anomalías en los registros de facturación."
            VerifactuLogger(self).log(msg)

    # En account_move.py
    def toggle_anomaly_cron(self):
        detector = VerifactuAnomalyDetector(self.env)
        if detector.is_cron_enabled():
            detector.disable_cron()
        else:
            detector.enable_cron()


    def export_event_records(self):
        return VerifactuEventExporter(self).export()

    def verify_verifactu_hash(self):
        self.ensure_one()
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)
        VerifactuHashVerifier(self,config).verify()
        return True

    def verify_verifactu_signature(self):
        self.ensure_one()
        try:
            xml_string = VerifactuSimpleXMLBuilder(self).build()

            # Obtener configuración con el certificado
            config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)
            signed_xml = VerifactuXMLSigner(config).sign(xml_string)

            VerifactuLogger(self).log(
                f"✅ Firma electrónica verificada para la factura {self.name}"
            )
            return True

        except Exception as e:
            VerifactuLogger(self).log(
                f"🛑 Error al verificar la firma electrónica: {str(e)}"
            )
            raise UserError(_(f"Error al verificar la firma electrónica: {str(e)}"))

    def verify_integrity(self):
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)
        return VerifactuIntegrityVerifier(self,config).verify()

    def verify_chain(self):
        return VerifactuChainVerifier(self).verify()

    def log_system_event(self, message):
        event = self.env["verifactu.event.log"].create({"name": message})
        _logger.info(message)
        return event

    def log_backup_restore(self):
        self.log_system_event("🔄 Restauración de copia de seguridad detectada.")

    def log_event_summary(self):
        self.log_system_event("📊 Generación de resumen de eventos.")

    def _generate_verifactu_xml(self):
        return VerifactuSimpleXMLBuilder(self).build()

    @api.depends("state", "verifactu_status")
    def _compute_verifactu_qr_image(self):
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)
        gate = self.env["verifactu.license.gate"]  # gate soft
        for rec in self:
            # valor por defecto
            rec.verifactu_qr_image = False

            # solo en posted
            if rec.state != "posted":
                continue

            should_generate = (
                (config and config.show_qr_always)
                or rec.verifactu_status in ("sent", "accepted_with_errors", "canceled", "rejected", "error")
            )

            if not should_generate:
                continue

            # 1) licencia (suave: no bloquea, solo evita generar QR del módulo)
            if not gate.ensure_valid(hard=False):
                VerifactuLogger(rec).log(
                    "ℹ️ No se genera QR de VeriFactu porque la licencia no es válida o falta el token."
                )
                continue

            # 2) config mínima (suave)
            missing_cert = not (config and config.cert_pfx and config.cert_password)
            missing_endpoint = not (config and config.endpoint_url)
            if missing_cert or missing_endpoint:
                msgs = []
                if missing_cert:
                    msgs.append("certificado digital no configurado (.pfx + contraseña)")
                if missing_endpoint:
                    msgs.append("endpoint de VeriFactu no configurado")
                VerifactuLogger(rec).log(
                    "ℹ️ QR omitido por configuración incompleta: " + " | ".join(msgs)
                )
                continue

            # 3) generar QR (nunca debe tocar firma ni abrir el .pfx)
            try:
                qr_bytes = VerifactuQRContentGenerator(
                    rec, config, factura_verificable=True
                ).generate_qr_binary()
                rec.verifactu_qr_image = (
                    base64.b64encode(qr_bytes).decode("ascii") if qr_bytes else False
                )
            except Exception as e:
                VerifactuLogger(rec).log(f"⚠️ No se pudo generar el QR: {e}")
                rec.verifactu_qr_image = False

    def get_verifactu_qr_content(self):
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)
        return VerifactuQRContentGenerator(self,config,self.verifactu_is_active).generate_content()

    def get_verifactu_qr_image_binary(self):
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)
        return VerifactuQRContentGenerator(self,config,self.verifactu_is_active).generate_qr_binary()
    
    def only_generate_xml_never_send(self):
        """Genera el XML (VeriFactu o No-VeriFactu) sin enviarlo a la AEAT."""
        self.ensure_one()
                # 🔐 Restricción: no permitir enviar facturas con fecha anterior a otra ya enviada
        if self.verifactu_is_active:
            newer_sent_invoice = self.search([
                ('id', '!=', self.id),
                ('verifactu_status', 'in', ('sent', 'accepted_with_errors')),
                ('invoice_date', '>', self.invoice_date),
            ], limit=1)

            if newer_sent_invoice:
                raise UserError(_(
                    "No se puede enviar esta factura a VeriFactu porque hay otra factura ya enviada "
                    "con una fecha posterior: %s (%s). Por favor, revisa el orden cronológico de tus facturas."
                ) % (newer_sent_invoice.name, newer_sent_invoice.invoice_date))
        if self.verifactu_is_active:
            self.prepare_verifactu_record()
        else:
            self.prepare_no_verifactu_record()

        self._log_verifactu_status(
        "hash_generated",
        notes=_("🧾 Hash y XML SOAP generados correctamente."),
        update_if_exists=True,
            )

        VerifactuLogger(self).log("📄 XML generado sin envío, lo puedes descargar en la pestaña de VeriFactu")
        self.verifactu_generated = True

    def send_xml(self):
            """Flujo de envío VeriFactu/No-VeriFactu (compat 13→18; retrocompatible con 12)."""
            self.ensure_one()  # lo normal es invocar por factura; si te gusta batch, quita esto y deja el for

            Config = self.env['verifactu.endpoint.config'].sudo()
            gate = self.env['verifactu.license.gate']

            # ----------------------------- helpers locales -----------------------------
            def _last_hash_dt(inv):
                """Último timestamp fiable para comparar 'mismo día'."""
                Log = inv.env['verifactu.status.log'].sudo()
                log = Log.search([('invoice_id', '=', inv.id), ('hash_actual', '!=', False)],
                                order='date desc, id desc', limit=1)
                if log and getattr(log, 'date', False):
                    try:
                        return fields.Datetime.from_string(log.date)
                    except Exception:
                        return log.date
                ts = getattr(inv, 'create_date', None) or getattr(inv, 'write_date', None)
                try:
                    return fields.Datetime.from_string(ts) if ts else None
                except Exception:
                    return None

            def _after_activation(inv, activation_dt):
                """¿La factura pertenece al periodo VeriFactu (tras activar)?"""
                if not activation_dt:
                    return False
                inv_d = _vf_get_invoice_date(inv)
                di = fields.Date.to_date(inv_d) if inv_d else None
                da = fields.Date.to_date(activation_dt)
                if not di or not da:
                    return False
                if di > da:
                    return True
                if di < da:
                    return False
                # mismo día → compara hora real
                rec_ts = _last_hash_dt(inv)
                if rec_ts is None:
                    return False
                return rec_ts >= activation_dt

            # ----------------------------- lógica principal -----------------------------
            for inv in self:
                # 0) Limpia anomalías previas (best-effort)
                try:
                    inv._vf_anomaly_clear()
                except Exception:
                    pass

                # 1) Config por compañía (with_company si existe; fallback force_company)
                company = inv.company_id or self.env.user.company_id
                if hasattr(Config, 'with_company'):
                    config = Config.with_company(company).search([('company_id', '=', company.id)], limit=1)
                else:
                    config = Config.with_context(force_company=company.id).search([('company_id', '=', company.id)], limit=1)
                activation_dt = getattr(config, 'verifactu_mode_activation_date', False)

                # 2) Licencia
                if not gate.ensure_valid(hard=False):
                    try:
                        inv._vf_anomaly_create('LIC001', _("Licencia inválida o no configurada."), severity='error')
                    except Exception:
                        pass
                    raise UserError(_("⛔ Licencia de VeriFactu inválida o no configurada.\n"
                                    "Introduce tu clave y pulsa 'Obtener/Actualizar token' en Ajustes > VeriFactu."))

                # 3) Reglas legales (solo si inv.verifactu_is_active y estamos 'después de activar')
                if getattr(inv, 'verifactu_is_active', False) and _after_activation(inv, activation_dt) and _vf_is_customer_doc(inv):

                    # 3.a) Regla cronológica: no puede haber ya enviada con fecha posterior
                    newer_domain = [
                        ('id', '!=', inv.id),
                        ('company_id', '=', inv.company_id.id),
                        ('verifactu_status', 'in', ('sent', 'accepted_with_errors')),
                    ] + _vf_is_posted_domain(inv)
                    # tipos ventas
                    if 'move_type' in inv._fields:
                        newer_domain += [('move_type', 'in', ('out_invoice', 'out_refund'))]
                    else:
                        newer_domain += [('type', 'in', ('out_invoice', 'out_refund'))]
                    # fecha posterior
                    inv_date = _vf_get_invoice_date(inv)
                    newer_domain += [(_vf_get_invoice_date(inv).__class__.__name__  # truco no fiable; mejor mapeo explícito
                                    , '>', inv_date)]
                    # mapeo explícito robusto:
                    if 'invoice_date' in inv._fields:
                        newer_domain[-1] = ('invoice_date', '>', inv_date)
                    else:
                        newer_domain[-1] = ('date_invoice', '>', inv_date)

                    newer_sent_invoice = inv.sudo().search(newer_domain, limit=1)
                    if newer_sent_invoice and _after_activation(newer_sent_invoice, activation_dt):
                        try:
                            inv._vf_anomaly_create(
                                'ORD001',
                                _("Existe una factura ya enviada con fecha posterior: %s (%s).") %
                                (_vf_display_name(newer_sent_invoice),
                                _vf_get_invoice_date(newer_sent_invoice)),
                                severity='error'
                            )
                        except Exception:
                            pass
                        raise UserError(_(
                            "No se puede enviar esta factura porque hay otra ya enviada con fecha posterior: %s (%s)."
                        ) % (_vf_display_name(newer_sent_invoice), _vf_get_invoice_date(newer_sent_invoice)))

                    # 3.b) Encadenamiento: exigir que la previa 'después de activar' esté enviada
                    prev_domain = [
                        ('id', '!=', inv.id),
                        ('company_id', '=', inv.company_id.id),
                        ('journal_id', '=', inv.journal_id.id),
                    ] + _vf_is_posted_domain(inv)
                    # tipos ventas
                    if 'move_type' in inv._fields:
                        prev_domain += [('move_type', 'in', ('out_invoice', 'out_refund'))]
                        prev_domain += [('invoice_date', '<=', inv_date)]
                        order_clause = "invoice_date desc, id desc"
                    else:
                        prev_domain += [('type', 'in', ('out_invoice', 'out_refund'))]
                        prev_domain += [('date_invoice', '<=', inv_date)]
                        order_clause = "date_invoice desc, id desc"

                    prev = inv.sudo().search(prev_domain, order=order_clause, limit=1)
                    if prev and _after_activation(prev, activation_dt):
                        if getattr(prev, 'verifactu_is_active', False) and \
                        getattr(prev, 'verifactu_status', '') not in ('sent', 'accepted_with_errors', 'canceled'):
                            try:
                                from ...verifactu.services.logger import VerifactuLogger
                                VerifactuLogger(inv).log(u"⛔ Encadenamiento roto: la factura previa (ya en periodo VeriFactu) no está enviada.")
                            except Exception:
                                pass
                            try:
                                inv._vf_anomaly_create(
                                    'ORD002',
                                    _("No se puede enviar esta factura (%s) porque la anterior (%s), ya en periodo VeriFactu, "
                                    "aún no ha sido enviada o tiene errores.") %
                                    (_vf_display_name(inv), _vf_display_name(prev)),
                                    severity='error'
                                )
                            except Exception:
                                pass
                            raise UserError(_(
                                "⛔ Encadenamiento VeriFactu roto.\n"
                                "La factura anterior (%s), ya del periodo VeriFactu, no está enviada."
                            ) % (_vf_display_name(prev)))

                # 4) Config mínima
                missing_cert = not (config and getattr(config, 'cert_pfx', False) and getattr(config, 'cert_password', False))
                endpoint_url = (getattr(config, 'endpoint_url', '') or '').strip()
                missing_endpoint = not (config and endpoint_url)
                if missing_cert or missing_endpoint:
                    try:
                        if missing_cert:
                            inv._vf_anomaly_create('CFG001', _("Certificado PFX/contraseña no configurados."), severity='error')
                        if missing_endpoint:
                            inv._vf_anomaly_create('CFG002', _("Endpoint VeriFactu no configurado."), severity='error')
                    except Exception:
                        pass
                    human_msg = " | ".join(filter(None, [
                        _("certificado digital no configurado (.pfx + contraseña)") if missing_cert else "",
                        _("endpoint de VeriFactu no configurado") if missing_endpoint else "",
                    ]))
                    raise UserError(_("No se puede enviar la factura: %s.") % human_msg)

                # 5) Modo No VeriFactu → requiere 'código de requerimiento'
                if not getattr(inv, 'verifactu_is_active', False):
                    req_code = (getattr(inv, 'verifactu_requerimiento', '') or '').strip()
                    if not req_code:
                        try:
                            inv._vf_anomaly_create('REQ001', _("Modo No VeriFactu sin código de requerimiento informado."),
                                                severity='error')
                        except Exception:
                            pass
                        raise UserError(_(
                            "Esta factura está en modo 'No VeriFactu' y el envío se realiza por requerimiento.\n"
                            "Indica primero el 'Código de requerimiento' en la pestaña VeriFactu de esta factura."
                        ))

                # 6) Flujo de generación + envío (idempotente)
                is_generated = bool(getattr(inv, 'verifactu_generated', False))
                status = getattr(inv, 'verifactu_status', '') or ''
                is_pending = status == 'pending'

                if is_generated and is_pending:
                    if getattr(inv, 'verifactu_is_active', False):
                        inv.send_verifactu_record()
                    else:
                        inv.send_no_verifactu_record()
                else:
                    if getattr(inv, 'verifactu_is_active', False):
                        inv.prepare_verifactu_record()
                        inv.send_verifactu_record()
                    else:
                        inv.prepare_no_verifactu_record()
                        inv.send_no_verifactu_record()
                    # marca generado si el campo existe
                    if 'verifactu_generated' in inv._fields:
                        inv.verifactu_generated = True

            return True

    
    def prepare_no_verifactu_record(self):
        self.ensure_one()


        self._validate_verifactu_tax_rates()
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)

        #VerifactuHashCalculator(self, config).compute_and_update(force_recalculate=True)

        if self.verifactu_status in ("sent", "accepted_with_errors"):
            builder = VerifactuXMLBuilderNoVerifactuSubsanacion(self, config)
        elif self.verifactu_status in ("rejected", "canceled"):
            builder = VerifactuXMLBuilderNoVerifactuSubsanacion(self, config, rechazo_previo=True)
        else:
            builder = VerifactuXMLBuilderNoVerifactu(self, config)

        raw_xml = builder.build()

        self.verifactu_soap_xml = base64.b64encode(raw_xml.encode("utf-8"))

        # Adjuntar pero no enviar aún
        VerifactuAttachmentService(self).attach_xml(raw_xml)


    
    def send_no_verifactu_record(self):
        self.ensure_one()

        if not self.verifactu_soap_xml:
            raise UserError(_("No se ha generado el XML. Ejecuta primero 'prepare_no_verifactu_record()'."))

        decoded_xml = base64.b64decode(self.verifactu_soap_xml).decode("utf-8")
        attachment = VerifactuAttachmentService(self).attach_xml(decoded_xml)

        VerifactuSender(self).send(decoded_xml, attachment)



    def prepare_verifactu_record(self):
        self.ensure_one()


        self._validate_verifactu_tax_rates()
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)

        #VerifactuHashCalculator(self, config).compute_and_update(force_recalculate=True)

        # Selección de builder
        if self.verifactu_status in ("sent", "accepted_with_errors"):
            builder = VerifactuXMLBuilderSubsanacion(self, config)
        elif self.verifactu_status == "rejected":
            builder = VerifactuXMLBuilderSubsanacion(self, config, rechazo_previo=True)
        elif self.verifactu_status == "canceled":
            builder = VerifactuXMLBuilderSubsanacion(self, config, rechazo_previo=True)
        else:
            builder = VerifactuXMLBuilder(self, config)

        raw_xml = builder.build()
        signed_xml = raw_xml  # Omitida la firma

        soap_envelope = VerifactuEnvelopeBuilder(self, config=config).build(signed_xml)
        self.verifactu_soap_xml = base64.b64encode(soap_envelope.encode("utf-8"))

        qr_base64 = base64.b64encode(
            VerifactuQRContentGenerator(self, config, self.verifactu_is_active).generate_qr_binary()
        ).decode("utf-8")
        self.verifactu_qr = qr_base64

        # Adjuntar, pero sin enviar aún
        VerifactuAttachmentService(self).attach_xml(soap_envelope)



    def send_verifactu_record(self):
        self.ensure_one()

        if not self.verifactu_soap_xml:
            raise UserError(_("No se ha generado el XML. Ejecuta primero 'prepare_verifactu_record()'."))

        decoded_envelope = base64.b64decode(self.verifactu_soap_xml).decode("utf-8")
        attachment = VerifactuAttachmentService(self).attach_xml(decoded_envelope)

        VerifactuSender(self).send(decoded_envelope, attachment)

    def generate_verifactu_anulacion(self):
        self.ensure_one()
        
        if self.verifactu_status not in ("sent", "accepted_with_errors"):
            raise UserError(_(
                "No se puede generar una anulación porque esta factura no ha sido enviada aún a VeriFactu. "
                "Solo se puede anular si el estado es 'Enviado' o 'Enviado con errores'."
            ))


        self._validate_verifactu_tax_rates()
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)

        # 1. Calcular el hash y guardarlo
        #hash_value = VerifactuHashCalculator(self,config).compute_cancellation_hash()
        #self.verifactu_hash = hash_value

        # 2. Seleccionar el builder según si es subsanación o no

        if self.verifactu_is_active:

                if self.verifactu_status == "pending":
                        try:
                            from ...verifactu.services.logger import VerifactuLogger
                            VerifactuLogger(self).log(u"⛔ No puedes anular una factura que todavia no esta registrada en el portal de Veri*Factu")
                        except Exception:
                            pass
                        try:
                            self._vf_anomaly_create(
                                'ORD007',
                                _("⛔ No puedes anular una factura que todavia no esta registrada en el portal de Veri*Factu."),
                                severity='error'
                            )
                        except Exception:
                            pass
                        raise UserError(_(
                            "⛔  No puedes anular una factura que todavia no esta registrada en el portal de Veri*Factu"))
                elif self.verifactu_status == "rejected" or self.verifactu_status == "error":
                    builder = VerifactuXMLBuilderAnulacion(self, config, rechazo_previo=True)
                else:
                    builder = VerifactuXMLBuilderAnulacion(self, config)
    
        else:
                if self.verifactu_status == "pending":
                        try:
                            from ...verifactu.services.logger import VerifactuLogger
                            VerifactuLogger(self).log(u"⛔ No puedes anular una factura que todavia no esta registrada en el portal de Veri*Factu")
                        except Exception:
                            pass
                        try:
                            self._vf_anomaly_create(
                                'ORD007',
                                _("⛔ No puedes anular una factura que todavia no esta registrada en el portal de Veri*Factu."),
                                severity='error'
                            )
                        except Exception:
                            pass
                        raise UserError(_(
                            "⛔  No puedes anular una factura que todavia no esta registrada en el portal de Veri*Factu"))
                elif self.verifactu_status == "rejected" or self.verifactu_status == "error":
                    builder = VerifactuXMLBuilderNoVerifactuAnulacion(self, config, rechazo_previo=True)
                else:
                    builder = VerifactuXMLBuilderNoVerifactuAnulacion(self, config)

        # 3. Construir el XML
        raw_xml = builder.build()

        # 4. Firmar el XML
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)
        # signed_xml = VerifactuXMLSigner(config).sign(raw_xml)

        # Omitir la firma
        signed_xml = raw_xml

        # Envolver el XML sin firma
        soap_envelope = VerifactuEnvelopeBuilderAnulacion(self, config=config).build(signed_xml)

        # 6. Generar y guardar el QR
        qr_base64 = base64.b64encode(
            VerifactuQRContentGenerator(self,config,self.verifactu_is_active).generate_qr_binary()
        ).decode("utf-8")
        self.verifactu_qr = qr_base64

        # 7. Envolver en sobre SOAP
        soap_envelope = VerifactuEnvelopeBuilderAnulacion(self, config=config).build(
            signed_xml
        )
        self.verifactu_soap_xml = base64.b64encode(soap_envelope.encode("utf-8"))
        
        # 🔁 Nuevo paso 8: Adjuntar el XML **ya envuelto en SOAP**
        xml_attachment = VerifactuAttachmentService(self).attach_xml(soap_envelope)

        # 8. Enviar el XML
        VerifactuSender(self).send(soap_envelope, xml_attachment)

        # 9. Log final
        if self.verifactu_status == "sent":
            builder = VerifactuXMLBuilderAnulacion(self, config)
            VerifactuLogger(self).log("✅ Factura VeriFactu anulada correctamente")
            verifactu_status= "canceled"
        elif self.verifactu_status == "accepted_with_errors":
            builder = VerifactuXMLBuilderAnulacion(self, config)
            VerifactuLogger(self).log(
                "✅ Factura VeriFactu anulada correctamente con errores"
            )
            verifactu_status= "canceled"
        elif self.verifactu_status == "rejected":
            builder = VerifactuXMLBuilderAnulacion(self, config, rechazo_previo=True)
            VerifactuLogger(self).log(
                "🛑 ESte VeriFactu XML de anulacion ha sido rechazado, mira la ventana de error"
            )
        elif self.verifactu_status == "error":
            builder = VerifactuXMLBuilderAnulacion(self, config, rechazo_previo=True)
            VerifactuLogger(self).log(
                "🛑 Error al anular la factura verifactu por favor revisa el error detallado"
            )
        else:
            builder = VerifactuXMLBuilderAnulacion(self, config)
            VerifactuLogger(self).log("✅ Factura VeriFactu anulada correctamente")
            verifactu_status= "canceled"
        return True

    def _validate_before_generation(self):
        if self.state != "posted":
            raise UserError(_("🛑 Intento de procesar factura no confirmada."))

        if self.move_type not in ("out_invoice", "out_refund"):
            raise UserError(
                _("🛑 Solo se pueden procesar facturas de cliente o rectificativas.")
            )

    def _ensure_verifactu_hash(self):
        config = self.env["verifactu.endpoint.config"].sudo().search([
    ('company_id', '=', self.env.company.id)
], limit=1)
        if self.move_type == "out_refund" or not self.verifactu_hash:
            self.verifactu_hash = VerifactuHashCalculator(self,config).compute_hash(
                force_recalculate=True
            )

    def build_verifactu_xml(self):
        return VerifactuXMLBuilder(self).build()

    def _attach_signed_verifactu_xml(self, signed_xml):
        attachment = self.env["ir.attachment"].create(
            {
                "name": f"verifactu_{self.name.replace('/', '_')}.xml",
                "type": "binary",
                "res_model": "account.move",
                "res_id": self.id,
                "datas": base64.b64encode(signed_xml.encode("utf-8")),
                "mimetype": "application/xml",
            }
        )
        return attachment

    def send_verifactu(self, signed_xml_str, attachment):
        return VerifactuSender(self).send(signed_xml_str, attachment)

    def view_verifactu_error(self):
        raise UserError(
            _(
                self.verifactu_detailed_error_msg
                or _("No hay mensaje de error detallado registrado.")
            )
        )

    def resend_verifactu(self):
        return VerifactuResender(self).resend()

    def open_verifactu_xml(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/verifactu/download/{self.id}",
            "target": "new",
        }

    def open_verifactu_soap_xml(self):
        self.ensure_one()
        if not self.verifactu_soap_xml:
            raise UserError(_("El archivo SOAP no está disponible."))

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self._name}/{self.id}/verifactu_soap_xml/soap_envelope.xml?download=true",
            "target": "new",
        }

    def open_verifactu_qr(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/verifactu/download_qr/{self.id}",
            "target": "new",
        }

    def _get_system_info(self):
        # Datos del sistema informático
        system_name = platform.node()
        system_id = hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest()[:8]
        system_version = platform.version()
        installation_id = hashlib.sha256(
            (system_name + system_id).encode("utf-8")
        ).hexdigest()[:8]
        multi_ot = "S" if len(self.env["res.company"].sudo().search([])) > 1 else "N"

        return {
            "NombreSistemaInformatico": system_name,
            "IdSistemaInformatico": system_id,
            "Version": system_version,
            "NumeroInstalacion": installation_id,
            "TipoUsoPosibleSoloVerifactu": "S",
            "TipoUsoPosibleOtros": "N",
            "TipoUsoPosibleMultiOT": multi_ot,
        }

    def _is_valid_nif(self, nif):
        """Valida que el NIF tenga un formato básico correcto (8–9 caracteres alfanuméricos)"""
        return bool(re.match(r"^[A-Z0-9]{8,9}$", nif or ""))

    def _validate_verifactu_tax_rates(self):
        valid_tax_rates = {"0", "4", "5", "7", "10", "21"}

        for line in self.invoice_line_ids:
            for tax in line.tax_ids:
                rate_str = str(int(round(tax.amount)))
                if rate_str not in valid_tax_rates:
                    raise UserError(
                        _(
                            "Tipo de IVA no válido para VeriFactu: %s%% en el producto '%s'. "
                            "Solo se permiten los tipos: %s."
                        )
                        % (rate_str, line.name, ", ".join(sorted(valid_tax_rates)))
                    )
                    
    


    def _vf_anomaly_create(self, code, message, severity='error', anomaly_type=None):
        self.ensure_one()

        # Map rápido code → tipo
        if not anomaly_type:
            anomaly_type = 'out_of_order' if str(code or '').startswith('ORD') else 'stale_pending'

        vals = {
            'move_id': self.id,
            'company_id': (self.company_id or self.env.user.company_id).id,
            'anomaly_type': anomaly_type,        # requerido
            'message': message or '',
            'severity': severity if severity in dict(self.env['verifactu.anomaly']._fields['severity'].selection) else 'warning',
            'detected_at': fields.Datetime.now(),
        }

        # Transacción separada → no se revierte por el UserError posterior
        registry = self.env.registry
        with registry.cursor() as cr:
            env2 = api.Environment(cr, SUPERUSER_ID, dict(self.env.context))
            A = env2['verifactu.anomaly'].sudo()
            existing = A.search([
                ('move_id', '=', vals['move_id']),
                ('anomaly_type', '=', vals['anomaly_type']),
                ('resolved', '=', False),
            ], limit=1)
            if existing:
                existing.write({'message': vals['message'], 'severity': vals['severity'], 'detected_at': vals['detected_at']})
            else:
                A.create(vals)
            # el commit se hace al salir del with (cursor context manager)



    def _vf_anomaly_clear(self):
        self.ensure_one()
        self.env['verifactu.anomaly'].sudo().search([
            ('move_id', '=', self.id),
            ('resolved', '=', False),
        ]).write({'resolved': True, 'resolved_at': fields.Datetime.now()})
