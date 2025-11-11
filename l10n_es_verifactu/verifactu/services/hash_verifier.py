# -*- coding: utf-8 -*-
from odoo.tools.translate import _
from odoo import release

from ..services.hash_calculator import VerifactuHashCalculator
from ..services.logger import VerifactuLogger


class VerifactuHashVerifier(object):
    """
    Verifica la integridad del encadenamiento VeriFactu:
      • Comprueba que el hash calculado coincide con el último hash ENVIADO (log).
      • Verifica que el prev_hash de cada factura coincida con el último hash ENVIADO de la anterior.
      • Permite encadenamiento alternativo válido (subsanaciones/anulaciones).
    Compatible Odoo 10–18.
    """

    def __init__(self, invoice, config, depth=5):
        self.invoice = invoice
        self.config = config
        self.depth = depth

    # ─────────────────────────────
    # Utilidades
    # ─────────────────────────────
    def _inv_number(self, inv):
        return (
            getattr(inv, 'number', None)
            or getattr(inv, 'name', None)
            or getattr(inv, 'move_name', None)
            or (str(inv.id) if inv else "–")
        )

    def _short(self, h):
        return (h or u"")[:16]

    def _safe_notify(self, inv, level, message):
        """Solo muestra notificación visual (sin chatter)."""
        user = inv.env.user
        try:
            method = getattr(user, f'notify_{level}', None)
            if callable(method):
                method(message=message)
        except Exception:
            pass

    def _last_sent_log(self, inv):
        Log = inv.env["verifactu.status.log"]
        return Log.search([
            ("invoice_id", "=", inv.id),
            ("status", "in", ["sent", "accepted_with_errors", "canceled"])
        ], order="date desc, id desc", limit=1)

    # ─────────────────────────────
    # Verificación principal
    # ─────────────────────────────
    def verify(self):
        inv = self.invoice
        inv.ensure_one()

        domain = [
            ("journal_id", "=", inv.journal_id.id),
            ("state", "in", ["posted", "sent"]),
        ]
        invoices = inv.env["account.move"].search(domain, order="invoice_date desc, id desc", limit=self.depth)
        if not invoices:
            msg = _("No hay facturas suficientes para verificar el encadenamiento.")
            inv.message_post(body=f"🟡 {msg}")
            self._safe_notify(inv, "info", msg)
            return True

        log_lines = []
        ok_chain = True
        prev_doc = None
        last_sent_hash_prev_doc = None

        for idx, doc in enumerate(reversed(invoices), start=1):
            num = self._inv_number(doc)
            calc_hash = VerifactuHashCalculator(doc, self.config).compute_hash() or ""
            last_log = self._last_sent_log(doc)
            last_sent_hash_this_doc = (last_log.hash_actual or "") if last_log else ""
            prev_hash = getattr(doc, "verifactu_previous_hash", "") or ""

            if last_sent_hash_this_doc:
                if calc_hash == last_sent_hash_this_doc:
                    log_lines.append(f"<b>{idx}. {num}:</b> ✅ Coincide con el último hash enviado "
                                     f"(<code>{self._short(calc_hash)}</code>)")
                else:
                    ok_chain = False
                    log_lines.append(f"<b>{idx}. {num}:</b> 🛑 <b>CAMBIO</b> — actual=<code>{self._short(calc_hash)}</code> "
                                     f"último_enviado=<code>{self._short(last_sent_hash_this_doc)}</code>")
                    log_lines.append("<i>⚠️ La factura fue modificada tras su envío a VeriFactu.</i>")
            else:
                log_lines.append(f"<b>{idx}. {num}:</b> 🛈 Sin envíos previos — actual=<code>{self._short(calc_hash)}</code>")

            if last_sent_hash_prev_doc:
                if prev_hash != last_sent_hash_prev_doc:
                    alt = inv.env["verifactu.status.log"].search([("hash_actual", "=", prev_hash)], limit=1)
                    if alt:
                        log_lines.append(f"ℹ️ Encadenamiento alternativo válido: prev_hash="
                                         f"<code>{self._short(prev_hash)}</code> coincide con hash enviado en otra factura.")
                    else:
                        ok_chain = False
                        prev_name = self._inv_number(prev_doc) if prev_doc else "–"
                        log_lines.append(f"⚠️ Ruptura de cadena entre <b>{prev_name}</b> → <b>{num}</b> "
                                         f"(prev_hash=<code>{self._short(prev_hash)}</code> "
                                         f"vs esperado=<code>{self._short(last_sent_hash_prev_doc)}</code>)")

            last_sent_hash_prev_doc = last_sent_hash_this_doc or ""
            prev_doc = doc

        # ─────────────────────────────
        # 3️⃣ Resultado y salida
        # ─────────────────────────────
        summary = (
            "🟢 <b>Cadena de integridad verificada correctamente.</b>"
            if ok_chain
            else "🔴 <b>Se detectaron discrepancias o rupturas en la cadena de hash.</b>"
        )

        html_lines = "<br/>".join(log_lines)
        html_message = f"{summary}<br/><br/>{html_lines}"

        inv.message_post(body=html_message, subtype_xmlid="mail.mt_note")

        if ok_chain:
            self._safe_notify(inv, "success", _("Cadena de integridad verificada correctamente."))
        else:
            hints = "<br/>".join([
                "<b>🧭 Posibles causas:</b>",
                "• Se modificó una factura ya sellada o enviada.",
                "• Falta una factura intermedia en el diario (ruptura de numeración).",
                "• Se restauró una copia antigua de la base de datos.",
                "• Se cambió el certificado o el método de cálculo de hash.",
                "• En casos de subsanación o anulación, el encadenamiento es válido si el prev_hash existe en un envío previo.",
            ])
            inv.message_post(body=f"{summary}<br/><br/>{hints}", subtype_xmlid="mail.mt_note")
            self._safe_notify(inv, "warning", _("Se detectaron discrepancias en la integridad del encadenamiento."))

        return True
