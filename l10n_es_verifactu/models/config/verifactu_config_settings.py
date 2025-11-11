# -*- coding: utf-8 -*-
# models/res_config_settings.py
# Desarrollado por Juan Ormaechea (Mr. Rubik) — Odoo Proprietary License v1.0

import requests
import pytz
from datetime import timedelta
from odoo import _, models, fields, api, release
from odoo.exceptions import UserError

REQUEST_TIMEOUT = 8
PARAM_KEY = 'verifactu.declaracion_attachment_id'


# ───────────────────────── Helpers de compatibilidad ─────────────────────────

def _odoo_major():
    try:
        return int(str(getattr(release, 'major_version', '') or release.version).split('.')[0])
    except Exception:
        return 13


def _is_modern(env):
    try:
        major = int(str(getattr(release, 'major_version', '') or release.version).split('.')[0])
    except Exception:
        major = 13 if hasattr(env, 'company') else 12
    return major >= 13


def _notify_success(env, title, message, sticky=False):
    if _is_modern(env):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': 'success', 'sticky': bool(sticky)},
        }
    return {'effect': {'fadeout': 'slow', 'message': u"%s\n%s" % (title or '', message or ''), 'type': 'rainbow_man'}}


def _notify_error(env, title, message, sticky=True):
    if _is_modern(env):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': 'danger', 'sticky': bool(sticky)},
        }
    raise UserError(u"%s\n%s" % (title or _("Error"), message or ""))


def _get_company(env):
    # Prioriza la compañía activa del contexto; si no existe (v10-12), cae a la del usuario
    return getattr(env, 'company', None) or env.user.company_id



# ───────────────────── Mixin ABSTRACTO (v11→18) ─────────────────────

class VerifactuSettingsMixin(models.AbstractModel):
    _name = 'verifactu.settings.mixin'
    _description = 'Mixin de ajustes VeriFactu'
    _auto = False



