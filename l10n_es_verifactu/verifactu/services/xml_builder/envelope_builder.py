# -*- coding: utf-8 -*-
import xml.etree.ElementTree as ET
from xml.dom import minidom
from odoo.exceptions import UserError
from ...utils.verifactu_xml_validator import VerifactuXMLValidator  # limpia NIF

# Namespaces AEAT
NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
NS_SUM  = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd"
NS_SUM1 = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"

# Registrar prefijos (funciona en Py2/Py3)
ET.register_namespace("soapenv", NS_SOAP)
ET.register_namespace("sum", NS_SUM)
ET.register_namespace("sum1", NS_SUM1)


class VerifactuEnvelopeBuilder(object):
    """Construye el sobre SOAP para AEAT. Compatible Odoo 11→18."""

    def __init__(self, invoice, config):
        self.invoice = invoice
        self.config = config

    # ---------- Helpers compat ----------

    def _to_bytes(self, s):
        """Convierte a bytes (robusto Py2/Py3)."""
        try:
            if isinstance(s, (bytes, bytearray)):
                return s
            return s.encode("utf-8")
        except Exception:
            try:
                return s.encode("utf-8")
            except Exception:
                return s

    def _fromstring(self, xml_str):
        """ET.fromstring robusto para str/bytes."""
        if isinstance(xml_str, (bytes, bytearray)):
            return ET.fromstring(xml_str)
        return ET.fromstring(self._to_bytes(xml_str))

    @staticmethod
    def _localname(tag):
        if not tag:
            return ""
        return tag.split("}", 1)[1] if "}" in tag else tag

    # ---------- Build ----------

    def build(self, signed_xml_str):
        # Emisor (empresa/autónomo) SIEMPRE desde company_id
        company = self.invoice.company_id
        company_name = (company.name or "").strip()
        company_vat_raw = (company.vat or "").strip()
        company_vat = VerifactuXMLValidator.clean_nif_es(company_vat_raw) if company_vat_raw else ""

        if not company_name or not company_vat:
            raise UserError("VeriFactu: faltan datos del emisor en la compañía (Nombre y/o NIF/CIF).")

        # SOAP Envelope
        root = ET.Element("{%s}Envelope" % NS_SOAP)
        ET.SubElement(root, "{%s}Header" % NS_SOAP)
        body = ET.SubElement(root, "{%s}Body" % NS_SOAP)

        # Contenedor RegFactuSistemaFacturacion
        reg_fact = ET.SubElement(body, "{%s}RegFactuSistemaFacturacion" % NS_SUM)

        # Cabecera con obligado a la emisión
        cabecera = ET.SubElement(reg_fact, "{%s}Cabecera" % NS_SUM)
        obligado = ET.SubElement(cabecera, "{%s}ObligadoEmision" % NS_SUM1)
        ET.SubElement(obligado, "{%s}NombreRazon" % NS_SUM1).text = company_name
        ET.SubElement(obligado, "{%s}NIF" % NS_SUM1).text = company_vat

        # XML firmado (puede ser RegistroFactura, RegistroAlta, RegistroAnulacion o RegistroResumen)
        signed_root = self._fromstring(signed_xml_str)
        lname = self._localname(signed_root.tag)

        if lname in ("RegistroAlta", "RegistroAnulacion", "RegistroResumen"):
            registro_factura = ET.SubElement(reg_fact, "{%s}RegistroFactura" % NS_SUM)
            registro_factura.append(signed_root)
        elif lname == "RegistroFactura":
            reg_fact.append(signed_root)
        else:
            raise ValueError(
                "Estructura XML no reconocida: se esperaba RegistroFactura/RegistroAlta/"
                "RegistroAnulacion/RegistroResumen (recibido: %s)" % lname
            )

        # Pretty print
        return minidom.parseString(self._to_bytes(ET.tostring(root))).toprettyxml(indent="  ")

    # (Útil si alguna vez necesitas forzar namespace de sum1 recursivamente)
    def _prefix_elements_recursively(self, elem, ns_uri=NS_SUM1):
        local = self._localname(elem.tag)
        elem.tag = u"{%s}%s" % (ns_uri, local)
        for child in list(elem):
            self._prefix_elements_recursively(child, ns_uri)
