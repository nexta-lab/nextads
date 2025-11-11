# -*- coding: utf-8 -*-
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from lxml import etree as LET
from odoo.tools.translate import _
from odoo.exceptions import UserError

from ...utils.system_info_builder import VerifactuSystemInfoBuilder
from ...services.xml_signer import VerifactuXMLSigner
from ...utils.verifactu_xml_validator import VerifactuXMLValidator

# Helpers alineados con el cálculo de huella (mismo origen que compute_*hash)
from ...services.hash_calculator import _iso_with_tz, _safe_str

# Compat Py2/Py3
try:
    basestring
except NameError:
    basestring = (str,)

# Helpers mínimos de compat bytes/str (si ya los tienes en otro módulo, puedes importarlos allí)
def _to_bytes(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    return (v or u"").encode("utf-8")

def _to_text(v):
    if v is None:
        return u""
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return v.decode("latin-1", "ignore")
    # A partir de aquí: cualquier tipo (Decimal, int, float, etc.) → texto
    try:
        return unicode(v)  # Py2
    except NameError:
        return str(v)       # Py3
    except Exception:
        return str(v)

NS_SUM  = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd"
NS_SUM1 = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"


class VerifactuXMLBuilderAnulacion(object):
    """
    Compatible con Odoo 10 → 18:
    - account.invoice (v10–12) y account.move (v13+)
    - number/name, date_invoice/invoice_date
    - Encadenamiento solo si hay previous_hash (no forzamos 'SINHUELLA')
    - Timestamp alineado con compute_cancellation_hash()
    - Mantiene atributo Id y uso opcional de reference_uri en el signer
    """

    def __init__(self, invoice, config, rechazo_previo=False, sin_Factura_anterior=False):
        self.invoice = invoice
        self.config = config
        self.rechazo_previo = rechazo_previo
        self.sin_Factura_anterior = sin_Factura_anterior

    # ---------------- Compat helpers ----------------

    def _get_invoice_number(self, inv):
        # v10–12: number ; v13+: name
        return (getattr(inv, "number", None) or getattr(inv, "name", u"") or u"").strip()

    def _coerce_date(self, val):
        # Admite date/datetime/str 'YYYY-MM-DD'
        try:
            from datetime import date as ddate, datetime as ddt
            if isinstance(val, ddt):
                return val.date()
            if hasattr(val, "isoformat") and not isinstance(val, basestring):
                return val  # date
            if isinstance(val, basestring):
                return datetime.strptime(val[:10], "%Y-%m-%d").date()
        except Exception:
            pass
        return None

    def _get_invoice_date(self, inv):
        # v10–12: date_invoice ; v13+: invoice_date ; fallback: date
        if getattr(inv, "date_invoice", None):
            return self._coerce_date(inv.date_invoice)
        if getattr(inv, "invoice_date", None):
            return self._coerce_date(inv.invoice_date)
        if getattr(inv, "date", None):
            return self._coerce_date(inv.date)
        return None

    def _format_ddmmyyyy(self, d):
        return d.strftime("%d-%m-%Y") if d else u""

    def _get_current_hash(self, inv):
        return _safe_str(getattr(inv, "verifactu_hash", u""))

    def _get_previous_hash(self, inv):
        # NO forzar 'SINHUELLA' -> evita desalinear base del hash
        return _safe_str(getattr(inv, "verifactu_previous_hash", u""))

    # ---------------- Build ----------------

    def build(self):
        inv = self.invoice
        company = inv.company_id

        # Emisor = compañía
        emisor_nif = VerifactuXMLValidator.clean_nif_es((company.vat or u"").strip()) if company.vat else u""
        if not emisor_nif:
            raise UserError(_("VeriFactu: la compañía no tiene NIF/CIF configurado."))

        invoice_number   = self._get_invoice_number(inv)
        date_invoice_str = self._format_ddmmyyyy(self._get_invoice_date(inv))
        current_hash     = self._get_current_hash(inv)
        previous_hash    = self._get_previous_hash(inv)

        # Nodo firmado: <RegistroAnulacion>
        registro_anulacion = ET.Element(ET.QName(NS_SUM1, "RegistroAnulacion"))
        ET.SubElement(registro_anulacion, ET.QName(NS_SUM1, "IDVersion")).text = "1.0"

        id_factura = ET.SubElement(registro_anulacion, ET.QName(NS_SUM1, "IDFactura"))
        ET.SubElement(id_factura, ET.QName(NS_SUM1, "IDEmisorFacturaAnulada")).text = emisor_nif
        ET.SubElement(id_factura, ET.QName(NS_SUM1, "NumSerieFacturaAnulada")).text = invoice_number
        ET.SubElement(id_factura, ET.QName(NS_SUM1, "FechaExpedicionFacturaAnulada")).text = date_invoice_str

        # Rechazo previo vs Sin registro previo (mutuamente excluyentes)
        if self.rechazo_previo:
            ET.SubElement(registro_anulacion, ET.QName(NS_SUM1, "RechazoPrevio")).text = "S"
        elif self.sin_Factura_anterior:
            ET.SubElement(registro_anulacion, ET.QName(NS_SUM1, "SinRegistroPrevio")).text = "S"

        # Encadenamiento —— SOLO si hay previous_hash (alineado con la base del hash)
        if previous_hash:
            encadenamiento = ET.SubElement(registro_anulacion, ET.QName(NS_SUM1, "Encadenamiento"))
            anterior = ET.SubElement(encadenamiento, ET.QName(NS_SUM1, "RegistroAnterior"))
            ET.SubElement(anterior, ET.QName(NS_SUM1, "IDEmisorFactura")).text = emisor_nif
            ET.SubElement(anterior, ET.QName(NS_SUM1, "NumSerieFactura")).text = invoice_number
            ET.SubElement(anterior, ET.QName(NS_SUM1, "FechaExpedicionFactura")).text = date_invoice_str
            ET.SubElement(anterior, ET.QName(NS_SUM1, "Huella")).text = previous_hash

        # Sistema informático
        VerifactuSystemInfoBuilder(inv.company_id, self.config).append_to(registro_anulacion)

        # Sello tiempo + huella actual —— usar el MISMO timestamp que compute_cancellation_hash()
        ts_str = _iso_with_tz(inv.env, getattr(inv, 'verifactu_hash_calculated_at', None))
        ET.SubElement(registro_anulacion, ET.QName(NS_SUM1, "FechaHoraHusoGenRegistro")).text = ts_str
        ET.SubElement(registro_anulacion, ET.QName(NS_SUM1, "TipoHuella")).text = "01"
        ET.SubElement(registro_anulacion, ET.QName(NS_SUM1, "Huella")).text = current_hash

        # --- Id del elemento firmado + firma ---
        unique_id = "ANU-%s" % ((invoice_number or u"s-n").replace("/", "-"))
        registro_anulacion.set("Id", unique_id)

        raw_anulacion = ET.tostring(registro_anulacion, encoding="utf-8")

        signer = VerifactuXMLSigner(self.config)
        try:
            # Si tu signer acepta reference_uri, úsalo
            signed_str = signer.sign(raw_anulacion, reference_uri="#%s" % unique_id)
        except TypeError:
            # Fallback: firma sin pasar URI
            signed_str = signer.sign(raw_anulacion)

        # Manejo robusto bytes/str
        signed_lxml = LET.fromstring(_to_bytes(signed_str))
        signed_etree = ET.fromstring(_to_bytes(LET.tostring(signed_lxml)))

        # Envolver dentro de <RegistroFactura> como tenías
        registro_factura = ET.Element(ET.QName(NS_SUM, "RegistroFactura"))
        registro_factura.append(signed_etree)

        # Pretty print robusto
        xml_bytes = ET.tostring(registro_factura)
        if not isinstance(xml_bytes, (bytes, bytearray)):
            xml_bytes = _to_bytes(xml_bytes)
        return _to_text(minidom.parseString(xml_bytes).toprettyxml(indent="  "))
