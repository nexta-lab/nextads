# -*- coding: utf-8 -*-
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from itertools import groupby
import logging

from lxml import etree as LET
from odoo.tools.translate import _
from odoo.exceptions import UserError

from ...utils.cert_handler import VerifactuCertHandler
from ...utils.system_info_builder import VerifactuSystemInfoBuilder
from ...utils.invoice_type_resolve import VerifactuTipoFacturaResolver
from ...utils.regime_key import VerifactuRegimeKey
from ...utils.calificacion_operacion import VerifactuOperacionClassifier
from ...services.xml_signer import VerifactuXMLSigner
from ...utils.verifactu_xml_validator import VerifactuXMLValidator

_logger = logging.getLogger(__name__)

NS_SUM  = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd"
NS_SUM1 = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"

# Reutilizar helpers del cálculo de huella (mismos formateos y timestamps)
from ...services.hash_calculator import _iso_with_tz, _safe_str, _fmt_amount

# --- Compat Py2/Py3 ---
try:
    basestring
except NameError:
    basestring = (str,)

# --- Helpers mínimos bytes/str ---
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
    try:
        return unicode(v)  # Py2
    except NameError:
        return str(v)       # Py3
    except Exception:
        return str(v)


class VerifactuXMLBuilderSubsanacion(object):
    """
    Compatible con Odoo 10 → 18:
    - account.invoice (v10–12) y account.move (v13+)
    - number/name, date_invoice/invoice_date
    - invoice_line_tax_ids/tax_ids
    - date_invoice_operation ausente → fallback a fecha de expedición
    """

    def __init__(self, invoice, config, rechazo_previo=False):
        self.invoice = invoice
        self.config = config
        self.rechazo_previo = rechazo_previo

    # ---- Compat helpers -----------------------------------------------------

    def _get_invoice_number(self, inv):
        return (getattr(inv, "number", None) or getattr(inv, "name", u"") or u"").strip()

    def _coerce_date(self, val):
        try:
            from datetime import datetime as dt
            if isinstance(val, dt):
                return val.date()
            if hasattr(val, "isoformat") and not isinstance(val, basestring):
                return val
            if isinstance(val, basestring):
                return datetime.strptime(val[:10], "%Y-%m-%d").date()
        except Exception:
            pass
        return None

    def _get_invoice_date(self, inv):
        if getattr(inv, "date_invoice", None):
            return self._coerce_date(inv.date_invoice)
        if getattr(inv, "invoice_date", None):
            return self._coerce_date(inv.invoice_date)
        if getattr(inv, "date", None):
            return self._coerce_date(inv.date)
        return None

    def _get_operation_date(self, inv):
        val = getattr(inv, "date_invoice_operation", None)
        return self._coerce_date(val) if val else self._get_invoice_date(inv)

    def _format_date(self, dateobj):
        return dateobj.strftime("%d-%m-%Y") if dateobj else u""

    def _get_lines(self, inv):
        return list(getattr(inv, "invoice_line_ids", []))

    def _get_line_taxes(self, line):
        taxes = getattr(line, "invoice_line_tax_ids", None)
        if taxes is None:
            taxes = getattr(line, "tax_ids", [])
        return list(taxes)

    def _get_line_subtotal(self, line):
        return float(getattr(line, "price_subtotal", 0.0) or 0.0)

    def _get_amount_total(self, inv):
        return float(getattr(inv, "amount_total", 0.0) or 0.0)

    def _get_amount_tax(self, inv):
        return float(getattr(inv, "amount_tax", 0.0) or 0.0)

    # ---- Build --------------------------------------------------------------

    def build(self):
        # Validar el PFX antes de empezar (igual que en el builder base)
        with VerifactuCertHandler(self.config.cert_pfx, self.config.cert_password):
            pass

        inv = self.invoice
        company = inv.company_id

        # Emisor
        company_vat_raw = (company.vat or u"").strip()
        company_vat = VerifactuXMLValidator.clean_nif_es(company_vat_raw) if company_vat_raw else u""
        company_name = (company.name or u"").strip()
        if (not company_vat) or (not company_name):
            raise UserError(_("VeriFactu: faltan datos del emisor en la compañía (VAT/NIF y/o nombre)."))

        invoice_number = self._get_invoice_number(inv) or u""
        date_invoice_dt = self._get_invoice_date(inv)
        date_invoice = self._format_date(date_invoice_dt)
        client_name = inv.partner_id.name or u"SINNOMBRE"

        current_hash = getattr(inv, "verifactu_hash", u"") or u""
        previous_hash = _safe_str(getattr(inv, "verifactu_previous_hash", u""))

        clave_regimen = VerifactuRegimeKey.compute_clave_regimen(inv)
        calif_operacion_global = VerifactuOperacionClassifier.compute(inv)
        date_operation_dt = self._get_operation_date(inv)
        _ = self._format_date(date_operation_dt)

        RE_TYPES = {Decimal("5.2"), Decimal("1.4"), Decimal("0.5")}
        base_coste_total = getattr(inv, "verifactu_base_coste", 0.0) or 0.0

        # Raíz
        registro_factura = ET.Element(ET.QName(NS_SUM, "RegistroFactura"))

        # Nodo firmable
        registro_alta = ET.Element(ET.QName(NS_SUM1, "RegistroAlta"))
        ET.SubElement(registro_alta, ET.QName(NS_SUM1, "IDVersion")).text = "1.0"

        id_factura = ET.SubElement(registro_alta, ET.QName(NS_SUM1, "IDFactura"))
        ET.SubElement(id_factura, ET.QName(NS_SUM1, "IDEmisorFactura")).text = company_vat
        ET.SubElement(id_factura, ET.QName(NS_SUM1, "NumSerieFactura")).text = invoice_number
        ET.SubElement(id_factura, ET.QName(NS_SUM1, "FechaExpedicionFactura")).text = date_invoice

        ET.SubElement(registro_alta, ET.QName(NS_SUM1, "NombreRazonEmisor")).text = company_name
        ET.SubElement(registro_alta, ET.QName(NS_SUM1, "Subsanacion")).text = "S"
        if self.rechazo_previo:
            ET.SubElement(registro_alta, ET.QName(NS_SUM1, "RechazoPrevio")).text = "S"

        # Tipo factura
        tipo_factura = VerifactuTipoFacturaResolver.resolve(inv)
        ET.SubElement(registro_alta, ET.QName(NS_SUM1, "TipoFactura")).text = tipo_factura

        # --- Rectificativas ---
        is_refund = self.invoice.is_rectificativa()
        if is_refund:
            # Determina tipo según tu lógica interna (R1–R5)
            tipo_factura = VerifactuTipoFacturaResolver.resolve(inv)
            tipo_rectificativa = VerifactuXMLValidator.infer_tipo_rectificativa(inv)

            # Corrige el valor de TipoRectificativa según AEAT
            tipo_rectificativa = (tipo_rectificativa or "").upper()
            valid_map = {
                "R1": "I",  # Sustitución o error fundado en derecho
                "R2": "S",  # Por diferencias
                "R3": "R",  # Resto de supuestos
                "R4": "O",  # Otros
                "R5": "A",  # Simplificada
            }
            ET.SubElement(registro_alta, ET.QName(NS_SUM1, "TipoRectificativa")).text = valid_map.get(tipo_factura, "S")
            descripcion_operacion = VerifactuXMLValidator.build_descripcion_operacion(inv)
            ET.SubElement(registro_alta, ET.QName(NS_SUM1, "DescripcionOperacion")).text = descripcion_operacion


        # Descripción operación
        if not is_refund:
            descripcion_operacion = VerifactuXMLValidator.build_descripcion_operacion(inv)
            ET.SubElement(registro_alta, ET.QName(NS_SUM1, "DescripcionOperacion")).text = descripcion_operacion

        # ---------------- Destinatario ----------------
        is_simpl = tipo_factura in ("F2", "R5")
        vat = (inv.partner_id.vat or "").strip().upper()

        if is_simpl and not vat:
            # Simplificada SIN identificar → 61.d
            ET.SubElement(registro_alta, ET.QName(NS_SUM1, "FacturaSinIdentifDestinatarioArt61d")).text = "S"
        else:
            # Identificada (incluye F2/R5 con VAT) → construir <Destinatarios>
            destinatarios = ET.SubElement(registro_alta, ET.QName(NS_SUM1, "Destinatarios"))
            id_dest = ET.SubElement(destinatarios, ET.QName(NS_SUM1, "IDDestinatario"))
            ET.SubElement(id_dest, ET.QName(NS_SUM1, "NombreRazon")).text = client_name or "SINNOMBRE"

            idinfo = VerifactuXMLValidator.build_id_for_xml(inv.partner_id)

            if idinfo.get("tag") == "NIF":
                val = (idinfo.get("value") or "").strip()
                if not val:
                    raise UserError(_("VeriFactu: NIF del destinatario vacío."))
                ET.SubElement(id_dest, ET.QName(NS_SUM1, "NIF")).text = val
            else:
                _id = (idinfo.get("ID") or "").strip()
                _type = (idinfo.get("IDType") or "").strip()
                _pais = (idinfo.get("CodigoPais") or "").strip()
                if not (_id and _type and _pais):
                    raise UserError(_("VeriFactu: destinatario extranjero sin ID/IDType/CodigoPais."))
                idotro = ET.SubElement(id_dest, ET.QName(NS_SUM1, "IDOtro"))
                ET.SubElement(idotro, ET.QName(NS_SUM1, "CodigoPais")).text = _pais
                ET.SubElement(idotro, ET.QName(NS_SUM1, "IDType")).text = _type
                ET.SubElement(idotro, ET.QName(NS_SUM1, "ID")).text = _id

        # --- Desglose ---
        desglose = ET.SubElement(registro_alta, ET.QName(NS_SUM1, "Desglose"))

        line_items = []
        for line in self._get_lines(inv):
            calificacion = VerifactuOperacionClassifier.compute_from_line(line)
            for tax in self._get_line_taxes(line):
                line_items.append({
                    "tax": tax,
                    "base": self._get_line_subtotal(line),
                    "calificacion": calificacion,
                })

        line_items.sort(key=lambda x: (x["tax"].id, x["calificacion"]))
        for (tax, calificacion), group in groupby(line_items, key=lambda x: (x["tax"], x["calificacion"])):
            group_list = list(group)
            base_total = sum(item["base"] for item in group_list)

            detalle = ET.SubElement(desglose, ET.QName(NS_SUM1, "DetalleDesglose"))
            ET.SubElement(detalle, ET.QName(NS_SUM1, "ClaveRegimen")).text = clave_regimen
            ET.SubElement(detalle, ET.QName(NS_SUM1, "CalificacionOperacion")).text = calificacion

            if calificacion == "S2":
                ET.SubElement(detalle, ET.QName(NS_SUM1, "OperacionExenta")).text = "E1"

            if calificacion not in ["N1", "N2"]:
                tipo_impositivo = Decimal(str(getattr(tax, "amount", 0.0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                ET.SubElement(detalle, ET.QName(NS_SUM1, "TipoImpositivo")).text = _to_text(tipo_impositivo)

            ET.SubElement(detalle, ET.QName(NS_SUM1, "BaseImponibleOimporteNoSujeto")).text = u"%s" % (
                Decimal(base_total).quantize(Decimal("0.01"))
            )

            if tipo_factura in ("F2", "F3", "R5") and clave_regimen == "06":
                base_coste_proporcional = VerifactuXMLValidator.compute_base_coste_proporcional(
                    inv, base_total, base_coste_total
                )
                ET.SubElement(detalle, ET.QName(NS_SUM1, "BaseImponibleACoste")).text = u"%s" % (
                    Decimal(base_coste_proporcional).quantize(Decimal("0.01"))
                )

            if calificacion not in ["N1", "N2"]:
                cuota = (Decimal(base_total) * Decimal(str(getattr(tax, "amount", 0.0))) / Decimal("100")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                ET.SubElement(detalle, ET.QName(NS_SUM1, "CuotaRepercutida")).text = _to_text(cuota)

            try:
                tax_pct = Decimal(str(getattr(tax, "amount", 0.0))).quantize(Decimal("0.01"))
            except Exception:
                tax_pct = Decimal("0.00")
            if tax_pct in RE_TYPES:
                ET.SubElement(detalle, ET.QName(NS_SUM1, "TipoRecargoEquivalencia")).text = _to_text(tax_pct)
                cuota_recargo = (Decimal(base_total) * tax_pct / Decimal("100")).quantize(Decimal("0.01"))
                ET.SubElement(detalle, ET.QName(NS_SUM1, "CuotaRecargoEquivalencia")).text = _to_text(cuota_recargo)

        # Sin impuestos
        line_items_no_tax = []
        for line in self._get_lines(inv):
            if not self._get_line_taxes(line):
                line_items_no_tax.append({
                    "base": self._get_line_subtotal(line),
                    "calificacion": VerifactuOperacionClassifier.compute_from_line(line),
                })

        for calificacion, group in groupby(sorted(line_items_no_tax, key=lambda x: x["calificacion"]), key=lambda x: x["calificacion"]):
            group_list = list(group)
            base_total = sum(item["base"] for item in group_list)
            detalle = ET.SubElement(desglose, ET.QName(NS_SUM1, "DetalleDesglose"))
            ET.SubElement(detalle, ET.QName(NS_SUM1, "ClaveRegimen")).text = clave_regimen
            ET.SubElement(detalle, ET.QName(NS_SUM1, "CalificacionOperacion")).text = calificacion
            if calificacion == "S2":
                ET.SubElement(detalle, ET.QName(NS_SUM1, "OperacionExenta")).text = "E1"
            ET.SubElement(detalle, ET.QName(NS_SUM1, "BaseImponibleOimporteNoSujeto")).text = u"%s" % (
                Decimal(base_total).quantize(Decimal("0.01"))
            )
            if calificacion not in ["N1", "N2"]:
                ET.SubElement(detalle, ET.QName(NS_SUM1, "TipoImpositivo")).text = "0.00"
                ET.SubElement(detalle, ET.QName(NS_SUM1, "CuotaRepercutida")).text = "0.00"

        # Totales — usa _fmt_amount para alinear con compute_hash()
        ET.SubElement(registro_alta, ET.QName(NS_SUM1, "CuotaTotal")).text = _fmt_amount(inv, self._get_amount_tax(inv))
        ET.SubElement(registro_alta, ET.QName(NS_SUM1, "ImporteTotal")).text = _fmt_amount(inv, self._get_amount_total(inv))

        # Encadenamiento — coherente con el builder base
        encadenamiento = ET.SubElement(registro_alta, ET.QName(NS_SUM1, "Encadenamiento"))
        if previous_hash:
            anterior = ET.SubElement(encadenamiento, ET.QName(NS_SUM1, "RegistroAnterior"))
            ET.SubElement(anterior, ET.QName(NS_SUM1, "IDEmisorFactura")).text = company_vat
            ET.SubElement(anterior, ET.QName(NS_SUM1, "NumSerieFactura")).text = invoice_number
            ET.SubElement(anterior, ET.QName(NS_SUM1, "FechaExpedicionFactura")).text = date_invoice
            ET.SubElement(anterior, ET.QName(NS_SUM1, "Huella")).text = previous_hash
        else:
            ET.SubElement(encadenamiento, ET.QName(NS_SUM1, "PrimerRegistro")).text = "S"

        # Información del sistema
        VerifactuSystemInfoBuilder(inv.company_id, self.config).append_to(registro_alta)

        # Sello temporal y huella (idéntico al base)
        ts_str = _iso_with_tz(inv.env, getattr(inv, 'verifactu_hash_calculated_at', None))
        ET.SubElement(registro_alta, ET.QName(NS_SUM1, "FechaHoraHusoGenRegistro")).text = ts_str
        ET.SubElement(registro_alta, ET.QName(NS_SUM1, "TipoHuella")).text = "01"
        ET.SubElement(registro_alta, ET.QName(NS_SUM1, "Huella")).text = current_hash

        # Firma de RegistroAlta
        raw_alta = ET.tostring(registro_alta, encoding="utf-8")
        signed_str = VerifactuXMLSigner(self.config).sign(raw_alta)
        signed_lxml = LET.fromstring(_to_bytes(signed_str))
        signed_etree = ET.fromstring(_to_bytes(LET.tostring(signed_lxml)))
        registro_factura.append(signed_etree)

        # Pretty print robusto
        xml_bytes = ET.tostring(registro_factura)
        if not isinstance(xml_bytes, (bytes, bytearray)):
            xml_bytes = _to_bytes(xml_bytes)
        return _to_text(minidom.parseString(xml_bytes).toprettyxml(indent="  "))
