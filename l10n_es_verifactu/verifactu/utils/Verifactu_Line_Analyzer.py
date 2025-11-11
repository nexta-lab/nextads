from odoo.tools import float_round
from .regime_key import VerifactuRegimeKey
from .calificacion_operacion import VerifactuOperacionClassifier
from odoo import fields

class VerifactuLineAnalyzer:
    def __init__(self, invoice):
        self.invoice = invoice
        self.clave_regimen = VerifactuRegimeKey.compute_clave_regimen(invoice)
        self.calificacion = VerifactuOperacionClassifier.compute(invoice)
        self.fecha_operacion = invoice.invoice_date or fields.Date.today()

    def analyze_lines(self):
        """
        Devuelve un diccionario por cada línea con todos los datos necesarios
        para la validación y generación XML.
        """
        result = []
        for line in self.invoice.invoice_line_ids:
            impuesto = self._get_tipo_impuesto(line)
            tipo_impositivo = self._get_tipo_impositivo(line)
            tipo_recargo = self._get_tipo_recargo_equivalencia(line)
            cuota = self._compute_cuota(line, tipo_impositivo)
            cuota_recargo = self._compute_cuota_recargo(line, tipo_recargo)
            base_coste = self._get_base_coste(line)
            operacion_exenta = self._is_exenta(line)

            result.append({
                "line": line,
                "tipo_impuesto": impuesto,
                "tipo_impositivo": tipo_impositivo,
                "tipo_recargo_equivalencia": tipo_recargo,
                "cuota_repercutida": cuota,
                "cuota_recargo_equivalencia": cuota_recargo,
                "base_coste": base_coste,
                "base_normal": line.price_subtotal,
                "calificacion": self.calificacion,
                "operacion_exenta": operacion_exenta,
                "clave_regimen": self.clave_regimen,
                "fecha_operacion": self.fecha_operacion,
            })

        return result

    def _get_tipo_impuesto(self, line):
        if not line.tax_ids:
            # Sin impuestos → ¿es exenta (IVA 0)? entonces es IVA (01), si no, otros (05)
            return "01" if self._is_exenta(line) else "05"

        # Identificar si es un impuesto que no es IVA (por ejemplo, IPSI o equivalentes)
        for tax in line.tax_ids:
            tipo_iva = tax.tax_group_id.name.lower()
            descripcion = (tax.description or "").lower()

            if "ipsi" in descripcion or "ceuta" in descripcion or "melilla" in descripcion:
                return "02"  # IPSI
            elif "otro" in descripcion or "especial" in descripcion:
                return "05"  # Otros impuestos especiales

        return "04"  # IVA regular


    def _get_tipo_impositivo(self, line):
        taxes = [tax for tax in line.tax_ids if tax.type_tax_use == "sale"]
        if not taxes:
            return 0.0
        return float_round(taxes[0].amount, precision_digits=2)

    def _get_tipo_recargo_equivalencia(self, line):
        for tax in line.tax_ids:
            if "recargo" in (tax.description or "").lower():
                return float_round(tax.amount, precision_digits=2)
        return None

    def _compute_cuota(self, line, tipo_impositivo):
        if tipo_impositivo is None or tipo_impositivo == 0:
            return 0.0
        return float_round(line.price_subtotal * tipo_impositivo / 100, precision_digits=2)

    def _compute_cuota_recargo(self, line, tipo_recargo):
        if tipo_recargo is None or tipo_recargo == 0:
            return 0.0
        return float_round(line.price_subtotal * tipo_recargo / 100, precision_digits=2)

    def _get_base_coste(self, line):
        if line.product_id and line.quantity:
            return float_round(line.product_id.standard_price * line.quantity, precision_digits=2)
        return 0.0

    def _is_exenta(self, line):
        for tax in line.tax_ids:
            if tax.amount == 0.0:
                return True
        return False
