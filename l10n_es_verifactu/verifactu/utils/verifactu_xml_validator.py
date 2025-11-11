from odoo.exceptions import UserError
from datetime import date, timedelta, datetime
from .regime_key import VerifactuRegimeKey
from .invoice_type_resolve import VerifactuTipoFacturaResolver
from .Verifactu_Line_Analyzer  import VerifactuLineAnalyzer
from .calificacion_operacion  import VerifactuOperacionClassifier
from .cert_handler import VerifactuCertHandler
import math
import re
from odoo.fields import Date
from odoo import _, models, fields, api, tools
from decimal import Decimal, ROUND_HALF_UP
import datetime as _dt


# Patrones básicos ES (NIF/NIE/CIF). No calculo letra; solo formato.

EU_COUNTRIES = {
    'AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR','DE','GR','HU','IE',
    'IT','LV','LT','LU','MT','NL','PL','PT','RO','SK','SI','ES','SE'
}

def _safe_cpartner(partner):
    return getattr(partner, 'commercial_partner_id', partner) or partner

def _country_code_from_partner(partner):
    # v11→18: country_id puede estar vacío
    p = _safe_cpartner(partner)
    code = getattr(getattr(p, 'country_id', None), 'code', None)
    return (code or "").upper().strip() or None

def _country_code_from_vat_prefix(vat):
    if not vat:
        return None
    m = re.match(r'^\s*([A-Za-z]{2})\s*', str(vat))
    return m.group(1).upper() if m else None

def _clean_vat(vat):
    if not vat:
        return ""
    v = str(vat).upper().strip()
    # quita espacios y separadores típicos
    return re.sub(r'[\s\.\-_/]', '', v)


_SP_NIF_RE = re.compile(
    r"""(?xi)
    (?:            # NIF persona física
        [0-9]{8}[A-Z]
    )
    |
    (?:            # NIE
        [XYZ][0-9]{7}[A-Z]
    )
    |
    (?:            # CIF
        [ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-J]
    )
    """
)

def _get_country_code(obj):
    """
    Obtiene el código de país ISO-2 en mayúsculas de un partner/company.
    Tolerante a registros incompletos o nulos.
    """
    try:
        country = getattr(obj, 'country_id', None)
        code = getattr(country, 'code', '') or ''
        return code.upper()
    except Exception:
        return ''

