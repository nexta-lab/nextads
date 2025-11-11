# -*- coding: utf-8 -*-
import re
import xml.etree.ElementTree as ET
from odoo.exceptions import UserError
from odoo.tools.translate import _
from ..utils.verifactu_xml_validator import VerifactuXMLValidator  # limpiar NIF

NS_SUM1 = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroInformacion.xsd"

# Compat Py2/Py3
try:
    basestring
except NameError:
    basestring = (str,)

def _to_text(v):
    """Convierte a texto sin reventar por bytes/Decimal/etc."""
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
        return str(v)
    except Exception:
        return str(v)

def _normalize(v):
    """
    Normaliza un valor de la config para XML:
    - None/False → ""
    - strings solo espacios → ""
    - cualquier otro → texto
    """
    if v is None or v is False:
        return u""
    if isinstance(v, basestring):
        s = v.strip()
        return s if s else u""
    return _to_text(v)

_ID_RE = re.compile(r'^[A-Z0-9\-]{1,50}$')

def _sanitize_system_id(raw):
    """Mayúsculas, solo A–Z 0–9 y guion; <=50 chars."""
    s = _normalize(raw).upper()
    s = re.sub(r'[^A-Z0-9\-]', u'', s)
    return s[:50]

class VerifactuSystemInfoBuilder(object):
    def __init__(self, company, config):
        self.company = company
        self.config = config

    def get_system_info(self):
        # Lee y limpia
        name = _normalize(getattr(self.config, 'verifactu_system_name', None))
        sys_id = _sanitize_system_id(getattr(self.config, 'verifactu_system_id', None))
        version = _normalize(getattr(self.config, 'verifactu_system_version', None))
        install = _normalize(getattr(self.config, 'verifactu_system_installation_number', None))
        only_vf = _normalize(getattr(self.config, 'verifactu_system_use_only_verifactu', None))
        multi_ot = _normalize(getattr(self.config, 'verifactu_system_multi_ot', None))
        multi_ind = _normalize(getattr(self.config, 'verifactu_system_multiple_ot_indicator', None))

        # Defaults seguros si se quedaron vacíos tras limpiar
        if not name:
            name = u"VF-ODOO-MRR"
        if not sys_id:
            sys_id = u"89"  # pon aquí tu default preferido
        if not version:
            version = u"2.0.6"
        if not install:
            install = u"1"
        if not only_vf:
            only_vf = u"N"
        if not multi_ot:
            multi_ot = u"S"
        if not multi_ind:
            multi_ind = u"S"

        # Validación dura del ID
        if not _ID_RE.match(sys_id):
            raise UserError(_(
                "Identificador del sistema inválido. Use solo letras mayúsculas, dígitos y guiones (A-Z, 0-9, -), 1–50 caracteres."
            ))

        return {
            "NombreSistemaInformatico": name,
            "IdSistemaInformatico": sys_id,
            # OJO: el esquema que estás usando esperaba <Version> (no VersionSistemaInformatico)
            "Version": version,
            "NumeroInstalacion": install,
            "TipoUsoPosibleSoloVerifactu": only_vf,
            "TipoUsoPosibleMultiOT": multi_ot,
            "IndicadorMultiplesOT": multi_ind,
        }

    def append_to(self, parent_element):
        info = self.get_system_info()

        # Emisor/titular del sistema = company
        company_name = _normalize(getattr(self.company, 'name', u""))
        company_vat_raw = _normalize(getattr(self.company, 'vat', u""))
        company_vat = VerifactuXMLValidator.clean_nif_es(company_vat_raw) if company_vat_raw else u""

        if (not company_name) or (not company_vat):
            raise UserError(_("VeriFactu: faltan datos en la compañía (Nombre y/o NIF/CIF) para 'SistemaInformatico'."))

        sistema = ET.SubElement(parent_element, ET.QName(NS_SUM1, "SistemaInformatico"))
        ET.SubElement(sistema, ET.QName(NS_SUM1, "NombreRazon")).text = company_name
        ET.SubElement(sistema, ET.QName(NS_SUM1, "NIF")).text = company_vat
        ET.SubElement(sistema, ET.QName(NS_SUM1, "NombreSistemaInformatico")).text = info["NombreSistemaInformatico"]
        ET.SubElement(sistema, ET.QName(NS_SUM1, "IdSistemaInformatico")).text = info["IdSistemaInformatico"]
        ET.SubElement(sistema, ET.QName(NS_SUM1, "Version")).text = info["Version"]
        ET.SubElement(sistema, ET.QName(NS_SUM1, "NumeroInstalacion")).text = info["NumeroInstalacion"]
        ET.SubElement(sistema, ET.QName(NS_SUM1, "TipoUsoPosibleSoloVerifactu")).text = info["TipoUsoPosibleSoloVerifactu"]
        ET.SubElement(sistema, ET.QName(NS_SUM1, "TipoUsoPosibleMultiOT")).text = info["TipoUsoPosibleMultiOT"]
        ET.SubElement(sistema, ET.QName(NS_SUM1, "IndicadorMultiplesOT")).text = info["IndicadorMultiplesOT"]