# ───────────────────── Clase principal (res.config.settings) ─────────────────────
class VerifactuResConfigSettings(models.TransientModel):
    _name = 'res.config.settings'
    _inherit = ['res.config.settings', 'verifactu.settings.mixin']
    _description = 'Ajustes VeriFactu (res.config.settings)'

    # --- CRON / reintentos / ritmo (periódico) ---
    cron_batch_size = fields.Integer(string="Tamaño de lote (batch)", default=5,
                                     help="Máximo de facturas por pasada del cron.")
    retry_backoff_min = fields.Integer(string="Backoff base (min)", default=10,
                                       help="Minutos para el primer reintento; luego crece exponencialmente.")
    retry_backoff_cap_min = fields.Integer(string="Backoff tope (min)", default=60,
                                           help="Tope máximo de espera entre reintentos por factura.")
    request_min_interval_sec = fields.Integer(string="Intervalo mínimo entre envíos (s)", default=60,
                                              help="Margen mínimo entre peticiones al portal por compañía (rate-limit).")

    # --- CRON DIARIO (a una hora fija) ---
    daily_auto_send_enabled = fields.Boolean(string="Activar envío diario a una hora", default=False,
                                             help="Si está activado, se ejecutará un CRON diario a la hora indicada.")
    daily_send_time = fields.Char(string="Hora diaria (HH:MM)", default="03:00",
                                  help="Hora local de la compañía (formato HH:MM).")

    # --- Parámetros PROPIOS del CRON diario ---
    daily_use_custom_params = fields.Boolean(string="Usar parámetros propios en el envío diario", default=False,
                                             help="Si está activo, el cron diario usará estos parámetros en lugar de los del cron periódico.")
    daily_cron_batch_size = fields.Integer(string="Tamaño de lote (diario)", default=5,
                                           help="Máximo de facturas por pasada del cron diario.")
    daily_retry_backoff_min = fields.Integer(string="Backoff base (min) diario", default=10,
                                             help="Minutos para el primer reintento en el cron diario; luego crece exponencialmente.")
    daily_retry_backoff_cap_min = fields.Integer(string="Backoff tope (min) diario", default=60,
                                                 help="Tope máximo de espera entre reintentos por factura en el cron diario.")
    daily_request_min_interval_sec = fields.Integer(string="Intervalo mínimo entre envíos (s) diario", default=60,
                                                    help="Margen mínimo entre peticiones al portal por compañía en el cron diario (rate-limit).")

    # --- Config VeriFactu existente ---
    endpoint_url = fields.Char("URL del endpoint VeriFactu")
    show_qr_always = fields.Boolean("Mostrar siempre el QR")
    auto_send_to_verifactu = fields.Boolean("Envío automático al validar")
    cron_auto_send_enabled = fields.Boolean("Activar envío periódico")

    # Certificado
    cert_password = fields.Char("Contraseña del certificado")
    cert_pfx = fields.Binary("Certificado PFX", attachment=True)
    cert_pfx_filename = fields.Char("Nombre del archivo PFX", readonly=True)

    # Sistema Informático
    verifactu_system_name = fields.Char("Nombre del Sistema Informático")
    verifactu_system_id = fields.Char("ID del Sistema Informático")
    verifactu_system_version = fields.Char("Versión del Sistema")
    verifactu_system_installation_number = fields.Char("Número de Instalación")
    verifactu_system_use_only_verifactu = fields.Selection([('S', 'Sí'), ('N', 'No')], string="Solo uso VeriFactu")
    verifactu_system_multi_ot = fields.Selection([('S', 'Sí'), ('N', 'No')], string="Multi OT posible")
    verifactu_system_multiple_ot_indicator = fields.Selection([('S', 'Sí'), ('N', 'No')], string="Indicador múltiples OT")

    # --- Licencia ---
    verifactu_license_key = fields.Char(string="Clave de licencia")
    verifactu_license_token = fields.Text(string="Token de licencia (JWT)", readonly=True)
    verifactu_license_status = fields.Selection(
        [("valid", "Válida"), ("grace", "Gracia"), ("invalid", "Inválida"), ("expired", "Expirada")],
        string="Estado de licencia", readonly=True)
    verifactu_license_server_url = fields.Char(
        string="URL del servidor de licencias",
        help="Servicio HTTPS que emite y firma los tokens de licencia (JWT).",
        default="https://us-central1-verifactu-7fc70.cloudfunctions.net/issueLicense")
    verifactu_update_feed_url = fields.Char(
        string="URL del feed de actualizaciones",
        default="https://firebasestorage.googleapis.com/v0/b/verifactu-7fc70.firebasestorage.app/o/latest.json?alt=media&token=1ad6b4a7-4b7e-4bde-bba9-ac7c2ca995e1")
    verifactu_updates_cron_enabled = fields.Boolean(
        string="Activar comprobación periódica de actualizaciones",
        help="Si está activado, se revisará el feed y se notificará cuando haya nueva versión.")
    verifactu_license_token_display = fields.Char(string="Token (JWT)", readonly=True)
    verifactu_update_link = fields.Char(string="Link descarga actualización", readonly=True,
                                        default="https://mrrubik.com/descargas/verifactu/modules/v16ACV876D/l10n_es_verifactu.zip")

    # Declaración responsable
    verifactu_declaracion_file = fields.Binary(string="Declaración Responsable", attachment=True)
    verifactu_declaracion_filename = fields.Char(string="Nombre del archivo")
    verifactu_declaracion_has_attachment = fields.Boolean(
        string="Hay adjunto", compute="_compute_declaracion_has_attachment")

    # Modo VeriFactu / No VeriFactu
    verifactu_mode_enabled = fields.Boolean(
        string="Modo VeriFactu",
        default=False,
        help="Activa el envío directo de facturas al sistema VeriFactu.")
    no_verifactu_mode_enabled = fields.Boolean(
        string="Modo No VeriFactu",
        default=True,
        help="Activa el modo de remisión bajo requerimiento.")
    verifactu_mode_activation_date = fields.Datetime(string="Fecha de activación del modo actual", readonly=True)
    last_verifactu_mode = fields.Selection(
        [('verifactu', 'VeriFactu'), ('no_verifactu', 'No VeriFactu')],
        string="Último modo activo", readonly=True)

    # Histórico (solo lectura; lo rellenamos vía compute para que no “ensucie” inverse)
    verifactu_mode_history_ids = fields.One2many(
        'verifactu.mode.history', 'company_id',
        compute='_compute_verifactu_mode_history',
        string="Histórico de modos", readonly=True)

    # anomalias
    vf_anomaly_cron_enabled = fields.Boolean(string="Activar detección global de anomalías")
    vf_anomaly_stale_days = fields.Integer(string="Días para marcar 'pendiente'", default=7)
    vf_anomaly_make_activity = fields.Boolean(string="Crear actividad de revisión", default=False)

    # Listado (solo lectura) de anomalías recientes de la compañía
    verifactu_anomaly_ids = fields.One2many(
        'verifactu.anomaly', 'company_id',
        string="Anomalías recientes",
        compute='_compute_verifactu_anomalies',
        readonly=True,
    )
    
    company_id = fields.Many2one(
    'res.company',
    string='Compañía',
    default=lambda self: self.env.company,
    )

    

    @api.depends()
    def _compute_verifactu_anomalies(self):
        Anom = self.env['verifactu.anomaly'].sudo()
        for rec in self:
            rec.verifactu_anomaly_ids = Anom.search([
                ('company_id', '=', rec.env.company.id),
                ('resolved', '=', False),
            ], order='detected_at desc', limit=20)

    # ---------- Helpers de compatibilidad ----------
    @api.model
    def _company(self):
        # Compat Odoo 10–18
        return _get_company(self.env)

    # Carga de histórico (solo UI; no escribe inverse)
    @api.depends()
    def _compute_verifactu_mode_history(self):
        History = self.env['verifactu.mode.history'].sudo()
        for rec in self:
            rec.verifactu_mode_history_ids = History.search(
                [('company_id', '=', rec._company().id)],
                order='change_date desc'
            )

    # ───────────── Validación y coherencia UI (NO persiste) ─────────────
    @api.onchange('verifactu_mode_enabled', 'no_verifactu_mode_enabled')
    def _onchange_mode_toggle(self):
        """Solo UI: fuerza exclusividad y aplica regla del año al intentar pasar a No VeriFactu."""
        if not self.id:
            # Si aún no está guardado, es una carga inicial → no aplicar restricciones
            return

        # Exclusión simple
        if self.verifactu_mode_enabled:
            self.no_verifactu_mode_enabled = False
        elif self.no_verifactu_mode_enabled:
            self.verifactu_mode_enabled = False

        # Regla del año (solo cuando el usuario cambia manualmente)
        if self.no_verifactu_mode_enabled:
            ICP = self.env['ir.config_parameter'].sudo()
            last_mode = ICP.get_param('l10n_es_verifactu.last_verifactu_mode')
            activation_date_str = ICP.get_param('l10n_es_verifactu.verifactu_mode_activation_date')
            activation_date = None
            if activation_date_str:
                try:
                    activation_date = fields.Datetime.from_string(activation_date_str)
                except Exception:
                    activation_date = None

            if last_mode == 'verifactu' and activation_date:
                delta = fields.Datetime.now() - activation_date
                if delta < timedelta(days=365):
                    self.no_verifactu_mode_enabled = False
                    self.verifactu_mode_enabled = True
                    return {
                        'warning': {
                            'title': _("Cambio no permitido"),
                            'message': _(
                                "No puedes volver al modo No VeriFactu hasta que haya pasado un año desde su activación (%s)."
                            ) % activation_date.strftime('%Y-%m-%d'),
                        }
                    }

                    
    @api.onchange('auto_send_to_verifactu', 'verifactu_mode_enabled')
    def _onchange_auto_send_guard(self):
        """No permitir activar auto_send_to_verifactu si NO está activo el modo VeriFactu."""
        if getattr(self, 'auto_send_to_verifactu', False) and not getattr(self, 'verifactu_mode_enabled', False):
            # revertimos el checkbox y avisamos
            self.auto_send_to_verifactu = False
            return {
                'warning': {
                    'title': _("Opción no disponible en 'No VeriFactu'"),
                    'message': _(
                        "No puedes activar 'Envío automático a Veri*Factu' si el modo VeriFactu está desactivado."
                    ),
                }
            }

    # ───────────── GET / SET VALUES ─────────────
    @api.model
    def get_values(self):
        try:
            res = super().get_values()
        except AttributeError:
            res = {}
        res.update(self._vf_get_values_dict())
        return res

    def set_values(self):
        try:
            super().set_values()
        except AttributeError:
            pass
        self._vf_write_config_from_self()

    # ───────────── Helpers TZ/nextcall (para CRON diario) ─────────────
    @api.model
    def _company_tz(self):
        tz = (self.env.user.company_id.tz or
              getattr(getattr(self.env, 'company', None), 'tz', None) or
              'UTC')
        try:
            return pytz.timezone(tz)
        except Exception:
            return pytz.UTC

    @api.model
    def _compute_daily_nextcall_utc(self, hhmm):
        try:
            hh, mm = (hhmm or '03:00').split(':')
            hh = int(hh); mm = int(mm)
        except Exception:
            hh, mm = 3, 0

        tz = self._company_tz()
        now_utc = fields.Datetime.now()
        now_local = pytz.UTC.localize(now_utc).astimezone(tz)
        run_local = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if run_local <= now_local:
            run_local = run_local + timedelta(days=1)
        run_utc = run_local.astimezone(pytz.UTC).replace(tzinfo=None)
        return fields.Datetime.to_string(run_utc)

    # ---------- Acciones UI (declaración responsable) ----------
    def _compute_declaracion_has_attachment(self):
        icp = self.env['ir.config_parameter'].sudo()
        att_id = icp.get_param(PARAM_KEY)
        for rec in self:
            rec.verifactu_declaracion_has_attachment = bool(att_id)

    def action_download_declaracion(self):
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        att_id = ICP.get_param(PARAM_KEY)
        if not att_id:
            if not self.verifactu_declaracion_file:
                return _notify_error(self.env, "Declaración", _("No hay documento cargado aún."))
            att = self.env['ir.attachment'].sudo().create({
                'name': self.verifactu_declaracion_filename or 'Declaracion_Responsable.pdf',
                'datas': self.verifactu_declaracion_file,
                'mimetype': 'application/pdf',
                'public': True,
            })
            ICP.set_param(PARAM_KEY, str(att.id))
            att_id = att.id

        filename = self.verifactu_declaracion_filename or 'Declaracion_Responsable.pdf'
        return {
            'type': 'ir.actions.act_url',
            'target': 'self',
            'url': "/web/content/%s?download=1&filename=%s" % (int(att_id), filename),
        }

    # ---------- LOAD / SAVE (ajustes) ----------
    @api.model
    def _vf_get_values_dict(self):
        company = getattr(self, 'company_id', None) or self.env.company
        Config = self.env['verifactu.endpoint.config'].sudo().with_company(company)
        config = Config.get_singleton_record()

        Lic = self.env["verifactu.license"].sudo().with_company(company)
        lic = Lic.get_singleton_record()

        icp = self.env['ir.config_parameter'].sudo()

        res = {
            # Config core
            'endpoint_url': config.endpoint_url,
            'show_qr_always': config.show_qr_always,
            'auto_send_to_verifactu': config.auto_send_to_verifactu,
            'cron_auto_send_enabled': config.cron_auto_send_enabled,
            'cert_password': config.cert_password,
            'cert_pfx': config.cert_pfx,
            'cert_pfx_filename': config.cert_pfx_filename,
            # Sistema Informático
            'verifactu_system_name': config.verifactu_system_name,
            'verifactu_system_id': config.verifactu_system_id,
            'verifactu_system_version': config.verifactu_system_version,
            'verifactu_system_installation_number': config.verifactu_system_installation_number,
            'verifactu_system_use_only_verifactu': config.verifactu_system_use_only_verifactu,
            'verifactu_system_multi_ot': config.verifactu_system_multi_ot,
            'verifactu_system_multiple_ot_indicator': config.verifactu_system_multiple_ot_indicator,
            # Modos
            'verifactu_mode_enabled': config.verifactu_mode_enabled,
            'no_verifactu_mode_enabled': config.no_verifactu_mode_enabled,
            # Periódico
            'cron_batch_size': getattr(config, 'cron_batch_size', 5),
            'retry_backoff_min': getattr(config, 'retry_backoff_min', 10),
            'retry_backoff_cap_min': getattr(config, 'retry_backoff_cap_min', 60),
            'request_min_interval_sec': getattr(config, 'request_min_interval_sec', 60),
            # Diario
            'daily_auto_send_enabled': getattr(config, 'daily_auto_send_enabled', False),
            'daily_send_time': getattr(config, 'daily_send_time', '03:00'),
            'daily_use_custom_params': getattr(config, 'daily_use_custom_params', False),
            'daily_cron_batch_size': getattr(config, 'daily_cron_batch_size', 5),
            'daily_retry_backoff_min': getattr(config, 'daily_retry_backoff_min', 10),
            'daily_retry_backoff_cap_min': getattr(config, 'daily_retry_backoff_cap_min', 60),
            'daily_request_min_interval_sec': getattr(config, 'daily_request_min_interval_sec', 60),
            # Lectura ICP (último modo / fecha)
            'last_verifactu_mode': icp.get_param('l10n_es_verifactu.last_verifactu_mode'),
            'verifactu_mode_activation_date': icp.get_param('l10n_es_verifactu.verifactu_mode_activation_date'),
            # Licencia
            "verifactu_license_key": lic.license_key,
            "verifactu_license_token": lic.license_token,
            "verifactu_license_status": lic.license_status,
            "verifactu_update_feed_url": lic.update_feed_url,
            "verifactu_license_server_url": lic.verifactu_license_server_url,
            "verifactu_updates_cron_enabled": lic.updates_cron_enabled,
            "verifactu_license_token_display": lic.license_token_display,
            # Anomalias
            'vf_anomaly_cron_enabled': bool(getattr(config, 'anomaly_cron_enabled', False)),
            'vf_anomaly_stale_days': int(getattr(config, 'anomaly_stale_days', 7) or 7),
            'vf_anomaly_make_activity': bool(getattr(config, 'anomaly_make_activity', False)),
        }
        return res

    def _vf_write_config_from_self(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        Config = self.env['verifactu.endpoint.config'].sudo().with_company(company)
        config = Config.get_singleton_record()
        ICP = self.env['ir.config_parameter'].sudo()

        # Determinar modo previo y nuevo (exclusividad simple)
        prev_mode = config.last_verifactu_mode or ('verifactu' if config.verifactu_mode_enabled else 'no_verifactu')
        vf_in = bool(self.verifactu_mode_enabled)
        nvf_in = bool(self.no_verifactu_mode_enabled)
        if vf_in and nvf_in:
            nvf_in = False
        new_mode = 'verifactu' if vf_in else 'no_verifactu'

        # Guardar configuración core en el singleton
        config.write({
            'endpoint_url': self.endpoint_url,
            'show_qr_always': self.show_qr_always,
            'auto_send_to_verifactu': self.auto_send_to_verifactu,
            'cron_auto_send_enabled': self.cron_auto_send_enabled,
            'cert_password': self.cert_password,
            'cert_pfx': self.cert_pfx,
            'cert_pfx_filename': self.cert_pfx_filename,
            # Sistema Informático
            'verifactu_system_name': self.verifactu_system_name,
            'verifactu_system_id': self.verifactu_system_id,
            'verifactu_system_version': self.verifactu_system_version,
            'verifactu_system_installation_number': self.verifactu_system_installation_number,
            'verifactu_system_use_only_verifactu': self.verifactu_system_use_only_verifactu,
            'verifactu_system_multi_ot': self.verifactu_system_multi_ot,
            'verifactu_system_multiple_ot_indicator': self.verifactu_system_multiple_ot_indicator,
            # Modos
            'verifactu_mode_enabled': vf_in,
            'no_verifactu_mode_enabled': nvf_in,
            # Periódico
            'cron_batch_size': self.cron_batch_size or 5,
            'retry_backoff_min': self.retry_backoff_min or 10,
            'retry_backoff_cap_min': self.retry_backoff_cap_min or 60,
            'request_min_interval_sec': self.request_min_interval_sec or 60,
            # Diario
            'daily_auto_send_enabled': bool(self.daily_auto_send_enabled),
            'daily_send_time': self.daily_send_time or '03:00',
            'daily_use_custom_params': bool(self.daily_use_custom_params),
            'daily_cron_batch_size': self.daily_cron_batch_size or 5,
            'daily_retry_backoff_min': self.daily_retry_backoff_min or 10,
            'daily_retry_backoff_cap_min': self.daily_retry_backoff_cap_min or 60,
            'daily_request_min_interval_sec': self.daily_request_min_interval_sec or 60,
            # Anomalias
            'anomaly_cron_enabled': bool(self.vf_anomaly_cron_enabled),
            'anomaly_stale_days': int(self.vf_anomaly_stale_days or 7),
            'anomaly_make_activity': bool(self.vf_anomaly_make_activity),
        })
        

        # Licencia (singleton)
        lic = self.env["verifactu.license"].sudo().get_singleton_record()
        lic.write({
            "license_key": self.verifactu_license_key,
            "update_feed_url": self.verifactu_update_feed_url,
            "verifactu_license_server_url": self.verifactu_license_server_url,
            "updates_cron_enabled": self.verifactu_updates_cron_enabled,
        })

        # Si cambia el modo → persistir y registrar histórico
        if new_mode != prev_mode:
            now = fields.Datetime.now()

            # Singleton (consulta por compañía)
            config.write({
                'last_verifactu_mode': new_mode,
                'verifactu_mode_activation_date': now,
            })

            # ICP (lectura rápida / compat)
            ICP.set_param('l10n_es_verifactu.last_verifactu_mode', new_mode)
            ICP.set_param('l10n_es_verifactu.verifactu_mode_activation_date', now)

            # Histórico
            self.env['verifactu.mode.history'].sudo().create({
                'company_id': self._company().id,
                'user_id': self.env.user.id,
                'change_date': now,
                'mode': new_mode,
                'notes': _("Cambio manual desde ajustes del módulo."),
            })

            # Feedback en el wizard (campos readonly)
            self.last_verifactu_mode = new_mode
            self.verifactu_mode_activation_date = now
            
        # encender/apagar cron global según haya alguna compañía con el flag activo
        try:
            cron = self.env.ref('l10n_es_verifactu.ir_cron_verifactu_anomaly_scanner', raise_if_not_found=False)
            if cron:
                any_on = bool(self.env['verifactu.endpoint.config'].sudo().search_count(
                    [('anomaly_cron_enabled', '=', True)]
                ))
                cron.sudo().write({'active': any_on})
        except Exception:
            pass

        # Mantener coherencia visual en la UI
        self.verifactu_mode_enabled = vf_in
        self.no_verifactu_mode_enabled = nvf_in

    # ---------- Acciones puente ----------
    def action_test_certificate(self):
        return self.env['verifactu.endpoint.config'].sudo().get_singleton_record().action_test_certificate()

    def action_reset_certificate(self):
        return self.env['verifactu.endpoint.config'].sudo().get_singleton_record().action_reset_certificate()

    def save_config(self):
        return self.env['verifactu.endpoint.config'].sudo().get_singleton_record().save_config()

    # ---------- Licencia ----------
    def action_issue_license_token(self):
        self.ensure_one()
        Lic = self.env["verifactu.license"].sudo()
        lic = Lic.get_singleton_record()
        url = (lic.verifactu_license_server_url or "").strip()
        if not url:
            return _notify_error(self.env, "Licencia", _("No hay URL de servidor configurada."))

        icp = self.env["ir.config_parameter"].sudo()
        db_uuid = icp.get_param("database.uuid") or ""
        base_url = (icp.get_param("web.base.url") or "").strip()
        module_version = icp.get_param("verifactu.module_version") or "1.0.8"
        company = self._company()
        company_name = (company.display_name or company.name or "no-name").strip()[:200]
        license_key = (lic.license_key or "").strip()
        if not license_key:
            return _notify_error(self.env, "Licencia", _("Introduce la clave de licencia."))

        payload = {
            "license_key": license_key,
            "db_uuid": db_uuid,
            "base_url": base_url,
            "company_name": company_name,
            "module": "l10n_es_verifactu",
            "module_version": module_version,
        }

        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            token = data.get("token")
            if not token:
                err_msg = data.get("error") or _("El servidor no devolvió un token válido.")
                return _notify_error(self.env, "Licencia", err_msg)

            lic.write({
                "license_token": token,
                "license_status": "valid",
                "last_check": fields.Datetime.now(),
                "last_error": False,
            })
            self.env["verifactu.license.guard"].sudo().verify_license()
            return _notify_success(self.env, "Licencia", _("Token recibido y verificado."))
        except Exception as e:
            lic.write({
                "license_status": "invalid",
                "last_error": str(e),
                "last_check": fields.Datetime.now()
            })
            return _notify_error(self.env, "Licencia", _("Error al contactar con el servidor: %s") % e)

    def action_verify_license_now(self):
        self.ensure_one()
        self.env["verifactu.license.guard"].sudo().verify_license()
        return _notify_success(self.env, "Licencia", _("Verificación ejecutada."))

    def action_open_verifactu_history(self):
        """Abre el historial completo en una vista lista separada."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Histórico de modos VeriFactu'),
            'res_model': 'verifactu.mode.history',
            'view_mode': 'tree,form',
            'domain': [('company_id', '=', self._company().id)],
            'target': 'current',
        }

    def action_open_anomalies(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Anomalías VeriFactu'),
            'res_model': 'verifactu.anomaly',
            'view_mode': 'tree,form',
            'domain': [('company_id', '=', self.env.company.id)],
            'target': 'current',
        }

    def action_run_anomaly_scan(self):
        self.env['verifactu.endpoint.config'].sudo().get_singleton_record().cron_scan_anomalies()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("Detector de anomalías"), 'message': _("Escaneo ejecutado."), 'type': 'success'}
        }