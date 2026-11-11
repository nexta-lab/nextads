# -*- coding: utf-8 -*-
"""Páginas de firmas y orden SEPA dibujadas con ReportLab.

Se dibujan con coordenadas exactas para colocar encima, en la solicitud de la app Firma,
los campos que rellena y firma cada parte. Todas las medidas están en milímetros desde la
esquina superior izquierda de un A4 (210 x 297 mm), que es como las espera Firma (en fracciones).
"""
import io
import logging

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from odoo import api, models
from odoo.tools.misc import file_path

_logger = logging.getLogger(__name__)

PAGE_W, PAGE_H = 210.0, 297.0
PRIMARY = HexColor('#004F71')
ACCENT = HexColor('#AF5894')
SURFACE = HexColor('#F4F8FA')
BORDER = HexColor('#DCE6EB')
BODY = HexColor('#3C5866')
MUTED = HexColor('#5C7480')

FONTS = {
    'NDS-Regular': 'nds_sale_quote_report/static/fonts/Inter-Regular.ttf',
    'NDS-Medium': 'nds_sale_quote_report/static/fonts/Inter-Medium.ttf',
    'NDS-SemiBold': 'nds_sale_quote_report/static/fonts/Inter-SemiBold.ttf',
    'NDS-Bold': 'nds_sale_quote_report/static/fonts/Inter-Bold.ttf',
    'NDS-Serif': 'nds_sale_quote_report/static/fonts/SourceSerif4-SemiBold.ttf',
}
LOGO = 'nds_sale_quote_report/static/img/nextads-logo-color.png'


def _register_fonts():
    for name, path in FONTS.items():
        if name in pdfmetrics.getRegisteredFontNames():
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, file_path(path)))
        except Exception:  # noqa: BLE001 - si falta una fuente, se usa Helvetica
            _logger.warning("nds_sale_contract_sign: no se pudo cargar la fuente %s", path)


def _font(name):
    return name if name in pdfmetrics.getRegisteredFontNames() else (
        'Helvetica-Bold' if name in ('NDS-Bold', 'NDS-SemiBold', 'NDS-Serif') else 'Helvetica')


