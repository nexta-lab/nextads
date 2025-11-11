# -*- coding: utf-8 -*-
import hashlib
import logging
from datetime import datetime as _dt, date as _date, time as _time, timedelta
import pytz
import re

from odoo import models, fields, api, _
from odoo.fields import Datetime as _FieldsDatetime

from ..utils.invoice_type_resolve import VerifactuTipoFacturaResolver
from ..utils.verifactu_xml_validator import VerifactuXMLValidator  # NIF de company_id

logger = logging.getLogger(__name__)

# --------- Compat Py2/Py3 + helpers comunes ---------
try:
    basestring
except NameError:
    basestring = (str,)

_HEX64 = re.compile(r"^[0-9A-Fa-f]{64}$")


def _to_bytes(x, encoding="utf-8"):
    if x is None:
        return b""
    if isinstance(x, bytes):
        return x
    return (x if isinstance(x, basestring) else str(x)).encode(encoding)


def _to_text(x, encoding="utf-8"):
    if x is None:
        return u""
    if isinstance(x, bytes):
        return x.decode(encoding)
    return x if isinstance(x, basestring) else str(x)


def _to_datetime(v):
    """Acepta datetime/date/str y devuelve datetime (naive, UTC) o None."""
    if not v:
        return None
    if isinstance(v, _dt):
        return v
    if isinstance(v, _date):
        return _dt.combine(v, _time.min)
    if isinstance(v, basestring):
        try:
            return fields.Datetime.from_string(v)
        except Exception:
            try:
                return _dt.strptime(v[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    return _dt.strptime(v[:10], "%Y-%m-%d")
                except Exception:
                    return None
    return None


def _to_date(v):
    """Acepta date/datetime/str y devuelve date o None."""
    if not v:
        return None
    if isinstance(v, _date) and not isinstance(v, _dt):
        return v
    dt = _to_datetime(v)
    return dt.date() if dt else None


def _format_ddmmyyyy(v):
    d = _to_date(v)
    return d.strftime("%d-%m-%Y") if d else ""


def _safe_str(v):
    if isinstance(v, basestring):
        return (v or "").strip()
    return (str(v).strip() if v is not None else "")


def _safe_hash_str(v):
    """
    Devuelve la huella HEX64 si lo parece; en cualquier otro caso, ''.
    Evita que bool False/True o basura acaben como 'False'/'True'.
    """
    if not v or isinstance(v, bool):
        return ""
    s = v.strip() if isinstance(v, basestring) else str(v).strip()
    return s if _HEX64.match(s) else ""


def _fmt_amount(inv, amount):
    """Redondea con currency si existe; 2 decimales por defecto."""
    amt = amount or 0.0
    cur = getattr(inv, 'currency_id', None)
    try:
        if cur:
            try:
                amt = cur.round(amt)
            except Exception:
                amt = round(amt, 2)
        else:
            amt = round(amt, 2)
    except Exception:
        amt = round(amt, 2)
    return "%.2f" % amt


def _has_model(env, model_name):
    try:
        env[model_name]
        return True
    except Exception:
        return False


def _invoice_model(env):
    return 'account.move' if _has_model(env, 'account.move') else 'account.invoice'


def _invoice_date_get(inv):
    if hasattr(inv, 'invoice_date') and getattr(inv, 'invoice_date'):
        return getattr(inv, 'invoice_date')
    if hasattr(inv, 'date_invoice') and getattr(inv, 'date_invoice'):
        return getattr(inv, 'date_invoice')
    if hasattr(inv, 'date') and getattr(inv, 'date'):
        return getattr(inv, 'date')
    return None


def _iso_with_tz(env, dt_utc=None):
    """
    Devuelve ISO8601 con huso: YYYY-MM-DDTHH:MM:SS+HH:MM
    Usa timezone del usuario si existe; si no, intenta Europe/Madrid; por último UTC.
    Esto reduce discrepancias con AEAT cuando el usuario no tiene TZ configurada.
    """
    dt = _to_datetime(dt_utc) or _to_datetime(fields.Datetime.now())
    if dt and dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    else:
        dt = dt.astimezone(pytz.utc)

    tzname = _safe_str(getattr(env.user, 'tz', '')) or 'Europe/Madrid'
    try:
        tz = pytz.timezone(tzname)
    except Exception:
        try:
            tz = pytz.timezone('Europe/Madrid')
        except Exception:
            tz = pytz.utc

    local = dt.astimezone(tz)
    offset = local.utcoffset() or timedelta(0)
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hh = total_seconds // 3600
    mm = (total_seconds % 3600) // 60
    return local.strftime("%Y-%m-%dT%H:%M:%S") + ("%s%02d:%02d" % (sign, hh, mm))


# ===================================================

NO_FINGERPRINT = ""  # Sin token cuando no hay encadenamiento previo


class VerifactuHashCalculator:
    def __init__(self, invoice, config):
        self.invoice = invoice
        self.config = config

    # --------------------------------------
    # Huella de Alta (RegistroAlta)
    # --------------------------------------
    def compute_hash(self):
        invoice = self.invoice
        invoice.ensure_one()

        company = invoice.company_id
        company_vat_raw = _safe_str(getattr(company, 'vat', None))
        nif = VerifactuXMLValidator.clean_nif_es(company_vat_raw) if company_vat_raw else ""

        invoice_number = _safe_str(getattr(invoice, 'name', "") or getattr(invoice, 'number', ""))
        invoice_date_val = _invoice_date_get(invoice)
        invoice_date = _format_ddmmyyyy(invoice_date_val)

        tipo_factura = VerifactuTipoFacturaResolver.resolve(invoice)
        cuota_total = _fmt_amount(invoice, getattr(invoice, 'amount_tax', 0.0))
        importe_total = _fmt_amount(invoice, getattr(invoice, 'amount_total', 0.0))

        prev = _safe_hash_str(getattr(invoice, 'verifactu_previous_hash', ""))
        previous_token = prev or NO_FINGERPRINT

        ts_saved = getattr(invoice, 'verifactu_hash_calculated_at', None)
        timestamp_str = _iso_with_tz(invoice.env, ts_saved)

        parts = [
            "IDEmisorFactura=" + nif,
            "NumSerieFactura=" + invoice_number,
            "FechaExpedicionFactura=" + invoice_date,
            "TipoFactura=" + _safe_str(tipo_factura),
            "CuotaTotal=" + cuota_total,
            "ImporteTotal=" + importe_total,
            "Huella=" + previous_token,
            "FechaHoraHusoGenRegistro=" + timestamp_str,
        ]
        base_string = "&".join(parts)
        logger.info("[VeriFactu] Base para hash (alta): %s", base_string)

        return hashlib.sha256(base_string.encode("utf-8")).hexdigest().upper()

    # --------------------------------------
    # Cálculo + encadenamiento
    # --------------------------------------
    def compute_and_update(self, force_recalculate=False):
        invoice = self.invoice
        invoice.ensure_one()

        # Asegura fecha si falta
        inv_date = _invoice_date_get(invoice)
        if not inv_date:
            today = fields.Date.today()
            if hasattr(invoice, 'invoice_date'):
                invoice.invoice_date = today
            elif hasattr(invoice, 'date_invoice'):
                invoice.date_invoice = today
            elif hasattr(invoice, 'date'):
                invoice.date = today
            try:
                invoice.message_post(body=u"⚠️ Fecha de factura no definida. Se ha asignado la fecha de hoy.")
            except Exception:
                pass

        # === NUEVO: intentar usar hash previo desde log ===
        prev_log = invoice.env["verifactu.status.log"].search([
            ("invoice_id", "=", invoice.id),
            ("hash_actual", "!=", False)
        ], order="date desc, id desc", limit=1)

        if prev_log:
            prev_hash = _safe_hash_str(prev_log.hash_actual)
            invoice.verifactu_previous_hash = prev_hash
            try:
                invoice.message_post(body=u"🔗 Hash anterior tomado del histórico: %s" % prev_hash[:16])
            except Exception:
                pass
        else:
            # Fallback clásico: última factura con hash válido del diario
            model_name = _invoice_model(invoice.env)
            domain = [
                ('id', '!=', invoice.id),
                ('company_id', '=', invoice.company_id.id),
                ('state', '=', 'posted'),
                ('verifactu_hash', '!=', False),
                ('verifactu_hash', '!=', ''),
            ]
            previous_invoice = invoice.env[model_name].search(
                domain, order="{} desc, id desc".format(
                    'invoice_date' if model_name == 'account.move' else 'date_invoice'
                ), limit=1
            )
            if previous_invoice:
                inv_prev_hash = _safe_hash_str(previous_invoice.verifactu_hash)
                if inv_prev_hash:
                    invoice.verifactu_previous_hash = inv_prev_hash
                    try:
                        invoice.message_post(body=u"🔗 Hash anterior asignado: %s" % inv_prev_hash[:16])
                    except Exception:
                        pass
            else:
                try:
                    invoice.message_post(body=u"⚠️ No se ha encontrado factura anterior con hash válido.")
                except Exception:
                    pass

        # ---- Timestamp ----
        now_utc = fields.Datetime.now()
        ts_saved = getattr(invoice, 'verifactu_hash_calculated_at', None)
        if not ts_saved or force_recalculate:
            invoice.verifactu_hash_calculated_at = now_utc
            try:
                pretty = fields.Datetime.context_timestamp(invoice.env.user, _to_datetime(now_utc)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pretty = _safe_str(now_utc)
            try:
                invoice.message_post(body=u"🕓 Timestamp actualizado para hash: %s" % pretty)
            except Exception:
                pass

        # Calcular hash
        new_hash = self.compute_hash()
        current_hash = _safe_hash_str(getattr(invoice, 'verifactu_hash', ""))

        if force_recalculate or not current_hash or current_hash != new_hash:
            invoice.verifactu_hash = new_hash
            try:
                invoice.message_post(body=u"✅ Hash actualizado: %s" % new_hash[:16])
            except Exception:
                pass
        else:
            try:
                invoice.message_post(body=u"ℹ️ Hash ya era correcto: %s" % current_hash[:16])
            except Exception:
                pass

        return new_hash


    # --------------------------------------
    # Huella de Anulación (RegistroAnulacion)
    # --------------------------------------
    def compute_cancellation_hash(self):
        invoice = self.invoice
        invoice.ensure_one()

        company = invoice.company_id
        company_vat_raw = _safe_str(getattr(company, 'vat', None))
        nif = VerifactuXMLValidator.clean_nif_es(company_vat_raw) if company_vat_raw else ""

        # --- Encadenamiento: buscar hash previo ---
        # 1) Preferir el último hash del log si existe
        prev_log = invoice.env["verifactu.status.log"].search([
            ("invoice_id", "=", invoice.id),
            ("hash_actual", "!=", False)
        ], order="date desc, id desc", limit=1)

        if prev_log:
            inv_prev_hash = _safe_hash_str(prev_log.hash_actual)
            invoice.verifactu_previous_hash = inv_prev_hash
            try:
                invoice.message_post(body=u"🔗 Hash anterior (log) asignado: %s" % inv_prev_hash[:16])
            except Exception:
                pass
        else:
            # 2) Fallback: última factura con hash válido (enviada o no)
            model_name = _invoice_model(invoice.env)
            domain = [
                ('id', '!=', invoice.id),
                ('company_id', '=', invoice.company_id.id),
                ('verifactu_hash', '!=', False),
                ('verifactu_hash', '!=', ''),
                # quitamos ('verifactu_date_sent', '!=', False)
            ]
            previous_invoice = invoice.env[model_name].search(
                domain,
                order="{} desc, id desc".format(
                    'invoice_date' if model_name == 'account.move' else 'date_invoice'
                ),
                limit=1
            )
            if previous_invoice:
                inv_prev_hash = _safe_hash_str(previous_invoice.verifactu_hash)
                invoice.verifactu_previous_hash = inv_prev_hash
                try:
                    invoice.message_post(body=u"🔗 Hash anterior asignado: %s" % inv_prev_hash[:16])
                except Exception:
                    pass
            else:
                try:
                    invoice.message_post(body=u"⚠️ No se ha encontrado factura anterior con hash válido.")
                except Exception:
                    pass

        # --- Construcción base para hash de anulación ---
        invoice_number = _safe_str(getattr(invoice, 'name', "") or getattr(invoice, 'number', ""))
        invoice_date_val = _invoice_date_get(invoice)
        invoice_date = _format_ddmmyyyy(invoice_date_val)

        prev = _safe_hash_str(getattr(invoice, 'verifactu_previous_hash', ""))
        previous_token = prev or NO_FINGERPRINT

        ts_saved = getattr(invoice, 'verifactu_hash_calculated_at', None)
        timestamp_str = _iso_with_tz(invoice.env, ts_saved)

        parts = [
            "IDEmisorFacturaAnulada=" + nif,
            "NumSerieFacturaAnulada=" + invoice_number,
            "FechaExpedicionFacturaAnulada=" + invoice_date,
            "Huella=" + previous_token,
            "FechaHoraHusoGenRegistro=" + timestamp_str,
        ]
        base_string = "&".join(parts)
        logger.info("[VeriFactu] Base para hash (anulación): %s", base_string)

        new_hash = hashlib.sha256(base_string.encode("utf-8")).hexdigest().upper()
        invoice.verifactu_hash = new_hash
        return new_hash

