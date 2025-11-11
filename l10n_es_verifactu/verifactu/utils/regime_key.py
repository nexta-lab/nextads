from odoo.exceptions import UserError
from ..utils.invoice_type_resolve import VerifactuTipoFacturaResolver
from ..utils.calificacion_operacion import VerifactuOperacionClassifier
from decimal import Decimal, ROUND_HALF_UP
# aqui estan las reglas para entender mejor todo esto:
# https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/SuministroLR.xsd
# reglas de asignacion de clave regimen: 1203 por ejmplo
class VerifactuRegimeKey:
    
    @staticmethod
    def compute_clave_regimen(invoice):
        tipo_factura = VerifactuTipoFacturaResolver.resolve(invoice)
        tipos_impositivo = VerifactuRegimeKey._get_tipos_impositivos(invoice)
        calif_operacion = VerifactuOperacionClassifier.compute(invoice)
        nif = (invoice.partner_id.vat or "").strip().upper()
        fecha_operacion = invoice.invoice_date_operation
        fecha_expedicion = invoice.invoice_date

        # Regla 1206 - Clave "11"
        # Solo evaluar regla 1206 si es una factura completa (F1) y estás en RE (si lo detectas)
        if tipo_factura == "F1" and VerifactuRegimeKey._has_recargo_equivalencia(invoice):
            if tipos_impositivo == {Decimal("21.00")}:
                return "11"
            elif Decimal("21.00") in tipos_impositivo:
                raise UserError(
                    f"La clave de régimen especial 11 solo puede usarse si todos los productos tienen un tipo impositivo del 21%. "
                    f"Tipos encontrados: {sorted(tipos_impositivo)}"
                )

                        

        # Regla 1205 - Clave "10"
        if tipo_factura == "F1" and nif.startswith("ES") and calif_operacion == "N1":
            return "10"

        # Regla 1202 - Clave "06"
        if tipo_factura in ("F2", "F3", "R5") and VerifactuRegimeKey._is_regimen_margen(invoice):
            base_coste = invoice.verifactu_base_coste
            if not base_coste or base_coste <= 0:
                raise UserError("La factura requiere 'Base de coste' para usar el régimen 06.")
            return "06"



        # Regla 1201 - Clave "04"
        if calif_operacion == "S2":
            return "04"

        # Regla 1200 - Clave "03"
        if calif_operacion == "S1":
            return "03"

        # Reglas 1147–1149 - Clave "14"
        if (
            fecha_operacion
            and fecha_expedicion
            and fecha_operacion > fecha_expedicion
            and tipo_factura in ("F1", "R1", "R2", "R3", "R4")
            and nif[:1] in ("P", "Q", "S", "V")
        ):
            return "14"

        # Valor por defecto - Clave "01"
        return "01"

    @staticmethod
    def _get_tipos_impositivos(invoice):
        """
        Devuelve un conjunto con los tipos impositivos distintos de 0% aplicados en la factura.
        """
        tipos = set()
        for line in invoice.invoice_line_ids:
            for tax in line.tax_ids:
                if tax.amount:
                    tipos.add(Decimal(tax.amount).quantize(Decimal("0.01")))
        return tipos
    

    @staticmethod
    def _has_recargo_equivalencia(invoice):
        for line in invoice.invoice_line_ids:
            for tax in line.tax_ids:
                if "recargo" in (tax.description or "").lower():
                    return True
        return False

    @staticmethod
    def _is_regimen_margen(invoice):
        return any(
            "margen" in (tax.description or "").lower()
            for line in invoice.invoice_line_ids
            for tax in line.tax_ids
        )
        
    

    @staticmethod
    def compute_base_coste_total(invoice):
        """
        Calcula automáticamente la base de coste total para una factura con régimen de margen.
        Se suma el coste real de los productos (standard_price).
        """
        base_coste = 0.0
        for line in invoice.invoice_line_ids:
            if any("margen" in (tax.description or "").lower() for tax in line.tax_ids):
                qty = line.quantity or 0
                base_coste += (line.product_id.standard_price or 0.0) * qty
        return round(base_coste, 2)

