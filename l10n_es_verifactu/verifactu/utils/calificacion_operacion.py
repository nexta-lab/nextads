from odoo import _

class VerifactuOperacionClassifier:
    """
    Clasifica una factura según la CalificacionOperacion para VeriFactu:

    - S1: Sujeta no exenta
    - S2: Sujeta exenta
    - N1: No sujeta (regla interna)
    - N2: No sujeta (regla internacional)
    """

    @staticmethod
    def compute(invoice):
        partner = invoice.partner_id
        partner_country = (partner.country_id.code or "").strip().upper()
        vat = (partner.vat or "").strip().upper()
        taxes = invoice.invoice_line_ids.mapped("tax_ids")

        # Fallback: deducir país si no está definido pero el NIF empieza por ES
        if not partner_country and vat.startswith("ES"):
            partner_country = "ES"

        # Caso internacional: cliente fuera de España
        if partner_country and partner_country != "ES":
            return "N2"

        # Exenta explícita: todas las líneas con IVA 0 y descripción 'exento'
        if all(
            t.amount == 0 and "exento" in (t.description or "").lower()
            for t in taxes
        ):
            return "S2"

        # Sujeta: al menos un impuesto con tipo > 0
        if any(t.amount > 0 for t in taxes):
            return "S1"

        # Nacional sin impuestos: posiblemente no sujeta
        if not taxes or all(t.amount == 0 for t in taxes):
            return "N1"

        # Fallback de seguridad
        return "S1"  # <-- CORREGIDO: no devuelvas tupla


    @staticmethod
    def compute_from_line(line):
        partner = line.move_id.partner_id
        partner_country = (partner.country_id.code or "").strip().upper()
        vat = (partner.vat or "").strip().upper()
        taxes = line.tax_ids

        # Fallback: deducir país si no está definido pero el NIF empieza por ES
        if not partner_country and vat.startswith("ES"):
            partner_country = "ES"

        # Internacional (cliente fuera de España)
        if partner_country and partner_country != "ES":
            return "N2"

        # Si tiene impuestos, analizamos su contenido
        if taxes:
            # Exenta explícita
            if all(t.amount == 0 and "exento" in (t.description or "").lower() for t in taxes):
                return "S2"
            # Sujeta no exenta
            if any(t.amount > 0 for t in taxes):
                return "S1"
            # Impuestos al 0% sin indicar exención
            return "N1"

        # ⚠️ Línea sin ningún impuesto asignado
        description = (line.name or "").lower()
        if "exento" in description or "exención" in description:
            return "S2"  # Inferimos que el usuario quiso marcarla como exenta

        return "N1"  # Default conservador: no sujeta nacional

