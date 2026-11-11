# -*- coding: utf-8 -*-
import base64
import io
import json
import logging

from markupsafe import Markup, escape

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.pdf import PdfFileReader, merge_pdf

_logger = logging.getLogger(__name__)

MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
          'septiembre', 'octubre', 'noviembre', 'diciembre']

DOC_TITLES = {
    'nda': "Acuerdo de confidencialidad y contrato de encargo del tratamiento (Anexo I)",
    'hosting': "Contrato de servidor y copias de seguridad",
    'support': "Contrato de soporte, mantenimiento y mejoras de Odoo",
    'sepa': "Orden de domiciliación de adeudo directo SEPA",
}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    nds_contract_auto = fields.Boolean(
        string="Enviar documentación al aceptar",
        default=True,
        help="Al aceptar y firmar el presupuesto en el portal, se envía para firmar la documentación "
             "que corresponda (acuerdo de confidencialidad, contratos y orden SEPA).",
    )
    nds_sign_request_id = fields.Many2one(
        'sign.request', string="Documentación para firmar", copy=False, readonly=True, index='btree_not_null')
    nds_sign_state = fields.Selection(related='nds_sign_request_id.state', string="Estado de la firma")
    nds_contract_parts = fields.Char(
        string="Documentos enviados", copy=False, readonly=True,
        help="Documentos incluidos en la solicitud de firma (uso interno).")

    # ------------------------------------------------------------------ qué documentos van
    def _nds_contract_lines(self, contract_type):
        self.ensure_one()
        return self.order_line.filtered(
            lambda l: not l.display_type and l.product_id
            and l.product_id.product_tmpl_id.nds_contract_type == contract_type)

    def _nds_is_recurring(self):
        self.ensure_one()
        if 'is_subscription' in self._fields and self.is_subscription:
            return True
        return any(
            'recurring_invoice' in line.product_id._fields and line.product_id.recurring_invoice
            for line in self.order_line if line.product_id and not line.display_type)

    def _nds_contract_parts(self):
        """Documentos que corresponden a este pedido, en el orden en que se presentan."""
        self.ensure_one()
        client = self.partner_id.commercial_partner_id
        parts = []
        if not client.nds_nda_signed_on:
            parts.append('nda')
        if self._nds_contract_lines('hosting'):
            parts.append('hosting')
        if self._nds_contract_lines('support'):
            parts.append('support')
        if self._nds_is_recurring() and not client._nds_has_active_mandate():
            parts.append('sepa')
        return parts

    def _nds_report_parts(self):
        """Documentos del cuerpo del contrato (sin SEPA). Si ya se envió, los que se enviaron."""
        self.ensure_one()
        parts = json.loads(self.nds_contract_parts) if self.nds_contract_parts else self._nds_contract_parts()
        return [p for p in parts if p in ('nda', 'hosting', 'support')]

    # ------------------------------------------------------------------ textos auxiliares
    @api.model
    def _nds_date_es(self, date):
        return "%d de %s de %d" % (date.day, MONTHS[date.month - 1], date.year)

    def _nds_contract_date_str(self):
        return self._nds_date_es(fields.Date.context_today(self))

    def _nds_partner_address(self, partner):
        city = ' '.join(x for x in (partner.zip, partner.city) if x)
        if partner.state_id:
            city = '%s (%s)' % (city, partner.state_id.name) if city else partner.state_id.name
        return ', '.join(x for x in (partner.street, partner.street2, city) if x)

    def _nds_line_title(self, line):
        """Primera línea útil de la descripción, sin repetir el nombre del producto."""
        pname = line.product_id.display_name or ''
        text = (line.name or '').strip()
        if pname and text.startswith(pname) and text[len(pname):].strip():
            text = text[len(pname):].strip()
        return text.split('\n')[0].strip() or pname

    def _nds_line_period(self, line):
        if 'plan_id' in self._fields and self.plan_id and line.product_id.recurring_invoice:
            return self.plan_id.name
        if 'recurring_invoice' in line.product_id._fields and line.product_id.recurring_invoice:
            return "Cuota recurrente"
        return "Pago único"

    def _nds_mandate_reference(self):
        self.ensure_one()
        client = self.partner_id.commercial_partner_id
        ref = 'NDS-%s-%s' % (client.id, self.name)
        return ''.join(ch for ch in ref if ch.isalnum() or ch in '+/-')[:35]

    # ------------------------------------------------------------------ PDF y solicitud de firma
    def _nds_build_contract_pdf(self, parts):
        """PDF único con los documentos y la lista de campos de Firma (con su página)."""
        self.ensure_one()
        pdfs, items, titles = [], [], []
        pages = 0
        body_parts = [p for p in parts if p in ('nda', 'hosting', 'support')]
        if body_parts:
            body = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
                'nds_sale_contract_sign.action_report_nds_contract', self.ids)[0]
            pdfs.append(body)
            pages += len(PdfFileReader(io.BytesIO(body), strict=False).pages)
            titles = [DOC_TITLES[p] for p in body_parts]
            sig_pdf, sig_items = self.env['nds.contract.pdf']._signature_page(self, titles)
            pdfs.append(sig_pdf)
            pages += 1
            items += [dict(item, page=pages) for item in sig_items]
        if 'sepa' in parts:
            sepa_pdf, sepa_items = self.env['nds.contract.pdf']._sepa_page(self, self._nds_mandate_reference())
            pdfs.append(sepa_pdf)
            pages += 1
            items += [dict(item, page=pages) for item in sepa_items]
            titles.append(DOC_TITLES['sepa'])
        pdf = pdfs[0] if len(pdfs) == 1 else merge_pdf(pdfs)
        return pdf, items, titles

    def _nds_sign_refs(self):
        ref = lambda xmlid: self.env.ref(xmlid, raise_if_not_found=False)  # noqa: E731
        Role = self.env['sign.item.role'].sudo()
        # En Firma 18 el rol de la empresa que envía es «User» (sign_item_role_user)
        roles = {
            'customer': ref('sign.sign_item_role_customer') or Role.search([('name', '=', 'Customer')], limit=1),
            'company': ref('sign.sign_item_role_user') or Role.search([('name', '=', 'User')], limit=1),
        }
        types = {
            'signature': ref('sign.sign_item_type_signature'),
            'name': ref('sign.sign_item_type_name'),
            'text': ref('sign.sign_item_type_text'),
            'date': ref('sign.sign_item_type_date'),
        }
        missing = [k for k, v in {**roles, **types}.items() if not v]
        if missing:
            raise UserError(_("Falta configuración de la app Firma: %s", ', '.join(missing)))
        return roles, types

    def _nds_create_sign_request(self, pdf, items, titles, parts):
        self.ensure_one()
        company = self.company_id
        signer = self.partner_id
        if not signer.email:
            raise UserError(_("El cliente del presupuesto (%s) no tiene correo electrónico: "
                              "no se le puede enviar la documentación para firmar.", signer.display_name))
        roles, types = self._nds_sign_refs()
        needs_company = any(item['role'] == 'company' for item in items)
        company_user = company.nds_contract_signer_id or self.user_id
        if needs_company and not company_user.partner_id.email:
            raise UserError(_("Falta el firmante de la empresa (Ajustes de Ventas › Contratos)."))

        filename = "%s - Documentación para firmar.pdf" % self.name
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': base64.b64encode(pdf),
            'mimetype': 'application/pdf',
        })
        template = self.env['sign.template'].sudo().create({'attachment_id': attachment.id})
        if 'name' in template._fields and not template.name:
            template.name = filename
        item_vals = []
        for item in items:
            vals = {
                'template_id': template.id,
                'type_id': types[item['type']].id,
                'responsible_id': roles[item['role']].id,
                'required': item['required'],
                'page': item['page'],
                'posX': item['posX'],
                'posY': item['posY'],
                'width': item['width'],
                'height': item['height'],
                'name': item['name'],
            }
            if 'placeholder' in self.env['sign.item']._fields:
                vals['placeholder'] = item['name']
            item_vals.append(vals)
        self.env['sign.item'].sudo().create(item_vals)

        request_items = [Command.create({
            'partner_id': signer.id,
            'role_id': roles['customer'].id,
            'mail_sent_order': 1,
        })]
        if needs_company:
            request_items.append(Command.create({
                'partner_id': company_user.partner_id.id,
                'role_id': roles['company'].id,
                'mail_sent_order': 2,
            }))
        vals = {
            'template_id': template.id,
            'reference': "%s · Documentación para firmar" % self.name,
            'request_item_ids': request_items,
        }
        Request = self.env['sign.request'].sudo()
        if 'reference_doc' in Request._fields:
            vals['reference_doc'] = 'sale.order,%s' % self.id
        if 'subject' in Request._fields:
            vals['subject'] = "%s · Documentación para firmar" % self.name
        if 'message' in Request._fields:
            vals['message'] = Markup("<p>%s</p>") % "Documentación del pedido %s: %s." % (
                self.name, ', '.join(t.lower() for t in titles))
        request = Request.with_context(no_sign_mail=True).create(vals)
        self.write({
            'nds_sign_request_id': request.id,
            'nds_contract_parts': json.dumps(parts),
        })
        return request

    def _nds_customer_sign_item(self):
        self.ensure_one()
        request = self.sudo().nds_sign_request_id
        if not request:
            return self.env['sign.request.item']
        return request.request_item_ids.filtered(lambda i: i.partner_id == self.partner_id)[:1] \
            or request.request_item_ids.sorted('mail_sent_order')[:1]

    def _nds_customer_sign_url(self):
        """Enlace para que firme el cliente (el mismo que enviaría la app Firma por correo)."""
        self.ensure_one()
        item = self._nds_customer_sign_item().sudo()
        if not item:
            return False
        url = item.access_url if 'access_url' in item._fields else False
        if not url:
            url = '/sign/document/mail/%s/%s' % (item.sign_request_id.id, item.access_token)
        if url.startswith('/'):
            url = self.get_base_url() + url
        return url

    def _nds_customer_has_to_sign(self):
        self.ensure_one()
        item = self._nds_customer_sign_item()
        return bool(item) and item.sign_request_id.state == 'sent' and item.state != 'completed'

    def _nds_post_sign_message(self, titles):
        self.ensure_one()
        url = self._nds_customer_sign_url()
        docs = Markup('').join(Markup('<li>%s</li>') % t for t in titles)
        body = Markup(
            "<p>Gracias por aceptar el presupuesto. Para empezar, falta firmar esta documentación:</p>"
            "<ul>%s</ul>"
            "<p><a href=\"%s\" style=\"display:inline-block;padding:10px 18px;border-radius:6px;"
            "background:#AF5894;color:#ffffff;text-decoration:none;font-weight:600\">Revisar y firmar</a></p>"
            "<p>Se firma en línea, sin imprimir nada. Si tenéis cualquier duda, respondednos aquí mismo.</p>"
        ) % (docs, url)
        author = (self.user_id or self.env.user).partner_id
        self.message_post(
            body=body,
            author_id=author.id,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=self.partner_id.ids,
        )

    def _nds_send_contract(self):
        """Prepara y envía la documentación. Devuelve la solicitud de firma o False si no hay nada."""
        self.ensure_one()
        parts = self._nds_contract_parts()
        if not parts:
            return False
        pdf, items, titles = self._nds_build_contract_pdf(parts)
        self._nds_create_sign_request(pdf, items, titles, parts)
        self._nds_post_sign_message(titles)
        return self.nds_sign_request_id

    def _nds_send_contract_safe(self):
        """Envío automático tras la aceptación: un error nunca impide que el cliente acepte."""
        for order in self:
            user = order.user_id or order.company_id.nds_contract_signer_id or self.env.ref('base.user_admin')
            try:
                with self.env.cr.savepoint():
                    order.with_user(user).sudo().with_company(order.company_id)._nds_send_contract()
            except Exception as error:  # noqa: BLE001
                _logger.exception("nds_sale_contract_sign: no se pudo enviar la documentación de %s", order.name)
                order.sudo().message_post(
                    body=Markup("<p><b>No se ha podido preparar la documentación para firmar.</b> %s</p>"
                                "<p>Revisadlo y usad el botón «Enviar documentación para firmar».</p>")
                    % escape(str(error)),
                    message_type='notification',
                    subtype_xmlid='mail.mt_note',
                )

    def _validate_order(self):
        res = super()._validate_order()
        to_send = self.filtered(
            lambda o: o.state == 'sale' and o.signature and o.nds_contract_auto and not o.nds_sign_request_id)
        if to_send:
            to_send._nds_send_contract_safe()
        return res

    # ------------------------------------------------------------------ botones
    def action_nds_send_contract(self):
        self.ensure_one()
        if self.nds_sign_request_id and self.nds_sign_request_id.state in ('sent', 'signed'):
            raise UserError(_("Este pedido ya tiene documentación enviada (%s).",
                              self.nds_sign_request_id.reference or self.nds_sign_request_id.display_name))
        request = self._nds_send_contract()
        if not request:
            raise UserError(_("No hay documentación que enviar: el cliente ya tiene firmado el acuerdo de "
                              "confidencialidad, el presupuesto no lleva servicios con contrato y no hace "
                              "falta orden SEPA."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Documentación enviada para firmar. El enlace está en el historial del pedido."),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_nds_open_sign_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sign.request',
            'res_id': self.nds_sign_request_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------ tras la firma
    def _nds_after_contract_signed(self, request):
        """Adjunta el PDF firmado, anota el acuerdo de confidencialidad y prepara el mandato SEPA."""
        self.ensure_one()
        order = self.sudo()
        parts = json.loads(order.nds_contract_parts or '[]')
        client = order.partner_id.commercial_partner_id
        today = fields.Date.context_today(order)

        attachments = self.env['ir.attachment']
        if 'completed_document_attachment_ids' in request._fields:
            attachments = request.completed_document_attachment_ids
        if not attachments and hasattr(request, '_generate_completed_document'):
            request._generate_completed_document()
            if 'completed_document_attachment_ids' in request._fields:
                attachments = request.completed_document_attachment_ids
        copies = self.env['ir.attachment']
        for attachment in attachments:
            copies |= attachment.copy({'res_model': 'sale.order', 'res_id': order.id})
        order.message_post(
            body=Markup("<p>Documentación firmada por todas las partes. Se adjunta el documento firmado.</p>"),
            attachment_ids=copies.ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        if 'nda' in parts and not client.nds_nda_signed_on:
            client.nds_nda_signed_on = today

        if 'sepa' in parts:
            order._nds_create_mandate_from_request(request, copies[:1])

    def _nds_signed_value(self, request, name):
        values = request.request_item_ids.sudo().mapped('sign_item_value_ids')
        value = values.filtered(lambda v: v.sign_item_id.name == name)[:1]
        return (value.value or '').strip() if value else ''

    def _nds_create_mandate_from_request(self, request, signed_attachment):
        self.ensure_one()
        client = self.partner_id.commercial_partner_id
        iban = ''.join(self._nds_signed_value(request, 'IBAN').split()).upper()
        if not iban:
            self.message_post(body=_("La orden SEPA está firmada pero no se ha encontrado el IBAN: "
                                     "cread el mandato a mano desde el documento firmado."),
                              subtype_xmlid='mail.mt_note')
            return
        Bank = self.env['res.partner.bank'].sudo()
        bank = Bank.search([('partner_id', 'child_of', client.id), ('acc_number', '=', iban)], limit=1) \
            or Bank.search([('partner_id', 'child_of', client.id)]).filtered(
                lambda b: (b.sanitized_acc_number or '').upper() == iban)[:1]
        if not bank:
            bank = Bank.create({'partner_id': client.id, 'acc_number': iban, 'allow_out_payment': True}
                               if 'allow_out_payment' in Bank._fields else
                               {'partner_id': client.id, 'acc_number': iban})
        mandate_vals = {
            'partner_id': client.id,
            'partner_bank_id': bank.id,
            'start_date': fields.Date.context_today(self),
            'one_off': False,
            'company_id': self.company_id.id,
        }
        Mandate = self.env['sdd.mandate'].sudo()
        if 'name' in Mandate._fields:
            mandate_vals['name'] = self._nds_mandate_reference()
        if signed_attachment and 'mandate_pdf_file' in Mandate._fields:
            mandate_vals['mandate_pdf_file'] = signed_attachment.datas
        mandate = Mandate.create(mandate_vals)
        if hasattr(mandate, 'activity_schedule'):
            mandate.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_("Validar mandato SEPA firmado (%s)", self.name),
                note=_("El cliente ha firmado la orden SEPA en línea. Revisad el IBAN y validad el mandato."),
                user_id=(self.user_id or self.env.user).id,
            )
        self.message_post(
            body=Markup("<p>Orden SEPA firmada: creado el mandato <b>%s</b> en borrador para validarlo.</p>")
            % (mandate.display_name,),
            subtype_xmlid='mail.mt_note',
        )
