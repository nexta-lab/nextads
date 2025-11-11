# -*- coding: utf-8 -*-
import xml.etree.ElementTree as ET
import logging
import requests
import re
import sys
import base64

from odoo.exceptions import UserError
from odoo import _, fields

from ..utils.cert_handler import VerifactuCertHandler
from ..utils.invoice_type_resolve import VerifactuTipoFacturaResolver  # opcional

_logger = logging.getLogger(__name__)

# Referencia oficial:
# https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/errores.properties

# Incluye errores internos AEAT (20000–20999)
REJECTION_ERROR_CODES = set(
    list(range(1100, 1300))      # Validaciones de factura
    + list(range(4102, 4141))    # Duplicados, estructura, etc.
    + list(range(20000, 21000))  # Errores internos AEAT (SOAP Fault)
    + [3001, 3002, 3003, 3004]   # Certificados, firma, WS
)
ACCEPTED_WITH_ERRORS_CODES = set(list(range(2000, 2009)) + [3000])

PY2 = sys.version_info[0] == 2


def _u(x):
    """Devuelve unicode (Py2) o str (Py3) a partir de bytes/str con fallback latin-1."""
    if x is None:
        return u'' if PY2 else ''
    if PY2:
        try:
            unicode_type = unicode  # noqa
        except NameError:
            unicode_type = type(u'')
        if isinstance(x, unicode_type):
            return x
        if isinstance(x, bytes):
            for enc in ('utf-8', 'latin-1'):
                try:
                    return x.decode(enc)
                except Exception:
                    pass
            return unicode_type(repr(x))
        try:
            return unicode_type(x)
        except Exception:
            return unicode_type(repr(x))
    else:
        if isinstance(x, bytes):
            for enc in ('utf-8', 'latin-1'):
                try:
                    return x.decode(enc)
                except Exception:
                    pass
            return str(x)
        return str(x)


def _bytes(x):
    if x is None:
        return b""
    if isinstance(x, (bytes, bytearray)):
        return bytes(x)
    return _u(x).encode('utf-8')


# --- Helper base64 seguro para ir.attachment.datas ---
def _to_b64_text(payload, encoding="utf-8"):
    """
    Convierte payload (str|bytes|otro) a texto base64 (str ASCII) para ir.attachment.datas.
    """
    if payload is None:
        raw = b""
    elif isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    elif isinstance(payload, str):
        raw = payload.encode(encoding)
    else:
        raw = str(payload).encode(encoding)
    return base64.b64encode(raw).decode("ascii")


def _looks_like_html_error(resp, text_low_first200):
    """
    Devuelve True si la respuesta parece ser una página HTML (front de Sede/Proxy)
    o un 5xx (p.ej. 503), que debemos tratar como incidencia AEAT (no como error funcional).
    """
    try:
        sc = getattr(resp, 'status_code', None)
        ctype = (resp.headers.get('Content-Type', '') if hasattr(resp, 'headers') else '').lower()
    except Exception:
        sc = None
        ctype = ''
    is_5xx = (sc is not None and int(sc) >= 500)
    is_html = ('text/html' in ctype) or ('<!doctype html' in text_low_first200) or ('<html' in text_low_first200)
    return bool(is_5xx or is_html)