class _Page:
    """Ayuda para dibujar en mm desde arriba a la izquierda."""

    def __init__(self, c):
        self.c = c

    def y(self, top_mm):
        return (PAGE_H - top_mm) * mm

    def text(self, x, top, value, font='NDS-Regular', size=9, color=BODY, align='left'):
        self.c.setFillColor(color)
        self.c.setFont(_font(font), size)
        if align == 'right':
            self.c.drawRightString(x * mm, self.y(top), value or '')
        else:
            self.c.drawString(x * mm, self.y(top), value or '')

    def label(self, x, top, value, color=MUTED, align='left', size=6.6, space=0.9):
        """Etiqueta en mayúsculas con espaciado entre letras."""
        value = (value or '').upper()
        font = _font('NDS-SemiBold')
        start = x * mm
        if align == 'right':
            start -= self.c.stringWidth(value, font, size) + space * max(len(value) - 1, 0)
        self.c.setFillColor(color)
        t = self.c.beginText()
        t.setFont(font, size)
        t.setCharSpace(space)
        t.setTextOrigin(start, self.y(top))
        t.textLine(value)
        t.setCharSpace(0)  # el espaciado se queda en el estado del PDF: se deja a cero
        self.c.drawText(t)

    def bullet(self, x, top, color=ACCENT):
        self.c.setFillColor(color)
        self.c.roundRect(x * mm, self.y(top - 0.4), 3.2 * mm, 1.1 * mm, 0.5 * mm, stroke=0, fill=1)

    def checkbox(self, x, top, size=3.4, checked=True, color=PRIMARY):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(0.8)
        self.c.rect(x * mm, self.y(top + size), size * mm, size * mm, stroke=1, fill=0)
        if checked:
            self.c.line((x + 0.7) * mm, self.y(top + 0.7), (x + size - 0.7) * mm, self.y(top + size - 0.7))
            self.c.line((x + 0.7) * mm, self.y(top + size - 0.7), (x + size - 0.7) * mm, self.y(top + 0.7))

    def paragraph(self, x, top, width, value, font='NDS-Regular', size=8.6, leading=12.4, color=BODY):
        """Texto con saltos automáticos. Devuelve la posición (mm) bajo la última línea."""
        self.c.setFillColor(color)
        self.c.setFont(_font(font), size)
        lines = simpleSplit(value or '', _font(font), size, width * mm)
        cur = top
        for line in lines:
            self.c.drawString(x * mm, self.y(cur), line)
            cur += leading / mm
        return cur

    def box(self, x, top, w, h, fill=SURFACE, stroke=None, radius=2.5):
        self.c.setFillColor(fill)
        if stroke:
            self.c.setStrokeColor(stroke)
            self.c.setLineWidth(0.6)
        self.c.roundRect(x * mm, self.y(top + h), w * mm, h * mm, radius * mm,
                         stroke=1 if stroke else 0, fill=1)

    def line(self, x1, top1, x2, top2, color=BORDER, width=0.6):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width)
        self.c.line(x1 * mm, self.y(top1), x2 * mm, self.y(top2))

    def header(self, tag):
        try:
            logo = ImageReader(file_path(LOGO))
            iw, ih = logo.getSize()
            h = 9.0
            w = h * iw / ih
            self.c.drawImage(logo, 18 * mm, self.y(13 + h), w * mm, h * mm, mask='auto')
        except Exception:  # noqa: BLE001
            self.text(18, 20, "Nexta DS", font='NDS-Bold', size=14, color=PRIMARY)
        self.label(192, 19, tag, align='right')
        self.line(18, 25.5, 192, 25.5)

    def footer(self, company):
        legal = company.name or ''
        if company.vat:
            legal += '  ·  NIF %s' % company.vat
        if company.street:
            legal += '  ·  %s' % company.street
        if company.zip or company.city:
            legal += '  ·  %s' % ' '.join(x for x in (company.zip, company.city) if x)
        self.c.setFillColor(MUTED)
        self.c.setFont(_font('NDS-Regular'), 6.4)
        self.c.drawCentredString(105 * mm, self.y(278), legal)
        self.c.setFillColor(ACCENT)
        self.c.rect(0, 0, PAGE_W * mm, 12 * mm, stroke=0, fill=1)
        self.c.setFillColor(white)
        self.c.setFont(_font('NDS-SemiBold'), 7)
        self.c.drawRightString(192 * mm, 4.6 * mm, 'NEXTADS.ES')


def _item(role, kind, name, x, top, w, h, required=True):
    """Campo de Firma en mm (se convierte a fracciones de página al crear la plantilla)."""
    return {
        'role': role, 'type': kind, 'name': name, 'required': required,
        'posX': round(x / PAGE_W, 4), 'posY': round(top / PAGE_H, 4),
        'width': round(w / PAGE_W, 4), 'height': round(h / PAGE_H, 4),
    }


