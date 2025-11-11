# -*- coding: utf-8 -*-
# Desarrollado por Juan Ormaechea (Mr. Rubik) — Todos los derechos reservados
# Este módulo está protegido por la Odoo Proprietary License v1.0
# Cualquier redistribución está prohibida sin autorización expresa.

from xml.dom import minidom
from xml.etree import ElementTree as ET
from datetime import datetime

# Compat Py2/Py3
try:
    basestring
except NameError:
    basestring = (str,)

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

def _coerce_date(val):
    """Admite date/datetime/str(YYYY-MM-DD) y devuelve date o ''."""
    if not val:
        return u""
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
    return u""

def _fmt_date_ddmmyyyy(val):
    d = _coerce_date(val)
    try:
        return d.strftime("%Y-%m-%d") if d else u""
    except Exception:
        return u""


class VerifactuSimpleXMLBuilder(object):
    def __init__(self, invoice):
        self.invoice = invoice

    def _get_number(self, inv):
        # v13+: name ; v10–12: number
        return (getattr(inv, "name", None) or getattr(inv, "number", u"") or u"").strip()

    def _get_date(self, inv):
        # v13+: invoice_date ; v10–12: date_invoice ; fallback: date
        if getattr(inv, "invoice_date", None):
            return inv.invoice_date
        if getattr(inv, "date_invoice", None):
            return inv.date_invoice
        if getattr(inv, "date", None):
            return inv.date
        return u""

    def build(self):
        """
        Genera un XML simplificado con los campos básicos de la factura.
        Compatible Odoo 10 → 18 y Py2/Py3.
        """
        self.invoice.ensure_one()

        inv = self.invoice
        root = ET.Element("Factura")

        ET.SubElement(root, "Numero").text = self._get_number(inv)
        ET.SubElement(root, "Cliente").text = (getattr(inv.partner_id, "name", u"") or u"")
        ET.SubElement(root, "Fecha").text = _fmt_date_ddmmyyyy(self._get_date(inv))
        ET.SubElement(root, "Total").text = _to_text(str(getattr(inv, "amount_total", 0.0) or 0.0))
        ET.SubElement(root, "Hash").text = (getattr(inv, "verifactu_hash", u"") or u"")
        ET.SubElement(root, "HashAnterior").text = (getattr(inv, "verifactu_previous_hash", u"") or u"")

        lineas_xml = ET.SubElement(root, "Lineas")
        for line in getattr(inv, "invoice_line_ids", []):
            linea = ET.SubElement(lineas_xml, "Linea")
            # display_name no existe en versiones muy antiguas → fallback a name
            product_name = (
                getattr(getattr(line, "product_id", None), "display_name", None)
                or getattr(line, "name", u"")
                or u""
            )
            ET.SubElement(linea, "Producto").text = product_name
            ET.SubElement(linea, "Cantidad").text = _to_text(str(getattr(line, "quantity", 0.0) or 0.0))
            ET.SubElement(linea, "Precio").text = _to_text(str(getattr(line, "price_unit", 0.0) or 0.0))

        # Pretty print robusto para Py2/Py3
        rough_bytes = ET.tostring(root, encoding="utf-8")
        xml_text = minidom.parseString(_to_bytes(rough_bytes)).toprettyxml(indent="  ")
        return _to_text(xml_text)