class VerifactuSender(object):
    def __init__(self, invoice):
        self.invoice = invoice

    # -------------------------
    # Helpers snapshot (compat 10→18)
    # -------------------------
    def _clean_es_nif(self, v):
        v = (v or '').upper()
        v = ''.join(ch for ch in v if ch.isalnum())
        if v.startswith('ES'):
            v = v[2:]
        return v

    def _compute_tipo_factura_now(self, inv):
        try:
            return VerifactuTipoFacturaResolver.resolve(inv)
        except Exception:
            mt = getattr(inv, 'move_type', None) or getattr(inv, 'type', None) or ''
            return 'R1' if 'refund' in (mt or '') else 'F1'

    def _get_invoice_name(self, inv):
        return getattr(inv, 'name', None) or getattr(inv, 'number', None) or ''

    def _get_invoice_date(self, inv):
        return getattr(inv, 'invoice_date', None) or getattr(inv, 'date_invoice', None) or getattr(inv, 'date', None) or False

    def _current_idfactu_tuple(self, inv):
        emisor_nif = self._clean_es_nif(getattr(inv.company_id, 'vat', '') or '')
        return (emisor_nif, self._get_invoice_name(inv), self._get_invoice_date(inv), self._compute_tipo_factura_now(inv))

    def _last_idfactu_tuple(self, inv):
        return (
            getattr(inv, 'verifactu_last_emisor_nif', '') or '',
            getattr(inv, 'verifactu_last_numero', '') or '',
            getattr(inv, 'verifactu_last_fecha', False) or False,
            getattr(inv, 'verifactu_last_tipo', '') or '',
        )

    def _save_snapshot_after_send(self, inv):
        emisor, num, fecha, tipo = self._current_idfactu_tuple(inv)
        inv.sudo().write({
            'verifactu_last_emisor_nif': emisor,
            'verifactu_last_numero': num,
            'verifactu_last_fecha': fecha,
            'verifactu_last_tipo': tipo,
        })

    def _preflight_reset_if_idfactu_changed(self, inv):
        """Si cambió el IDFactura respecto al último snapshot, resetea flags para forzar envío como nuevo."""
        last = self._last_idfactu_tuple(inv)
        curr = self._current_idfactu_tuple(inv)
        if last == ('', '', False, ''):
            return
        if curr != last:
            inv.sudo().write({
                'verifactu_sent': False,
                'verifactu_sent_with_errors': False,
                'verifactu_processed': False,
                'verifactu_status': 'draft',
            })

    # -------------------------
    # Envío
    # -------------------------
    def send(self, signed_xml_str, attachment):
        invoice = self.invoice
        company = invoice.company_id

        endpoint_config = invoice.env["verifactu.endpoint.config"].search([
            ("company_id", "=", company.id)
        ], limit=1)

        if (not endpoint_config) or (not endpoint_config.endpoint_url):
            msg = _("⚠️ Endpoint no configurado. Se ha generado el archivo, pero no se ha podido enviar.")
            self._post_message(msg, attachment)
            invoice.verifactu_sent = False
            invoice.verifactu_sent_with_errors = False
            invoice.verifactu_processed = False
            invoice.verifactu_status = "error"
            return signed_xml_str

        try:
            # Preflight: si el IDFactura cambió, resetea flags aquí (sin hooks)
            try:
                self._preflight_reset_if_idfactu_changed(invoice)
            except Exception:
                pass

            # Preparar payload (si es str → bytes utf-8)
            payload = signed_xml_str if isinstance(signed_xml_str, (bytes, bytearray)) else signed_xml_str.encode("utf-8")

            # --- NUEVO: actualiza el log antes de enviar ---
            try:
                invoice.verifactu_soap_xml = signed_xml_str
                if hasattr(invoice, "_log_verifactu_status"):
                    invoice._log_verifactu_status(
                        "hash_generated",
                        notes=_("🧾 XML SOAP firmado y almacenado correctamente."),
                        update_if_exists=True,
                    )
            except Exception as e:
                _logger.warning("[VeriFactu] No se pudo actualizar el log con el XML firmado: %s", e)

            with VerifactuCertHandler(endpoint_config.cert_pfx, endpoint_config.cert_password) as cert_handler:
                response = requests.post(
                    endpoint_config.endpoint_url,
                    data=payload,
                    headers={"Content-Type": "application/xml; charset=utf-8"},
                    cert=(cert_handler.cert_path, cert_handler.key_path),
                    timeout=30
                )

            # >>> NUEVO: detección temprana de 5xx/HTML (ej. 503 Sede)
            response_bytes = getattr(response, 'content', b'') or b''
            response_text = _u(response_bytes)
            low_200 = response_text[:200].lower()

            if _looks_like_html_error(response, low_200):
                # Log útil
                _logger.warning(
                    "[VeriFactu] Incidencia AEAT: HTTP %s, Content-Type=%s. Inicio cuerpo: %s",
                    getattr(response, 'status_code', '?'),
                    (response.headers.get('Content-Type', '') if hasattr(response, 'headers') else ''),
                    response_text[:120].replace('\n', ' ')
                )

                # Mensaje claro al usuario
                msg = _("🟠 Incidencia en AEAT (HTTP %s). Servicio temporalmente no disponible. "
                        "Tu envío NO se ha validado todavía. Se reintentará más tarde.")
                self._post_message(msg % getattr(response, 'status_code', '?'),
                                   attachment, detailed_error=response_text)

                # Estado consistente para reintentos
                invoice.verifactu_sent = False
                invoice.verifactu_sent_with_errors = False
                invoice.verifactu_processed = False
                invoice.verifactu_status = "error"  # o "pending_retry" si tienes ese estado
                invoice._log_verifactu_status("error", code, update_if_exists=True)


                # Adjuntamos como HTML para diagnóstico
                try:
                    att_vals = {
                        'name': (self._get_invoice_name(invoice) or 'respuesta_aeat') + '.html',
                        'datas': _to_b64_text(response_bytes),
                        'datas_fname': 'respuesta_aeat.html',
                        'res_model': invoice._name,
                        'res_id': invoice.id,
                        'mimetype': 'text/html',
                    }
                    invoice.env['ir.attachment'].sudo().create(att_vals)
                except Exception:
                    _logger.exception("No se pudo adjuntar la respuesta AEAT como HTML.")

                # Salimos sin parsear como SOAP
                return signed_xml_str

            # Preferir .content (bytes) para decodificar a gusto (si no era HTML/5xx)
            # (ya tenemos response_text del bloque anterior)
            if getattr(response, 'status_code', 200) >= 400:
                _logger.warning("[VeriFactu] HTTP %s en envío: %s", response.status_code, (response_text or '')[:300])

            # Parse estructurado
            res = self.parse_response(response_text)
            summary = res.get("summary")
            detail = res.get("detail")
            code = res.get("code") 
            status = res.get("status")
            now = fields.Datetime.now()

            # Postear al chatter + guardar detalle largo
            self._post_message(summary, attachment, detailed_error=detail)

            # Actualiza estados
            if status == "sent":
                invoice.verifactu_sent = True
                invoice.verifactu_sent_with_errors = False
                invoice.verifactu_processed = False
                invoice.verifactu_status = "sent"
                invoice.verifactu_date_sent = now
                invoice._log_verifactu_status("sent", code, update_if_exists=True)
                try:
                    self._save_snapshot_after_send(invoice)
                except Exception:
                    pass

            elif status == "accepted_with_errors":
                invoice.verifactu_sent = False
                invoice.verifactu_sent_with_errors = True
                invoice.verifactu_processed = False
                invoice.verifactu_status = "accepted_with_errors"
                invoice.verifactu_date_sent = now
                invoice._log_verifactu_status("accepted_with_errors", code, update_if_exists=True)

                try:
                    self._save_snapshot_after_send(invoice)
                except Exception:
                    pass

            elif status == "canceled":
                invoice.verifactu_sent = True
                invoice.verifactu_sent_with_errors = False
                invoice.verifactu_processed = False
                invoice.verifactu_status = "canceled"
                invoice.verifactu_date_sent = now
                invoice._log_verifactu_status("canceled", code, update_if_exists=True)

            else:  # "error" u otros
                invoice.verifactu_sent = False
                invoice.verifactu_sent_with_errors = False
                invoice.verifactu_processed = False
                invoice.verifactu_status = "error"
                invoice._log_verifactu_status("error", code, update_if_exists=True)

                # Adjuntar respuesta AEAT completa como .xml para diagnóstico (Py3-safe)
                try:
                    att_vals = {
                        'name': (self._get_invoice_name(invoice) or 'respuesta_aeat') + '.xml',
                        'datas': _to_b64_text(response_text),
                        'datas_fname': 'respuesta_aeat.xml',
                        'res_model': invoice._name,
                        'res_id': invoice.id,
                        'mimetype': 'application/xml',
                    }
                    invoice.env['ir.attachment'].sudo().create(att_vals)
                except Exception:
                    _logger.exception("No se pudo adjuntar la respuesta AEAT como XML.")

            return signed_xml_str

        except requests.exceptions.RequestException as e:
            # FALLO DE TRANSPORTE: no hubo SOAP válido en AEAT
            error_text = _u(str(e))
            self._post_message(_("🛑 Error de transporte al contactar con VeriFactu: %s") % error_text,
                               attachment, detailed_error=error_text)
            invoice.verifactu_sent = False
            invoice.verifactu_sent_with_errors = False
            invoice.verifactu_processed = False
            invoice.verifactu_status = "error"
            invoice._log_verifactu_status("error", code, update_if_exists=True)
            raise UserError(_("🛑 No se pudo contactar con VeriFactu. Reintenta o revisa la configuración."))

    # -------------------------
    # Parser de respuesta (generalista)
    # -------------------------
    def parse_response(self, response_text):
        """
        Devuelve dict: {status, summary, detail, code?}
        - status ∈ {'sent', 'accepted_with_errors', 'canceled', 'error'}
        """
        txt = _u(response_text or "")
        low = txt.lower()

        # Guardarraíl adicional por si llega HTML hasta aquí (no debería con el early check)
        if low.lstrip().startswith('<!doctype html') or '<html' in low[:200]:
            return {
                "status": "error",
                "summary": _("🟠 Respuesta HTML de AEAT (no SOAP). Incidencia de disponibilidad."),
                "code": None,
                "detail": txt
            }

        env = {
            'env':  'http://schemas.xmlsoap.org/soap/envelope/',
            'tikR': 'https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/RespuestaSuministro.xsd',
            'tik':  'https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd',
        }

        code = None
        desc_error = ""

        try:
            root = ET.fromstring(_bytes(txt))

            # 1) Fault SOAP
            fault = root.find('.//env:Fault/env:faultstring', env)
            if fault is not None and fault.text:
                m = re.search(r"\b(\d{4,5})\b", fault.text)  # acepta 4 o 5 dígitos
                code = int(m.group(1)) if m else None
                return {
                    "status": "error",
                    "summary": _("🛑 Error SOAP: %s") % _u(fault.text),
                    "code": code,
                    "detail": txt
                }

            nodo_resp = root.find('.//tikR:RespuestaRegFactuSistemaFacturacion', env)
            if nodo_resp is None:
                # No está el nodo esperado → heurística textual
                raise ValueError("Respuesta sin nodo RespuestaRegFactuSistemaFacturacion")

            estado_envio = (nodo_resp.findtext('.//tikR:EstadoEnvio', default='', namespaces=env) or '').strip()

            linea = nodo_resp.find('.//tikR:RespuestaLinea', env)
            # En algunos casos puede no haber línea, evitamos crash
            estado_registro = (linea.findtext('.//tikR:EstadoRegistro', default='', namespaces=env) or '').strip() if linea is not None else ''
            code_text = (linea.findtext('.//tikR:CodigoErrorRegistro', default='', namespaces=env) or '').strip() if linea is not None else ''
            code = int(code_text) if code_text.isdigit() else None
            desc_error = (linea.findtext('.//tikR:DescripcionErrorRegistro', default='', namespaces=env) or '').strip() if linea is not None else ''

            # >>> NUEVO: leer el tipo de operación (Alta / Anulacion / Subsanacion…)
            tipo_oper = (linea.findtext('.//tik:TipoOperacion', default='', namespaces=env) or '').strip() if linea is not None else ''
            display = (getattr(self.invoice, 'name', None) or getattr(self.invoice, 'number', None) or '???')

            # 2) Clasificación explícita por tipo de operación
            if tipo_oper.lower() == 'anulacion':
                # Si además llega "Correcto", aún más claro, pero marcamos igual como 'canceled'
                summary = _("🗑️ Factura %s anulada correctamente en VeriFactu.") % display
                return {"status": "canceled", "summary": summary, "code": None, "detail": None}

            # 3) Ramas estándar
            if (estado_registro.lower().startswith('aceptado') and 'error' in estado_registro.lower()) \
            or (estado_envio.lower() == 'parcialmentecorrecto') \
            or (code in ACCEPTED_WITH_ERRORS_CODES if code is not None else False):
                desc_short = (desc_error[:180] + u"…") if desc_error and len(desc_error) > 200 else (desc_error or "")
                summary = _("⚠️ Factura %s aceptada con errores%s: %s") % (
                    display, (" (%s)" % code) if code else "", desc_short or _("ver detalle")
                )
                detail = u"\n".join([
                    u"— Respuesta completa AEAT —",
                    txt or _(u"(vacía)"),
                ])
                return {"status": "accepted_with_errors", "summary": summary, "code": code, "detail": detail}

            if estado_registro.lower() == 'correcto' or 'correcto' in low:
                summary = _("✅ Factura %s enviada correctamente a VeriFactu.") % display
                return {"status": "sent", "summary": summary, "code": None, "detail": None}

            # 4) Si llegamos aquí y hay código → error
            desc_short = (desc_error[:180] + u"…") if desc_error and len(desc_error) > 200 else (desc_error or "")
            summary = _("🛑 Error VeriFactu%s: %s") % (
                (" (%s)" % code) if code else "", desc_short or _("ver detalle")
            )
            detail = u"\n".join([
                _(u"Código %s") % code if code else "",
                u"\n— Respuesta completa AEAT —",
                txt or _(u"(vacía)"),
            ]).strip()
            return {"status": "error", "summary": summary, "code": code, "detail": detail}

        except Exception:
            # Fallback por texto (por si el XML viene raro)
            display = (getattr(self.invoice, 'name', None) or getattr(self.invoice, 'number', None) or '???')

            if any(w in low for w in (u"anulacion", u"anulación", u"anulada", u"anulado")):
                return {"status": "canceled",
                        "summary": _("🗑️ Factura %s anulada correctamente en VeriFactu.") % display,
                        "code": None, "detail": txt}

            code = self._extract_error_code(txt)
            if (u"aceptado" in low and u"error" in low) or (u"aceptada" in low and u"error" in low) \
            or (code in ACCEPTED_WITH_ERRORS_CODES if code is not None else False):
                summary = _("⚠️ Factura %s aceptada con errores%s: %s") % (
                    display, (" (%s)" % code) if code else "", _("ver detalle")
                )
                detail = u"\n".join([
                    u"— Respuesta completa AEAT —",
                    txt or _(u"(vacía)"),
                ])
                return {"status": "accepted_with_errors", "summary": summary, "code": code, "detail": detail}

            if u"correcto" in low:
                return {"status": "sent",
                        "summary": _("✅ Factura %s enviada correctamente a VeriFactu.") % display,
                        "code": None, "detail": None}

            code = self._extract_error_code(txt)
            # Construir descripción corta a partir del texto si hay pista clara
            desc_match = re.search(r"Error[^.:]{0,80}", txt, re.IGNORECASE)
            desc_short = (desc_match.group(0).strip() if desc_match else "")[:120]

            # Clasificación heurística para mensaje más útil
            if code and 20000 <= code < 21000:
                summary = _("🟠 Incidencia temporal en los servidores de la AEAT (código %s). "
                            "Tu envío no ha sido procesado. Se recomienda reintentarlo más tarde.") % code
            elif code and 3000 <= code < 4000:
                summary = _("⚙️ Error técnico en la comunicación con AEAT (código %s). "
                            "Revisa el certificado o la conexión.") % code
            elif code and 1100 <= code < 1300:
                summary = _("🛑 Error de validación en la factura (código %s). "
                            "Revisa los datos de emisor, destinatario o impuestos.") % code
            else:
                summary = _("🛑 Error al enviar la factura a VeriFactu%s. %s") % (
                    (" (código %s)" % code) if code else "",
                    desc_short or _("Consulta el detalle."),
                )

            return {
                "status": "error",
                "summary": summary,
                "code": code,
                "detail": txt or _("Respuesta vacía de VeriFactu.")
}


    # -------------------------
    # Extractores auxiliares
    # -------------------------
    
    def _extract_error_code(self, xml_text):
        """
        Busca un código de error numérico relevante en el texto SOAP o plano.

        Detecta códigos AEAT típicos:
        - 1100–1299 → validaciones de factura
        - 20000–20999 → errores internos del servidor AEAT
        - 3000–3999 → fallos técnicos, firma o WS
        - 4100–4199 → duplicados, estructura XML, etc.
        """
        try:
            txt = _u(xml_text or "")
            # Captura números de 3 a 5 dígitos dentro de corchetes, paréntesis o texto
            # Ejemplos válidos: Codigo[20009], Código 4102, Error 3001
            m = re.search(r"\b(1[01]\d{2}|2\d{4}|3\d{3}|4[01]\d{2})\b", txt)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return None


    # -------------------------
    # Mensajería
    # -------------------------
    def _post_message(self, message, attachment, detailed_error=None):
        """
        Postea en el chatter (con/ sin adjunto) y guarda el detalle largo en verifactu_detailed_error_msg.
        Compatible v10→18.
        """
        msg_txt = _u(message or u'')
        # Evita duplicados exactos (mismo body + mismo adjunto si existe)
        try:
            already_posted = self.invoice.message_ids.filtered(
                lambda m: (m.body == msg_txt) and attachment and (attachment.id in m.attachment_ids.ids)
            )
        except Exception:
            already_posted = self.invoice.message_ids.filtered(lambda m: (m.body == msg_txt))

        if not already_posted:
            # 1) Intento moderno: attachment_ids (M2M ids)
            try:
                if attachment and hasattr(attachment, 'id'):
                    self.invoice.message_post(body=msg_txt, message_type="comment", attachment_ids=[attachment.id])
                else:
                    self.invoice.message_post(body=msg_txt, message_type="comment")
            except Exception:
                # 2) Fallback v10: attachments=[(name, data)]
                try:
                    if attachment and getattr(attachment, 'datas', False):
                        self.invoice.message_post(
                            body=msg_txt,
                            message_type="comment",
                            attachments=[(attachment.name or 'respuesta.xml', attachment.datas)]
                        )
                    else:
                        self.invoice.message_post(body=msg_txt, message_type="comment")
                except Exception:
                    # Último recurso: solo body
                    self.invoice.message_post(body=msg_txt)

        # Guarda detalle largo (último error) si cambia
        if detailed_error and (getattr(self.invoice, "verifactu_detailed_error_msg", None) != _u(detailed_error)):
            try:
                self.invoice.with_context(check_move_validity=False).sudo().write({
                    "verifactu_detailed_error_msg": _u(detailed_error)
                })
            except Exception:
                pass