class VerifactuXMLValidator:
    def __init__(self, invoice, config):
        self.invoice = invoice
        self.company = invoice.company_id
        self.partner = invoice.partner_id
        self.config = config

    def validate(self):
        self._validate_emisor()
        self._validate_cliente()
        self._validate_fechas()
        self._validate_tipo_factura()
        self._validate_regimen()
        self._validate_impuestos()
        self._validate_totales()
        self._validate_encadenamiento()
       #  self._validate_tercero() ESTA VALIACION NO LO HAGO PORQUE SE DA MUY POCAS VECES, PRCATICAMENTE CASI NUNCA
        # self._validate_generador()
        self._validate_flags()
        self._validate_longitudes()
        self._validate_huella()
        # Agrega más según los bloques

    def _validate_emisor(self):
        # ✅ Emisor = compañía (empresa o autónomo), NO el certificado
        inv = self.invoice
        company = inv.company_id

        from ..utils.verifactu_xml_validator import VerifactuXMLValidator

        company_name = (company.name or "").strip()
        vat_raw = (company.vat or "").strip()
        emisor_nif = VerifactuXMLValidator.clean_nif_es(vat_raw) if vat_raw else ""

        # 1) NIF del emisor (ObligadoEmision)
        if not emisor_nif:
            raise UserError("El NIF/CIF del emisor (compañía) no puede estar vacío.")

        # Permite prefijo ES; valida el cuerpo alfanumérico
        nif_for_regex = emisor_nif[2:] if emisor_nif.upper().startswith("ES") else emisor_nif
        if not re.match(r"^[A-Z0-9]{8,12}$", nif_for_regex):
            raise UserError(f"El NIF/CIF del emisor tiene un formato no válido: {emisor_nif}")

        # 2) Nombre o razón social
        if not company_name:
            raise UserError("El nombre/razón social del emisor (compañía) es obligatorio.")




    def _validate_cliente(self):
        tipo_factura = VerifactuTipoFacturaResolver.resolve(self.invoice)
        id_type = getattr(self.invoice, "verifactu_id_type", None)
        partner = self.partner
        company_vat = self.company.vat
        codigo_pais = partner.country_id.code if partner and partner.country_id else ""

        if tipo_factura in ("F1", "F3", "R1", "R2", "R3", "R4"):
            if not partner:
                raise UserError("Este tipo de factura requiere un destinatario.")
            if not partner.name:
                raise UserError("El nombre o razón social del destinatario es obligatorio.")
            if not partner.vat and id_type != "07":
                raise UserError("El NIF o identificador del destinatario es obligatorio.")

        if tipo_factura in ("F2", "R5") and partner:
            raise UserError("Este tipo de factura no debe incluir un destinatario.")

        if partner and partner.vat and partner.vat == company_vat:
            raise UserError("El NIF del destinatario no puede coincidir con el del emisor.")

        if tipo_factura == "R3" and id_type not in ("07",) and not partner.vat:
            raise UserError("Factura R3 requiere NIF o identificador tipo 'No censado' (07).")

        if tipo_factura == "R2" and id_type not in ("02", "07") and not partner.vat:
            raise UserError("Factura R2 requiere NIF o identificador tipo 02 o 07.")

        if id_type and codigo_pais == "ES" and id_type not in ("03", "07"):
            raise UserError("Para país ES, el tipo de ID debe ser Pasaporte (03) o No censado (07).")

        if id_type != "02" and not codigo_pais:
            raise UserError("El Código de país es obligatorio cuando el tipo de ID no es 02.")

        if partner and re.match(r"^\d", partner.vat or "") and not partner.name:
            raise UserError("Si el NIF del destinatario es de persona física, debe informarse también el nombre o razón social.")

        fecha = self.invoice.invoice_date_operation or self.invoice.invoice_date
        if partner and partner.vat and fecha:
            if partner.vat.startswith("XI") and fecha < date(2021, 1, 1):
                raise UserError("No se puede usar identificador 'XI' antes de 01/01/2021.")
            if partner.vat.startswith("GB") and fecha >= date(2021, 2, 1):
                raise UserError("No se puede usar identificador 'GB' a partir de 01/02/2021.")


    def _validate_fechas(self):
        invoice = self.invoice
        fecha_exp = invoice.invoice_date
        fecha_op = invoice.invoice_date_operation
        clave_regimen = VerifactuRegimeKey.compute_clave_regimen(invoice)
        tipo_factura = VerifactuTipoFacturaResolver.resolve(invoice)
        huso = getattr(invoice, "verifactu_huso_fecha", None)  # Evita petar si no existe

        hoy = Date.context_today(invoice)
        hace_20_anios = hoy - timedelta(days=365 * 20)

        if not fecha_exp:
            raise UserError("La fecha de expedición es obligatoria.")
        if fecha_exp > hoy:
            raise UserError("La fecha de expedición no puede ser futura.")
        if fecha_exp < date(2004, 10, 28):
            raise UserError("La fecha de expedición no puede ser anterior al 28/10/2004.")
        if fecha_exp < hace_20_anios:
            raise UserError("La fecha de expedición no puede ser anterior a hace 20 años.")

        if fecha_op:
            if fecha_op > hoy and clave_regimen not in ("14", "15"):
                raise UserError("La fecha de operación no puede ser futura salvo en regímenes 14 o 15.")
            if fecha_op < hace_20_anios:
                raise UserError("La fecha de operación no puede ser anterior a hace 20 años.")

        if clave_regimen == "14":
            if not fecha_op:
                raise UserError("Para ClaveRegimen 14 la fecha de operación es obligatoria.")
            if fecha_op <= fecha_exp:
                raise UserError("En ClaveRegimen 14, la fecha de operación debe ser posterior a la de expedición.")

        if fecha_op and fecha_exp > fecha_op and clave_regimen not in ("14", "15"):
            raise UserError("La fecha de expedición no puede ser posterior a la fecha de operación salvo en régimen 14 o 15.")

        if huso:
            try:
                datetime.fromisoformat(huso)
            except Exception:
                raise UserError("El campo FechaHoraHusoGenRegistro tiene un formato incorrecto (debe ser ISO 8601).")
            if len(huso) > 25:
                raise UserError("El campo FechaHoraHusoGenRegistro excede la longitud permitida.")
            
    def _to_date(v):
        """Acepta date, datetime o str y devuelve date (o None). Compat 10–18."""
        if not v:
            return None
        if isinstance(v, _dt.date) and not isinstance(v, _dt.datetime):
            return v
        if isinstance(v, _dt.datetime):
            return v.date()
        if isinstance(v, str):
            # Odoo 10–18: from_string funciona en todas
            try:
                return fields.Date.from_string(v)
            except Exception:
                try:
                    return fields.Datetime.from_string(v).date()
                except Exception:
                    return None
        return None


    def _validate_tipo_factura(self):
        invoice = self.invoice
        def is_factura_sin_identif(invoice):
            tipo = VerifactuTipoFacturaResolver.resolve(invoice)
            vat = (invoice.partner_id.vat or "").upper().strip()
            return tipo in ("F2", "R5") and (not vat or vat == "SINNIF")
        
        tipo = VerifactuTipoFacturaResolver.resolve(invoice)
        clave_regimen = VerifactuRegimeKey.compute_clave_regimen(invoice)
        destinatario = invoice.partner_id
        art_61d = "S" if is_factura_sin_identif(invoice) else "N"

        if not tipo:
            raise UserError("El campo TipoFactura es obligatorio.")

        # 1. Bloque destinatarios obligatorio o prohibido
        if tipo in ("F1", "F3", "R1", "R2", "R3", "R4"):
            if not destinatario:
                raise UserError("Este tipo de factura requiere identificar al destinatario.")
        elif tipo in ("F2", "R5"):
            if destinatario:
                raise UserError("Este tipo de factura no puede tener destinatario identificado (tipo simplificada).")

        # 2. FacturaSinIdentifDestinatarioArt61d solo puede ser 'S' si tipo es F2 o R5
        if art_61d == "S" and tipo not in ("F2", "R5"):
            raise UserError("El campo FacturaSinIdentifDestinatarioArt61d solo puede marcarse como 'S' si el tipo es F2 o R5.")

        # 3. Compatibilidad tipo-factura vs. clave régimen
        if clave_regimen == "06" and tipo in ("F2", "F3", "R5"):
            raise UserError("El tipo de factura no es válido para ClaveRegimen 06.")

        if clave_regimen == "14" and tipo not in ("F1", "R1", "R2", "R3", "R4"):
            raise UserError("Para ClaveRegimen 14, el tipo de factura debe ser F1 o R1–R4.")

        # 4. Validaciones específicas por tipo e identificador
        if tipo == "R3":
            if invoice.partner_id.vat and not invoice.partner_id.verifactu_id_type == "07":
                raise UserError("El tipo R3 solo admite NIF o IDType = No Censado (07).")

        if tipo == "R2":
            if invoice.partner_id.verifactu_id_type not in ("01", "02", "07"):
                raise UserError("El tipo R2 solo admite NIF, NIF-IVA (02) o No Censado (07).")
            

    def _validate_impuestos(self):
        analyzer = VerifactuLineAnalyzer(self.invoice)

        for data in analyzer.analyze_lines():
            line = data["line"]
            impuesto = data["tipo_impuesto"]
            tipo_impositivo = data["tipo_impositivo"]
            tipo_recargo = data["tipo_recargo_equivalencia"]
            cuota = data["cuota_repercutida"]
            cuota_recargo = data["cuota_recargo_equivalencia"]
            base_coste = data["base_coste"]
            base_normal = data["base_normal"]
            calificacion = data["calificacion"]
            operacion_exenta = data["operacion_exenta"]
            clave_regimen = data["clave_regimen"]
            fecha_op = data["fecha_operacion"]

            # A partir de aquí, exactamente la misma lógica que ya tienes:
            if base_coste and cuota and (base_coste * cuota < 0):
                raise UserError("CuotaRepercutida y BaseImponibleACoste deben tener el mismo signo.")

            if base_normal and cuota and (base_normal * cuota < 0):
                raise UserError("CuotaRepercutida y BaseImponibleOimporteNoSujeto deben tener el mismo signo.")

            if tipo_impositivo and cuota is not None:
                expected_cuota = (base_coste or base_normal) * (tipo_impositivo / 100)
                if not tools.float_compare(cuota, expected_cuota, precision_digits=2) == 0:
                    raise UserError("La CuotaRepercutida no concuerda con el TipoImpositivo y la base.")

            if (tipo_recargo and cuota_recargo is None) or (cuota_recargo and tipo_recargo is None):
                raise UserError("Si se informa TipoRecargoEquivalencia debe informarse CuotaRecargoEquivalencia y viceversa.")

            if calificacion == "S2":
                if any([tipo_impositivo, cuota, tipo_recargo, cuota_recargo]):
                    raise UserError("Si Calificación es S2, tipo y cuotas deben valer 0.")

            if operacion_exenta:
                if any([tipo_impositivo, cuota, tipo_recargo, cuota_recargo]):
                    raise UserError("No se pueden informar impuestos en una operación exenta.")

            if tipo_impositivo == 5:
                if fecha_op >= date(2023, 1, 1) and fecha_op <= date(2024, 9, 30):
                    if tipo_recargo not in (0.5, 0.62):
                        raise UserError("Para tipo 5% en este periodo, recargo debe ser 0.5 o 0.62.")
                elif fecha_op >= date(2022, 7, 1) and fecha_op <= date(2022, 12, 31):
                    if tipo_recargo != 0.5:
                        raise UserError("En ese periodo solo se permite recargo 0.5 para tipo 5%.")

            if tipo_impositivo == 21 and tipo_recargo not in (5.2, 1.75, None):
                raise UserError("Para tipo 21% solo se permite recargo 5.2 o 1.75.")

            if tipo_impositivo == 10 and tipo_recargo not in (1.4, None):
                raise UserError("Para tipo 10% solo se permite recargo 1.4.")

            if tipo_impositivo == 4 and tipo_recargo not in (0.5, None):
                raise UserError("Para tipo 4% solo se permite recargo 0.5.")

            if tipo_impositivo == 0 and fecha_op <= date(2024, 9, 30) and tipo_recargo not in (0.0, None):
                raise UserError("Para tipo 0% solo se permite recargo 0% hasta 30/09/2024.")

            if clave_regimen == "18":
                if tipo_recargo is None or cuota_recargo is None:
                    raise UserError("ClaveRegimen 18 requiere informar Tipo y Cuota de Recargo.")

            if calificacion == "S1" and (tipo_impositivo is None or cuota is None):
                raise UserError("Para Calificación S1, tipo y cuota son obligatorios.")



    def _validate_tercero(self): 
        invoice = self.invoice

        tipo_emision = invoice.verifactu_emitida_por_tercero  # valores posibles: 'T', 'D', None 
        tercero = invoice.verifactu_tercero_id  # registro relacionado

        # 1151
        if tipo_emision and tipo_emision not in ("T", "D"):
            raise UserError("El campo EmitidaPorTerceroODestinatario solo acepta valores T o D.")

        # 1155 y 1158
        if tipo_emision and not tercero:
            raise UserError("Se ha informado EmitidaPorTerceroODestinatario, pero no se ha informado el bloque Tercero.")

        if tercero and not tipo_emision:
            raise UserError("Se está informando el bloque Tercero sin estar informado EmitidaPorTerceroODestinatario.")

        # 1186 y 1187
        if tipo_emision == "T" and not tercero:
            raise UserError("Si EmitidaPorTerceroODestinatario es igual a T, el bloque Tercero es obligatorio.")

        if tercero and tipo_emision != "T":
            raise UserError("Solo se puede cumplimentar el bloque Tercero si el valor de EmitidaPorTerceroODestinatario es T.")

        # 1188
        if tercero and tercero.vat == invoice.company_id.vat:
            raise UserError("El NIF del bloque Tercero debe ser diferente al del ObligadoEmision.")

        # 1211
        if tercero and tercero.verifactu_id_type == "07":
            raise UserError("El bloque Tercero no puede estar identificado con IDType=No Censado (07).")

        # 1229
        if tipo_emision == "T" and tercero.verifactu_id_type == "07":
            raise UserError("Si el valor de GeneradoPor es igual a T, el campo IDType del bloque Generador (Tercero) no debe ser No Censado (07).")

        # 1230 y 1231
        if tipo_emision == "D" and tercero.country_id.code == "ES":
            if tercero.verifactu_id_type not in ("03", "07"):
                raise UserError("Si GeneradoPor es igual a D y el Código País es ES, IDType debe ser Pasaporte (03) o No Censado (07).")

        if tercero.verifactu_id_type not in ("01", "02", "03", "07"):
            raise UserError("El valor del campo IDType del bloque Generador es incorrecto.")

        # 1258 y 1259
        if tercero.vat and not tercero.vat.startswith("ES"):
            raise UserError("El valor del campo NIF del bloque Generador es incorrecto.")

        if tercero.vat == invoice.company_id.vat:
            raise UserError("El NIF del Tercero debe ser distinto al del emisor.")

        

    def _validate_encadenamiento(self):
        invoice = self.invoice
        config = self.config

        # Usamos SHA256 fijo según tu implementación
        tipo_huella = "SHA256"
        huella = invoice.verifactu_hash
        huella_anterior = invoice.verifactu_previous_hash

        # 1247 – Solo permitimos SHA256 por ahora
        if tipo_huella not in ("SHA256", "SHA512"):
            raise UserError("El valor del campo TipoHuella es incorrecto.")

        # 1262 – Longitud esperada del hash en base64: 44*2 = 88 (pero tú usas hex, que es 64)
        if huella and len(huella) != 64:
            raise UserError("La longitud de la huella no cumple con las especificaciones (se espera SHA256 en hexadecimal de 64 caracteres).")

        # 1263 – Longitud máxima del tipo de huella
        if tipo_huella and len(tipo_huella) > 10:
            raise UserError("La longitud del tipo de huella no cumple con las especificaciones.")

        # 1278 – La huella no puede coincidir con la anterior
        if huella and huella_anterior and huella == huella_anterior:
            raise UserError("La huella del registro anterior debe ser diferente a la del registro actual.")

        # 1280 – Si ClaveRegimen es 18 e impuesto es 01 o vacío, deben informarse recargo y cuota
        lines_data = VerifactuLineAnalyzer(invoice).analyze_lines()
        for line_data in lines_data:
            if line_data["clave_regimen"] == "18" and line_data["tipo_impuesto"] in ("01", ""):
                if not line_data["tipo_recargo_equivalencia"] or not line_data["cuota_recargo_equivalencia"]:
                    raise UserError(
                        "Si ClaveRegimen es 18 y el impuesto es IVA o vacío, deben informarse TipoRecargoEquivalencia y CuotaRecargoEquivalencia en todas las líneas."
                    )

        # 1284 – Ambos campos de recargo deben ir juntos
        for line_data in lines_data:
            tipo = line_data["tipo_recargo_equivalencia"]
            cuota = line_data["cuota_recargo_equivalencia"]
            if (tipo and not cuota) or (cuota and not tipo):
                raise UserError(
                    "Si se ha informado TipoRecargoEquivalencia también debe informarse CuotaRecargoEquivalencia y viceversa en todas las líneas."
                )




    def _validate_totales(self):
        invoice = self.invoice
        lines_data = VerifactuLineAnalyzer(invoice).analyze_lines()

        total_base = sum(line["base_normal"] for line in lines_data)
        total_base_coste = sum(line["base_coste"] for line in lines_data)
        total_cuota = sum(line["cuota_repercutida"] for line in lines_data)
        total_recargo = sum(line["cuota_recargo_equivalencia"] for line in lines_data)

        importe_total = invoice.amount_total
        macrodato = invoice.verifactu_macrodato

        # 1140 – Mismo signo entre base de coste y cuota repercutida
        if total_base_coste and total_cuota and (total_base_coste * total_cuota < 0):
            raise UserError("Los campos CuotaRepercutida y BaseImponibleACoste deben tener el mismo signo.")

        # 1143 – Mismo signo entre base normal y cuota repercutida
        if total_base and total_cuota and (total_base * total_cuota < 0):
            raise UserError("Los campos CuotaRepercutida y BaseImponibleOimporteNoSujeto deben tener el mismo signo.")

        # 1142 / 1144 – Cuota repercutida correcta por línea
        for line in lines_data:
            base = line["base_normal"]
            tipo_impositivo = line["tipo_impositivo"]
            cuota = line["cuota_repercutida"]

            if base and tipo_impositivo:
                expected_cuota = round(base * tipo_impositivo / 100, 2)
                if cuota is not None and not math.isclose(cuota, expected_cuota, abs_tol=0.02):
                    raise UserError(
                        f"La línea '{line['line'].name or line['line'].id}' tiene una CuotaRepercutida incorrecta para el TipoImpositivo y la Base."
                    )

        # 1216 – CuotaTotal = cuota + recargo
        expected_cuota_total = total_cuota + total_recargo
        if not math.isclose(expected_cuota_total, total_cuota + total_recargo, abs_tol=0.02):
            raise UserError("El campo CuotaTotal tiene un valor incorrecto respecto a CuotaRepercutida y CuotaRecargoEquivalencia.")

        # 1210 – ImporteTotal = base + cuotas
        expected_importe = total_base + total_cuota + total_recargo
        if not math.isclose(importe_total, expected_importe, abs_tol=0.02):
            raise UserError("El campo ImporteTotal tiene un valor incorrecto respecto a la suma de Base, CuotaRepercutida y Recargo.")

        # 1138 – Macrodato obligatorio si el importe es alto
        if importe_total and abs(importe_total) >= 100_000_000 and macrodato != "S":
            raise UserError("El campo Macrodato debe estar informado como S cuando el ImporteTotal >= ±100.000.000")

        # 1139 – Macrodato no debe estar como S si el importe es bajo
        if macrodato == "S" and abs(importe_total) < 100_000_000:
            raise UserError("El campo Macrodato solo puede ser S si el ImporteTotal >= ±100.000.000")
        
    def _validate_flags(self):
        i = self.invoice

        def _check_sn(field_label, value):
            if value not in (None, "S", "N"):
                raise UserError(f"El campo {field_label} solo acepta los valores 'S' o 'N'.")

        tipo = VerifactuTipoFacturaResolver.resolve(self.invoice)

        # 1183: FacturaSimplificadaArticulos7273
        flag_7273 = i.verifactu_flag_art_7273
        if flag_7273 == "S" and tipo not in ("F1", "F3", "R1", "R2", "R3", "R4"):
            raise UserError("El campo FacturaSimplificadaArticulos7273 solo se puede marcar si el tipo de factura es F1, F3, R1, R2, R3 o R4.")
        _check_sn("FacturaSimplificadaArticulos7273", flag_7273)

        # 1184–1185: FacturaSinIdentifDestinatarioArt61d
        flag_61d = i.verifactu_flag_art_61d
        if flag_61d == "S" and tipo not in ("F2", "R5"):
            raise UserError("El campo FacturaSinIdentifDestinatarioArt61d solo puede ser 'S' si el tipo de factura es F2 o R5.")
        _check_sn("FacturaSinIdentifDestinatarioArt61d", flag_61d)

        """    # 1212–1213: Uso del sistema
        _check_sn("TipoUsoPosibleSoloVerifactu", i.verifactu_flag_solo_verifactu)
        _check_sn("TipoUsoPosibleMultiOT", i.verifactu_flag_multi_ot)

        # 1226: IndicadorMultiplesOT
        _check_sn("IndicadorMultiplesOT", i.verifactu_flag_multiples_ot)

        # 1261: IndicadorRepresentante (no exigimos lógica de ObligadoEmision aquí todavía)
        _check_sn("IndicadorRepresentante", i.verifactu_flag_representante) """

        # 1270–1272: MostrarNombreRazonEmisor / MostrarSistemaInformatico
        """   mostrar_nombre = i.verifactu_flag_mostrar_nombre
        mostrar_sistema = i.verifactu_flag_mostrar_sistema
        _check_sn("MostrarNombreRazonEmisor", mostrar_nombre)
        _check_sn("MostrarSistemaInformatico", mostrar_sistema) """



        
    def _validate_regimen(self):
        invoice = self.invoice
        analyzer = VerifactuLineAnalyzer(invoice)
        tipo = VerifactuTipoFacturaResolver.resolve(invoice)

        for data in analyzer.analyze_lines():
            clave = data["clave_regimen"]
            calificacion = data["calificacion"]
            impuesto = data["tipo_impuesto"]
            operacion_exenta = data["operacion_exenta"]
            base_coste = data["base_coste"]
            cuota = data["cuota_repercutida"]
            tipo_impositivo = data["tipo_impositivo"]

            # 1200: Clave 03 → calificación solo puede ser S1
            if clave == "03" and calificacion != "S1":
                raise UserError("Si ClaveRegimen es 03, CalificacionOperacion solo puede ser S1.")

            # 1201: Clave 04 → solo S2 o Exenta
            if clave == "04" and calificacion not in ("S2", None) and not operacion_exenta:
                raise UserError("Si ClaveRegimen es 04, CalificacionOperacion solo puede ser S2 o bien Exenta.")

            # 1202: Clave 06 → no puede ser F2, F3, R5 y debe tener base de coste
            if clave == "06":
                if tipo in ("F2", "F3", "R5"):
                    raise UserError("ClaveRegimen 06 no puede usarse con facturas tipo F2, F3 o R5.")
                if not base_coste:
                    raise UserError("ClaveRegimen 06 requiere informar la BaseImponibleACoste.")

            # 1203: Clave 07 → no puede ser exenta E2–E5 ni calificación S2/N1/N2
            if clave == "07":
                if operacion_exenta in ("E2", "E3", "E4", "E5") or calificacion in ("S2", "N1", "N2"):
                    raise UserError("ClaveRegimen 07 no admite ciertas exenciones ni calificaciones S2/N1/N2.")

            # 1205: Clave 10 → calificación N1, tipo F1, y destinatario con NIF
            if clave == "10":
                if calificacion != "N1" or tipo != "F1" or not self._destinatario_identificado_por_nif():
                    raise UserError("ClaveRegimen 10 requiere Calificacion N1, TipoFactura F1 y destinatario con NIF.")

            # 1206: Clave 11 → tipo impositivo debe ser 21%
            if clave == "11" and tipo_impositivo != 21:
                raise UserError("ClaveRegimen 11 requiere TipoImpositivo igual a 21%.")

            # 1207: Cuota distinta de 0 solo si calificación es S1
            if cuota and cuota != 0 and calificacion != "S1":
                raise UserError("Cuota solo puede ser distinta de 0 si CalificacionOperacion es S1.")

            # 1208 y 1209: S1 requiere tipo y cuota si falta base, y obligatorio si clave es 06
            if calificacion == "S1":
                if not base_coste and (not tipo_impositivo or not cuota):
                    raise UserError("Calificacion S1 requiere TipoImpositivo y CuotaRepercutida si no hay Base de Coste.")
                if clave == "06" and (not tipo_impositivo or not cuota):
                    raise UserError("Calificacion S1 con Clave 06 requiere TipoImpositivo y CuotaRepercutida.")

            # 1257: BaseImponibleACoste solo permitido si clave = 06 o impuesto = 02 (IPSI) o 05 (Otros)
            if base_coste and clave != "06" and impuesto not in ("02", "05"):
                raise UserError("BaseImponibleACoste solo puede informarse si ClaveRegimen = 06 o Impuesto es 02/05.")

            # 1260: ClaveRegimen solo se permite si Impuesto es vacío o 01 o 03
            if clave and impuesto not in ("", "01", "03"):
                raise UserError("ClaveRegimen solo debe informarse si el Impuesto es vacío, 01 o 03.")



        

    def _validate_recargo_equivalencia(self):
        invoice = self.invoice
        analyzer = VerifactuLineAnalyzer(invoice)
        fecha = invoice.invoice_date or fields.Date.today()

        for data in analyzer.analyze_lines():
            tipo = data["tipo_recargo_equivalencia"]
            cuota = data["cuota_recargo_equivalencia"]
            impuesto = data["tipo_impuesto"]
            tipo_impositivo = data["tipo_impositivo"]
            calif = data["calificacion"]
            clave_regimen = data["clave_regimen"]

            # 1284
            if (tipo and not cuota) or (cuota and not tipo):
                raise UserError("Si se ha informado de TipoRecargoEquivalencia también se debe informar de CuotaRecargoEquivalencia y viceversa.")

            # 1281
            if (tipo or cuota) and calif != "S1":
                raise UserError("Solo se puede cumplimentar TipoRecargoEquivalencia y CuotaRecargoEquivalencia cuando CalificacionOperacion es 'S1'.")

            # 1279
            if (tipo or cuota) and impuesto in (None, "01", "03") and clave_regimen != "18":
                raise UserError("Si el impuesto es IVA(01) o vacío, solo se podrá informar TipoRecargoEquivalencia y CuotaRecargoEquivalencia si ClaveRegimen es 18.")

            # 1280
            if impuesto in (None, "01", "03") and clave_regimen == "18" and (not tipo or not cuota):
                raise UserError("Si el impuesto es IVA(01) o vacío y ClaveRegimen es 18, es obligatorio informar TipoRecargoEquivalencia y CuotaRecargoEquivalencia.")

            # 1160–1166, 1169–1170: reglas por tipo impositivo y fechas
            if tipo_impositivo == 5.0:
                if fecha < date(2022, 7, 1) or fecha > date(2024, 9, 30):
                    raise UserError("TipoImpositivo 5% con recargo solo permitido entre el 1/7/2022 y 30/9/2024.")
                elif fecha <= date(2022, 12, 31) and tipo != 0.5:
                    raise UserError("Para el 5% antes de 2023, solo se admite TipoRecargoEquivalencia 0,5.")
                elif fecha >= date(2023, 1, 1) and tipo != 0.62:
                    raise UserError("Para el 5% desde 2023, solo se admite TipoRecargoEquivalencia 0,62.")

            if tipo_impositivo == 0 and date(2023, 1, 1) <= fecha <= date(2024, 9, 30):
                if tipo != 0:
                    raise UserError("TipoRecargoEquivalencia para TipoImpositivo 0% solo puede ser 0% entre 1/1/2023 y 30/9/2024.")

            if tipo_impositivo == 2.0 and date(2024, 10, 1) <= fecha <= date(2024, 12, 31) and tipo != 0.26:
                raise UserError("Para TipoImpositivo 2% entre 1/10/2024 y 31/12/2024 solo se admite recargo 0,26.")

            if tipo_impositivo == 7.5 and date(2024, 10, 1) <= fecha <= date(2024, 12, 31) and tipo != 1.0:
                raise UserError("Para TipoImpositivo 7.5% entre 1/10/2024 y 31/12/2024 solo se admite recargo 1,0.")

            if tipo_impositivo == 21 and tipo not in (5.2, 1.75):
                raise UserError("Para TipoImpositivo 21% solo se admite recargo 5,2 o 1,75.")

            if tipo_impositivo == 10 and tipo != 1.4:
                raise UserError("Para TipoImpositivo 10% solo se admite recargo 1,4.")

            if tipo_impositivo == 4 and tipo != 0.5:
                raise UserError("Para TipoImpositivo 4% solo se admite recargo 0,5.")

            # 1277
            if tipo_impositivo == 0 and tipo != 0:
                raise UserError("TipoRecargoEquivalencia para tipo impositivo 0% debe ser 0%.")

        # 1216: Cuota total coherente (evaluada a nivel factura)
        if any(data["cuota_recargo_equivalencia"] for data in analyzer.analyze_lines()):
            if not self._cuota_total_valida():
                raise UserError("El campo CuotaTotal tiene un valor incorrecto para el valor de los campos CuotaRepercutida y CuotaRecargoEquivalencia.")



    def _validate_generador(self):
        invoice = self.invoice
        generado_por = invoice.verifactu_generado_por
        generador = {
            "nif": invoice.verifactu_generador_nif,
            "id_type": invoice.verifactu_generador_id_type,
            "id_otro": invoice.verifactu_generador_id_otro,
            "codigo_pais": invoice.verifactu_generador_codigo_pais,
        }

        nif = generador.get("nif")
        id_type = generador.get("id_type")
        id_otro = generador.get("id_otro")
        codigo_pais = generador.get("codigo_pais")

        # 1227: Si generado_por = 'E' → debe tener NIF
        if generado_por == "E" and not nif:
            raise UserError("El campo NIF del bloque Generador es obligatorio si GeneradoPor = 'E'.")

        # 1228: No puede haber NIF e IDOtro a la vez, pero uno debe existir
        if nif and id_otro:
            raise UserError("No puede haber NIF e IDOtro a la vez en el bloque Generador.")
        if not nif and not id_otro:
            raise UserError("Debe informarse NIF o IDOtro en el bloque Generador.")

        # 1231: Validación de IDType
        if id_type and id_type not in ("01", "02", "03", "06", "07"):
            raise UserError(f"IDType del bloque Generador es incorrecto: {id_type}")

        # 1232–1234: IDOtro con país ES → solo tipos 03 o 07
        if id_otro and codigo_pais == "ES" and id_type not in ("03", "07"):
            raise UserError("Si se usa IDOtro con país ES, el IDType debe ser Pasaporte (03) o No Censado (07).")

        # 1258: Validación censal del NIF (si implementaste _nif_valido)
        if nif and not self._nif_valido(nif):
            raise UserError("El NIF del bloque Generador no es válido.")

        # 1259: NIF del Generador ≠ NIF del ObligadoEmision
        if nif and nif == invoice.verifactu_obligado_nif:
            raise UserError("El NIF del Generador debe ser distinto al del ObligadoEmision.")

        
    def _validate_longitudes(self):
        analyzer = VerifactuLineAnalyzer(self.invoice)
        line_data_list = analyzer.analyze_lines()

        for line_data in line_data_list:
            def check_max_length(value, max_len, field_name, line):
                if value is not None and len(str(value)) > max_len:
                    raise UserError(
                        f"La longitud del campo '{field_name}' en la línea '{line.name}' supera los {max_len} caracteres."
                    )

            def check_length(value, expected_len, field_name, line):
                if value is not None and len(str(value)) != expected_len:
                    raise UserError(
                        f"La longitud del campo '{field_name}' en la línea '{line.name}' debe ser exactamente {expected_len} caracteres."
                    )

            line = line_data["line"]
            check_max_length(line_data["tipo_impuesto"], 2, "TipoImpuesto", line)
            check_max_length(line_data["tipo_impositivo"], 6, "TipoImpositivo", line)
            check_max_length(line_data["tipo_recargo_equivalencia"], 6, "TipoRecargoEquivalencia", line)
            check_max_length(line_data["cuota_repercutida"], 16, "CuotaRepercutida", line)
            check_max_length(line_data["cuota_recargo_equivalencia"], 16, "CuotaRecargoEquivalencia", line)
            check_max_length(line_data["base_coste"], 16, "BaseImponibleACoste", line)
            check_max_length(line_data["base_normal"], 16, "BaseImponible", line)
            check_max_length(line_data["calificacion"], 2, "CalificacionOperacion", line)
            check_max_length(line_data["operacion_exenta"], 2, "OperacionExenta", line)


        

    def _validate_huella(self):
        i = self.invoice

        # Revisión: usar los nombres correctos de campos
        huella_actual = i.verifactu_hash
        huella_anterior = i.verifactu_previous_hash
        tipo_huella = "SHA256"

        # 1278: La huella del registro anterior no puede coincidir con la del actual
        if huella_anterior and huella_actual:
            if huella_anterior == huella_actual:
                raise UserError("La huella del registro anterior no puede coincidir con la del actual.")

        # 1262: Validar longitud de la huella (se espera 64 si es SHA256)
        if huella_actual and len(huella_actual) != 64:
            raise UserError("La longitud de la huella actual no cumple con las especificaciones. Se espera 64 caracteres.")

        # 1247: Validar tipo de huella permitido
        if tipo_huella and tipo_huella not in ("SHA256", "SHA384"):
            raise UserError("El valor del campo TipoHuella es incorrecto. Debe ser SHA256 o SHA384.")




    @staticmethod
    def clean_vat_like(text):
        """
        Quita espacios, puntos y guiones, y pasa a mayúsculas.
        Devuelve solo caracteres [A-Z0-9].
        """
        if not text:
            return ''
        return re.sub(r'[^A-Z0-9]', '', (text or '').upper())


    @staticmethod
    def clean_nif_es(vat):
        """
        Normaliza y limpia el VAT/NIF:
        - Convierte a mayúsculas, sin espacios ni separadores.
        - Elimina prefijo de país (p.ej. ES, FR, DE...) si viene de VIES/ERP.
        - Devuelve la parte numérica o alfanumérica pura.
        """
        if not vat:
            return ""
        v = VerifactuXMLValidator.clean_vat_like(vat)

        # Elimina prefijo de país si existe (códigos ISO-3166 de 2 letras al inicio)
        if len(v) >= 2 and v[:2].isalpha():
            # Para no eliminar códigos falsos tipo 'XX123...', comprobamos que no sea un NIF español legítimo (A12345678)
            prefix = v[:2].upper()
            # Si el prefijo es un país europeo o ES, lo quitamos
            EU_CODES = {
                'AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR','DE','GR','HU','IE',
                'IT','LV','LT','LU','MT','NL','PL','PT','RO','SK','SI','ES','SE'
            }
            if prefix in EU_CODES:
                v = v[2:]

        return v.strip()


    @staticmethod
    def is_es_nif_format(v):
        """Valida formato básico (sin calcular letra) de NIF/NIE/CIF."""
        if not v:
            return False
        return bool(_SP_NIF_RE.fullmatch(v))
    

    @staticmethod
    def is_probably_eu_vat(vat):
        """
        Heurística mejorada para detectar y limpiar VAT-UE:
        - Elimina separadores y espacios.
        - Detecta prefijo ISO (2 letras) y lo normaliza:
            EL→GR, UK→GB, XI→XI (Irlanda del Norte), etc.
        - Elimina el prefijo del VAT limpio si es válido.
        - Considera todos los países de la UE y XI.
        Devuelve: (es_vat_ue, código_país_normalizado, vat_sin_prefijo)
        """
        v = _clean_vat(vat)
        if not v or len(v) < 4:
            return (False, None, v)

        pref = _country_code_from_vat_prefix(v) or ''
        if not pref:
            return (False, None, v)

        pref = pref.upper()

        # --- Normalizaciones comunes ---
        normalization_map = {
            'EL': 'GR',  # Grecia (EL en VAT, GR en AEAT)
            'UK': 'GB',  # Reino Unido (aunque post-Brexit, aún se usa en históricos)
            'GB': 'GB',  # Mantiene GB
            'XI': 'XI',  # Irlanda del Norte (caso especial post-Brexit)
        }
        norm = normalization_map.get(pref, pref)

        # ES no cuenta como VAT-UE extranjero
        if norm == 'ES':
            return (False, None, v)

        # Países UE reconocidos (más XI)
        in_eu = (norm in EU_COUNTRIES) or (norm == 'XI')

        # Reglas mínimas: formato alfanumérico, longitud ≥ 4
        is_alnum = v.isalnum()

        # Si el VAT tiene formato válido y pertenece a un país UE, limpiamos el prefijo
        vat_limpio = v
        if in_eu and is_alnum and v.upper().startswith(pref):
            vat_limpio = v[len(pref):].strip()

        # Asegura coherencia (p.ej. "FR 23334175221" → "23334175221")
        return (bool(in_eu and is_alnum), norm if in_eu else None, vat_limpio)



    @staticmethod
    def build_id_for_xml(partner):
        """
        Devuelve un diccionario con los datos de identificación fiscal
        del destinatario en formato compatible con el esquema AEAT VeriFactu 1.0.

        Ejemplos devueltos:
        - {'tag': 'NIF', 'value': 'B12345678'}
        - {'tag': 'IDOtro', 'IDType': '02', 'CodigoPais': 'US', 'ID': '352712024'}
        - {'tag': 'IDOtro', 'IDType': '06', 'CodigoPais': 'ES', 'ID': 'X1234567L'}

        Reglas aplicadas:
        1️⃣ España (ES) → NIF válido → <NIF>
        2️⃣ España (ES) sin NIF válido → IDOtro(06)
        3️⃣ Unión Europea ≠ ES → IDOtro(02) o (04) si sin VAT válido
        4️⃣ Extracomunitario → IDOtro(02) si empresa, (01) si persona física
        5️⃣ Sin país → error explícito (mejor fallar que enviar datos inválidos)
        """
        p = _safe_cpartner(partner)

        raw_vat = getattr(p, "vat", "") or ""
        vat_clean = _clean_vat(raw_vat)

        # 1️⃣ País del partner o deducido del VAT
        country = (
            _country_code_from_partner(p)
            or _country_code_from_vat_prefix(vat_clean)
        )

        # 2️⃣ España
        if country == "ES":
            v = VerifactuXMLValidator.clean_nif_es(raw_vat)
            if VerifactuXMLValidator.is_es_nif_format(v):
                return {"tag": "NIF", "value": v}

            # Español sin NIF/NIE/CIF válido → IDOtro 06 (documento nacional alternativo)
            _id = (v or vat_clean or (getattr(p, "ref", "") or "")).strip()
            if not _id:
                raise UserError(
                    "VeriFactu: destinatario español sin NIF válido y sin ID alternativo (ref)."
                )
            return {"tag": "IDOtro", "IDType": "06", "CodigoPais": "ES", "ID": _id}

        # 3️⃣ Unión Europea (excepto España)
        if country in EU_COUNTRIES and country != "ES":
            ok, norm_pref, vclean = VerifactuXMLValidator.is_probably_eu_vat(vat_clean)
            if ok and (norm_pref == country or (country == "GR" and norm_pref == "EL")):
                # VAT-UE válido
                _id = vclean
                if not _id.upper().startswith(country):
                    _id = f"{country}{_id}"  # añade prefijo si falta
                return {"tag": "IDOtro", "IDType": "02", "CodigoPais": country, "ID": _id}


            # UE sin VAT-UE válido → documento alternativo
            _id = (vclean or getattr(p, "ref", "") or "").strip()
            if not _id:
                raise UserError("VeriFactu: destinatario UE sin VAT-UE ni ID alternativo.")
            return {"tag": "IDOtro", "IDType": "04", "CodigoPais": country, "ID": _id}

        # 4️⃣ Extracomunitario (fuera de la UE)
        if country:
            _id = (vat_clean or getattr(p, "ref", "") or "").strip()
            if not _id:
                raise UserError("VeriFactu: destinatario extranjero sin documento (ID) ni VAT/Ref.")

            # Diferenciamos empresa vs persona física (AEAT recomienda 02 / 01)
            id_type = "02" if getattr(p, "is_company", True) else "01"
            return {"tag": "IDOtro", "IDType": id_type, "CodigoPais": country, "ID": _id}

        # 5️⃣ Sin país → error (no podemos inventarlo)
        raise UserError(
            "VeriFactu: el destinatario no tiene país y no se puede inferir del VAT. "
            "Asigna un país al contacto o usa un VAT con prefijo de país (p.ej. FR..., DE...)."
        )




    @staticmethod
    def get_recargo_equivalencia_from_tax_ids(tax_ids): # OJO ESTO ES ALO NUEVO
        RE_TYPES = {
            Decimal("5.2"): Decimal("21.0"),
            Decimal("1.4"): Decimal("10.0"),
            Decimal("0.5"): Decimal("4.0"),
        }

        for tax in tax_ids:
            tipo = Decimal(tax.amount).quantize(Decimal("0.1"))
            if tipo in RE_TYPES:
                return tipo
        return None
    
    @staticmethod
    def infer_tipo_rectificativa(invoice): # OJO ESTO ES ALO NUEVO
        original = invoice.reversed_entry_id
        if not original:
            return "S"  # por defecto

        # Comparamos totales
        same_base = abs(original.amount_untaxed - invoice.amount_untaxed) < 0.01
        same_tax = abs(original.amount_tax - invoice.amount_tax) < 0.01
        same_total = abs(original.amount_total - invoice.amount_total) < 0.01

        if same_base and same_tax and same_total:
            return "S"
        else:
            return "I"

    @staticmethod
    def build_descripcion_operacion(invoice):
        """
        Genera una descripción contextual para el nodo <DescripcionOperacion>.
        Compatible con Odoo 10–18 y según recomendaciones AEAT.
        """
        tipo = getattr(invoice, "move_type", "") or ""
        tipo_factura = VerifactuTipoFacturaResolver.resolve(invoice)
        is_refund = tipo.startswith("out_refund") or tipo_factura.startswith("R")

        # Recoge nombres únicos de líneas
        productos = list({
            (line.name or line.product_id.display_name or "").strip()
            for line in getattr(invoice, "invoice_line_ids", [])
            if (line.name or line.product_id)
        })

        # Clasificación heurística
        servicios = [
            p for p in productos
            if any(s in p.lower() for s in ("servicio", "consultor", "mantenimiento", "soporte", "desarrollo"))
        ]

        resumen = ""

        # Caso 1: Factura rectificativa
        if is_refund:
            resumen = "Factura rectificativa"
            if getattr(invoice, "reversed_entry_id", False):
                orig = invoice.reversed_entry_id
                num_orig = getattr(orig, "name", "") or getattr(orig, "number", "")
                date_orig = getattr(orig, "invoice_date", getattr(orig, "date_invoice", None))
                resumen += f" de la factura {num_orig or 'anterior'}"
                if date_orig:
                    resumen += f" emitida el {date_orig.strftime('%d-%m-%Y')}"
            elif hasattr(invoice, "ref") and invoice.ref:
                resumen += f" referente a {invoice.ref}"

        # Caso 2: Servicios o productos
        elif servicios and len(servicios) > 0:
            resumen = "Prestación de servicios"
            resumen += f": {', '.join(servicios[:3])}"
        elif productos:
            resumen = "Venta de bienes"
            resumen += f": {', '.join(productos[:3])}"
        else:
            resumen = "Operación comercial sin descripción detallada"

        # Añadir información de líneas si es relevante
        num_lines = len(getattr(invoice, "invoice_line_ids", []))
        if num_lines > 3:
            resumen += f" (total {num_lines} conceptos)"

        return resumen.strip()[:500]


    @staticmethod
    def compute_base_coste_proporcional(invoice, base_grupo, base_coste_total):
        base_grupo = Decimal(str(base_grupo))
        base_coste_total = Decimal(str(base_coste_total))

        base_total_factura = sum(
            Decimal(str(line.price_subtotal))
            for line in invoice.invoice_line_ids
            if any("margen" in (tax.description or "").lower() for tax in line.tax_ids)
        )

        if base_total_factura == 0:
            return Decimal("0.00")

        proporcional = (base_grupo / base_total_factura * base_coste_total)
        return proporcional.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    @staticmethod
    def get_original_invoice(inv):
        orig = getattr(inv, 'reversed_entry_id', False)  # v13+
        if orig:
            return orig
        return getattr(inv, 'refund_invoice_id', False)  # v11–12

    @staticmethod
    def get_original_num_and_date(orig):
        if not orig:
            return None, None
        num = getattr(orig, 'name', None) or getattr(orig, 'number', None)
        date = getattr(orig, 'invoice_date', None) or getattr(orig, 'date_invoice', None)
        return num, date

    @staticmethod
    def compute_importe_rectificacion(invoice, original, tipo_rectificativa):
        """
        Devuelve (base_rectificada, cuota_rectificada) como floats >= 0
        - 'S' (sustitución): rectificas la **original** completa. Si no hay original,
        usa los totales de la factura rectificativa como fallback.
        - 'I' (diferencias): informa la **diferencia**; en la práctica, la mayoría de
        rectificativas por diferencias ya vienen con los importes de diferencia,
        así que tomamos los totales de la rectificativa (en positivo).
        """
        def _abs2(x):
            try:
                return abs(float(x or 0.0))
            except Exception:
                return 0.0

        if (tipo_rectificativa or '').upper() == 'S':
            if original:
                base = _abs2(getattr(original, 'amount_untaxed', 0.0))
                cuota = _abs2(getattr(original, 'amount_tax', 0.0))
            else:
                base = _abs2(getattr(invoice, 'verifactu_base_original', None)) or _abs2(getattr(invoice, 'amount_untaxed', 0.0))
                cuota = _abs2(getattr(invoice, 'verifactu_cuota_original', None)) or _abs2(getattr(invoice, 'amount_tax', 0.0))
            return base, cuota

        # 'I' diferencias (o cualquier otro código): usa los totales de la rectificativa
        base = _abs2(getattr(invoice, 'amount_untaxed', 0.0))
        cuota = _abs2(getattr(invoice, 'amount_tax', 0.0))
        return base, cuota