class NdsContractPdf(models.AbstractModel):
    _name = 'nds.contract.pdf'
    _description = "NextaDS: páginas de firmas y orden SEPA"

    # ------------------------------------------------------------------ página de firmas
    @api.model
    def _signature_page(self, order, document_titles):
        """Devuelve (pdf, campos). Los campos van en la página 1 de este PDF."""
        _register_fonts()
        company = order.company_id
        client = order.partner_id.commercial_partner_id
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        p = _Page(c)
        p.header("Documentación · %s" % order.name)

        p.text(18, 40, "FIRMAS", font='NDS-SemiBold', size=8, color=ACCENT)
        p.text(18, 52, "Firma de la documentación", font='NDS-Serif', size=24, color=PRIMARY)
        cur = p.paragraph(
            18, 63, 174,
            "Con su firma en esta página, las partes aceptan íntegramente los documentos siguientes, "
            "que forman parte de este mismo archivo y se refieren al pedido %s:" % order.name,
            size=9.4, leading=14)
        cur += 3
        for title in document_titles:
            p.bullet(19.5, cur - 1.2)
            cur = p.paragraph(27, cur, 165, title, size=9.4, leading=14, color=PRIMARY)
            cur += 1.5
        top = max(cur + 8, 118)

        # Columna NextaDS (izquierda) y cliente (derecha)
        col_w = 84
        left, right = 18, 108
        for x in (left, right):
            p.box(x, top, col_w, 128, fill=SURFACE)
            c.setFillColor(ACCENT)
            c.rect(x * mm, p.y(top + 1.2), col_w * mm, 1.2 * mm, stroke=0, fill=1)

        # NextaDS
        p.label(left + 6, top + 10, "Por")
        p.paragraph(left + 6, top + 16, col_w - 12, (company.name or '').upper(),
                    font='NDS-Bold', size=9, leading=12, color=PRIMARY)
        rep = company.nds_contract_representative or (company.nds_contract_signer_id.name or '')
        rep_title = company.nds_contract_representative_title or ''
        p.text(left + 6, top + 30, rep, font='NDS-Medium', size=9, color=PRIMARY)
        if rep_title:
            p.text(left + 6, top + 35, rep_title[:1].upper() + rep_title[1:], size=8.4, color=MUTED)
        p.label(left + 6, top + 47, "Firma")
        p.box(left + 6, top + 50, col_w - 12, 42, fill=white, stroke=BORDER)
        p.label(left + 6, top + 102, "Fecha")
        p.box(left + 6, top + 105, col_w - 12, 10, fill=white, stroke=BORDER)

        # Cliente
        p.label(right + 6, top + 10, "Por")
        p.paragraph(right + 6, top + 16, col_w - 12, (client.name or '').upper(),
                    font='NDS-Bold', size=9, leading=12, color=PRIMARY)
        p.label(right + 6, top + 27, "Nombre y apellidos")
        p.box(right + 6, top + 29, col_w - 12, 8, fill=white, stroke=BORDER)
        p.label(right + 6, top + 42, "Cargo")
        p.box(right + 6, top + 44, col_w - 12, 8, fill=white, stroke=BORDER)
        p.label(right + 6, top + 57, "Firma")
        p.box(right + 6, top + 59, col_w - 12, 33, fill=white, stroke=BORDER)
        p.label(right + 6, top + 102, "Fecha")
        p.box(right + 6, top + 105, col_w - 12, 10, fill=white, stroke=BORDER)

        p.paragraph(
            18, top + 136, 174,
            "Firma electrónica realizada a través de la aplicación Firma de Odoo. Cada firmante recibe "
            "una copia del documento firmado y su certificado de firma.",
            size=7.6, leading=10.5, color=MUTED)
        p.footer(company)
        c.showPage()
        c.save()

        pad = 1.2
        items = [
            # cliente
            _item('customer', 'name', "Nombre y apellidos", right + 6 + pad, top + 29 + 0.8, col_w - 12 - 2 * pad, 6.4),
            _item('customer', 'text', "Cargo", right + 6 + pad, top + 44 + 0.8, col_w - 12 - 2 * pad, 6.4),
            _item('customer', 'signature', "Firma", right + 6 + pad, top + 59 + pad, col_w - 12 - 2 * pad, 33 - 2 * pad),
            _item('customer', 'date', "Fecha", right + 6 + pad, top + 105 + 1.5, 40, 7),
            # NextaDS
            _item('company', 'signature', "Firma", left + 6 + pad, top + 50 + pad, col_w - 12 - 2 * pad, 42 - 2 * pad),
            _item('company', 'date', "Fecha", left + 6 + pad, top + 105 + 1.5, 40, 7),
        ]
        return buf.getvalue(), items

    # ------------------------------------------------------------------ orden SEPA
    @api.model
    def _sepa_page(self, order, mandate_reference):
        """Orden de domiciliación SEPA CORE. Devuelve (pdf, campos) para la página 1 de este PDF."""
        _register_fonts()
        company = order.company_id
        client = order.partner_id.commercial_partner_id
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        p = _Page(c)
        p.header("Orden SEPA · %s" % order.name)

        p.text(18, 38, "DOMICILIACIÓN BANCARIA", font='NDS-SemiBold', size=8, color=ACCENT)
        p.text(18, 49, "Orden de domiciliación de adeudo directo SEPA", font='NDS-Serif', size=18, color=PRIMARY)
        p.text(18, 55, "SEPA CORE Direct Debit Mandate", size=8.4, color=MUTED)

        # Acreedor
        p.box(18, 61, 174, 39)
        p.label(23, 68, "A cumplimentar por el acreedor")
        rows = [
            ("Referencia de la orden", mandate_reference),
            ("Identificador del acreedor", company.sdd_creditor_identifier or ''),
            ("Nombre del acreedor", (company.name or '').upper()),
            ("Dirección", ', '.join(x for x in (
                company.street, ' '.join(y for y in (company.zip, company.city) if y),
                company.state_id.name, company.country_id.name) if x)),
        ]
        cur = 75
        for label, value in rows:
            p.text(23, cur, label, size=8, color=MUTED)
            p.text(70, cur, value, font='NDS-Medium', size=8.6, color=PRIMARY)
            cur += 6.5

        cur = p.paragraph(
            18, 108, 174,
            "Mediante la firma de esta orden de domiciliación, el deudor autoriza (A) al acreedor a enviar "
            "instrucciones a la entidad del deudor para adeudar su cuenta y (B) a la entidad para efectuar "
            "los adeudos en su cuenta siguiendo las instrucciones del acreedor. Como parte de sus derechos, "
            "el deudor está legitimado al reembolso por su entidad en los términos y condiciones del contrato "
            "suscrito con la misma. La solicitud de reembolso deberá efectuarse dentro de las ocho semanas "
            "que siguen a la fecha de adeudo en cuenta. Puede obtener información adicional sobre sus "
            "derechos en su entidad financiera.",
            size=8, leading=11.2)

        # Deudor
        top = 138
        p.box(18, top, 174, 104)
        p.label(23, top + 7, "A cumplimentar por el deudor")
        address = ', '.join(x for x in (client.street, client.street2) if x)
        city = ' '.join(x for x in (client.zip, client.city) if x)
        region = ' - '.join(x for x in (client.state_id.name, client.country_id.name) if x)
        rows = [
            ("Nombre del deudor", (client.name or '').upper()),
            ("NIF", client.vat or ''),
            ("Dirección", address),
            ("Código postal y población", city),
            ("Provincia y país", region),
        ]
        cur = top + 15
        for label, value in rows:
            p.text(23, cur, label, size=8, color=MUTED)
            p.text(70, cur, value, font='NDS-Medium', size=8.6, color=PRIMARY)
            cur += 6.5

        # Campos que rellena el cliente
        p.label(23, top + 48, "Número de cuenta (IBAN)")
        p.box(23, top + 50, 164, 9, fill=white, stroke=BORDER)
        p.text(23, top + 63.5, "En España el IBAN tiene 24 posiciones y empieza por ES.", size=7, color=MUTED)
        p.label(23, top + 70, "Swift-BIC (opcional)")
        p.box(23, top + 72, 70, 8, fill=white, stroke=BORDER)
        p.label(100, top + 70, "Tipo de pago")
        p.checkbox(100, top + 74.6)
        p.text(105.5, top + 77.5, "Pago recurrente", font='NDS-Medium', size=8.6, color=PRIMARY)
        p.label(23, top + 87, "Localidad")
        p.box(23, top + 89, 70, 8, fill=white, stroke=BORDER)
        p.label(100, top + 87, "Fecha")
        p.box(100, top + 89, 40, 8, fill=white, stroke=BORDER)

        sig_top = top + 111
        p.label(18, sig_top, "Firma del deudor")
        p.box(18, sig_top + 2, 90, 22, fill=white, stroke=BORDER)
        p.paragraph(
            114, sig_top + 5, 78,
            "Todos los campos son obligatorios, salvo el Swift-BIC. Una vez firmada, esta orden queda "
            "custodiada por el acreedor.",
            size=7.4, leading=10, color=MUTED)
        p.footer(company)
        c.showPage()
        c.save()

        pad = 1.0
        items = [
            _item('customer', 'text', "IBAN", 23 + pad, top + 50 + 0.9, 164 - 2 * pad, 7.2),
            _item('customer', 'text', "Swift-BIC", 23 + pad, top + 72 + 0.8, 70 - 2 * pad, 6.4, required=False),
            _item('customer', 'text', "Localidad", 23 + pad, top + 89 + 0.8, 70 - 2 * pad, 6.4),
            _item('customer', 'date', "Fecha", 100 + pad, top + 89 + 0.8, 40 - 2 * pad, 6.4),
            _item('customer', 'signature', "Firma del deudor", 18 + pad, sig_top + 2 + pad, 90 - 2 * pad, 22 - 2 * pad),
        ]
        return buf.getvalue(), items
