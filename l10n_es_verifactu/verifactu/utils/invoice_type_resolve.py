# -*- coding: utf-8 -*-

class VerifactuTipoFacturaResolver(object):
    @staticmethod
    def _get_invoice_type(inv):
        """
        Devuelve el tipo/move_type normalizado ('out_invoice', 'out_refund', 'in_invoice', ...)
        compatible v10→v18.
        """
        # Campo en v13+: move_type; v10–v12: type
        if hasattr(inv, 'move_type'):
            t = inv.move_type
        elif hasattr(inv, 'type'):
            t = inv.type
        else:
            t = None

        # Heurísticos de respaldo por si algún flujo no establece el campo:
        # - En v13+ un abono suele tener reversed_entry_id
        # - En v10–v12 un reembolso suele tener referencia a invoice_id refund
        if not t:
            try:
                if getattr(inv, 'reversed_entry_id', False):
                    # asume cliente
                    return 'out_refund'
                if getattr(inv, 'refund_invoice_id', False):
                    return 'out_refund'
            except Exception:
                pass
        return t or ''

    @staticmethod
    def _partner_vat(partner):
        """Devuelve el VAT normalizado (u'') sin reventar en None."""
        try:
            vat = partner and partner.vat or u""
        except Exception:
            vat = u""
        try:
            vat = vat.strip().upper()
        except Exception:
            # si no es str/unicode
            vat = u""
        return vat

    @staticmethod
    def resolve(invoice):
        """
        Determina el tipo de factura VeriFactu a partir de los datos del move/invoice.
        Reglas:
          - R1: rectificativa de cliente (out_refund)
          - F2: simplificada sin identificación (cliente sin NIF)
          - F1: completa (cliente con NIF)
          - F5: recibida (entrada proveedor) — orientativo
          - Por defecto: F1
        """
        inv_type = VerifactuTipoFacturaResolver._get_invoice_type(invoice)

        # 1) Rectificativas (abonos de cliente)
        if inv_type == 'out_refund':
            return "R1"

        # 2) Emitidas a cliente
        if inv_type == 'out_invoice':
            partner = getattr(invoice, 'partner_id', None)
            vat = VerifactuTipoFacturaResolver._partner_vat(partner)

            # Sin NIF o marcado como SINNIF -> simplificada
            if not vat or vat in ('SINNIF', '-', 'NA', 'N/A'):
                return "F2"

            # Con NIF -> completa
            return "F1"

        # 3) Recibidas (proveedor)
        if inv_type == 'in_invoice':
            # En VeriFactu no suele aplicar, pero dejamos un tipo orientativo
            return "F5"

        # 4) Desconocido -> por defecto completa
        return "F1"
