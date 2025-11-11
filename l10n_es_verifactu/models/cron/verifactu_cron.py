# -*- coding: utf-8 -*-
import logging
import random
import time
from datetime import timedelta

from odoo import api, fields, models, _, SUPERUSER_ID

_logger = logging.getLogger(__name__)


class VerifactuCronService(models.AbstractModel):
    """
    Servicio de CRON para VeriFactu, compatible Odoo 10→18.
    - Advisory lock a nivel BD (PostgreSQL) para evitar solapes entre workers
    - Selección segura de facturas (pending -> error con backoff)
    - Backoff exponencial con jitter y cap
    - Circuit breaker por compañía
    - Watchdog de facturas 'processing' atascadas
    - Rate-limit por compañía (intervalo mínimo entre envíos)
    - Savepoints + commit por factura (¡commit fuera del savepoint!)
    - Sin f-strings (Py2 compat)
    - Compat 10–12: force_company | Compat 13+: allowed_company_ids (sin force_company)
    - Dominios compatibles (type / move_type)
    """
    _name = "verifactu.cron.service"
    _description = "VeriFactu Cron Service"

    _LOCK_KEY = 922337203685477000
    _CB_WINDOW_MIN = 15
    _CB_THRESHOLD = 5
    _JITTER_SECONDS_MAX = 60
    _WATCHDOG_TTL_MIN = 30
    _DEFAULT_MIN_INTERVAL_SEC = 60

    # ───────────────── Helpers de compatibilidad ─────────────────
    @api.model
    def _is_modern_env(self):
        """Devuelve True a partir de Odoo 13 (donde no se debe usar force_company)."""
        try:
            import odoo
            ver = getattr(odoo.release, 'version', '13.0')
            major = int(str(ver).split('.')[0])
        except Exception:
            major = 13 if hasattr(self.env, 'company') else 12
        return major >= 13

    @api.model
    def _env_for_company(self, company_id):
        """
        Environment por compañía:
          - Odoo 10–12 → usa force_company (no existe with_company); allowed_company_ids opcional
          - Odoo 13+   → NO usa force_company; usa allowed_company_ids
          - Siempre SUPERUSER_ID (sudo)
        """
        ctx = dict(self.env.context or {})
        if self._is_modern_env():
            ctx.pop('force_company', None)
            ctx['allowed_company_ids'] = [company_id]
        else:
            ctx['force_company'] = company_id
            ctx['allowed_company_ids'] = [company_id]
        return api.Environment(self.env.cr, SUPERUSER_ID, ctx)

    @api.model
    def _ctx_no_force_company(self, disable_tracking=False):
        """
        Contexto limpio sin 'force_company' para evitar warnings en subsistemas como
        mail/chatter durante write(); opcionalmente desactiva el tracking (Odoo 13+).
        """
        ctx = dict(self.env.context or {})
        ctx.pop('force_company', None)
        if disable_tracking:
            ctx['tracking_disable'] = True   # Odoo 13+
            ctx['mail_notrack'] = True       # Compat adicional
        return ctx

    @api.model
    def _move_model_for_company(self, company_id):
        env_company = self._env_for_company(company_id)
        return env_company['account.move']

    @api.model
    def _domain_sales_moves_for(self, Move):
        """Devuelve dominio correcto según exista move_type (v13+) o type (v10–12)."""
        fields_map = getattr(Move, "_fields", {}) or {}
        if "move_type" in fields_map:
            return [("move_type", "in", ("out_invoice", "out_refund"))]
        if "type" in fields_map:
            return [("type", "in", ("out_invoice", "out_refund"))]
        _logger.warning("[VeriFactu] Ni move_type ni type existen en account.move; se omite filtro de tipo.")
        return []

    @api.model
    def _order_safe(self, primary="invoice_date", fallback="date_invoice"):
        return "id asc"

    # ───────────────── ENTRYPOINT ─────────────────
    @api.model
    def run(self):
        if not self._acquire_db_lock():
            return
        try:
            self._process_companies()
        finally:
            self._release_db_lock()

    # ───────────────── Núcleo ─────────────────
    @api.model
    def _process_companies(self):
        Company = self.env["res.company"].sudo()
        Config = self.env["verifactu.endpoint.config"].sudo()

        for company in Company.search([]):
            cfg = Config.search([("company_id", "=", company.id)], limit=1)
            if not (cfg and getattr(cfg, "endpoint_url", None) and getattr(cfg, "cron_auto_send_enabled", False)):
                continue

            batch = max(1, int(getattr(cfg, "cron_batch_size", 5) or 5))
            base_backoff_min = max(1, int(getattr(cfg, "retry_backoff_min", 10) or 10))
            cap_backoff_min = max(base_backoff_min, int(getattr(cfg, "retry_backoff_cap_min", 60) or 60))
            min_interval_sec = max(
                0, int(getattr(cfg, "request_min_interval_sec", self._DEFAULT_MIN_INTERVAL_SEC) or self._DEFAULT_MIN_INTERVAL_SEC)
            )

            Move = self._move_model_for_company(company.id)

            # 0) Watchdog
            try:
                self._release_stuck_processing(Move, company, ttl_min=self._WATCHDOG_TTL_MIN)
            except Exception:
                _logger.exception("[VeriFactu][%s] Fallo en watchdog de 'processing'.", company.name)

            # 1) Circuit breaker
            if self._company_in_circuit_breaker(company, self._CB_WINDOW_MIN, self._CB_THRESHOLD):
                continue

            # 2) Selección
            candidates = self._pick_invoices_batch(Move, company, batch, base_backoff_min, cap_backoff_min)
            if not candidates:
                continue

            # 3) Marcar processing + last_try (commit fuera de savepoint)
            now = fields.Datetime.now()
            ok_count, fail_count = 0, 0
            try:
                candidates.with_context(self._ctx_no_force_company(disable_tracking=True)).sudo().write({
                    "verifactu_processing": True,
                    "verifactu_last_try": now
                })
                self.env.cr.commit()
            except Exception:
                _logger.exception("[VeriFactu][%s] No se pudieron marcar processing/last_try.", company.name)

            _logger.info(
                "[VeriFactu][%s] Cron: procesando %s facturas (batch=%s, base_backoff=%sm, cap_backoff=%sm, min_interval=%ss).",
                company.name, len(candidates), batch, base_backoff_min, cap_backoff_min, min_interval_sec
            )

            # 4) Procesado por factura
            for inv in candidates:
                try:
                    self._pacing_wait(company, min_interval_sec)
                except Exception:
                    _logger.debug("[VeriFactu][%s] Pacing omitido por excepción menor.", company.name)

                # Importante: NO commit dentro del savepoint
                with self.env.cr.savepoint():
                    try:
                        self._touch_company_send_ts(company)
                        inv.send_xml()
                        try:
                            inv.with_context(self._ctx_no_force_company(disable_tracking=True)).sudo().write({
                                "verifactu_processing": False,
                                "verifactu_retry_count": 0,
                            })
                        except Exception:
                            pass
                        ok_count += 1
                    except Exception as e:
                        _logger.warning(
                            "[VeriFactu][%s] Error al enviar %s: %s",
                            company.name, getattr(inv, "name", inv.id), e
                        )
                        try:
                            inv.with_context(self._ctx_no_force_company(disable_tracking=True)).sudo().write({
                                "verifactu_processing": False,
                                "verifactu_retry_count": (getattr(inv, "verifactu_retry_count", 0) or 0) + 1,
                                "verifactu_status": "error",
                            })
                        except Exception:
                            try:
                                inv.with_context(self._ctx_no_force_company(disable_tracking=True)).sudo().write({
                                    "verifactu_processing": False,
                                    "verifactu_status": "error"
                                })
                            except Exception:
                                pass
                        fail_count += 1

                # Commit por factura (fuera del savepoint)
                self.env.cr.commit()

            _logger.info("[VeriFactu][%s] Cron resumen → ok=%s, fail=%s, batch=%s",
                         company.name, ok_count, fail_count, len(candidates))

            try:
                self.env.invalidate_all()
            except Exception:
                pass

    # ───────────────── Watchdog de 'processing' ─────────────────
    @api.model
    def _release_stuck_processing(self, Move, company, ttl_min):
        cutoff = fields.Datetime.now() - timedelta(minutes=int(ttl_min or 30))
        dom = [
            ("company_id", "=", company.id),
            ("verifactu_processing", "=", True),
            "|", ("verifactu_last_try", "=", False),
                 ("verifactu_last_try", "<", fields.Datetime.to_string(cutoff)),
        ]
        stuck = Move.search(dom, limit=200)
        if stuck:
            stuck.with_context(self._ctx_no_force_company(disable_tracking=True)).sudo().write({"verifactu_processing": False})
            _logger.warning("[VeriFactu][%s] Liberadas %s facturas atascadas en 'processing'.",
                            company.name, len(stuck))

    # ───────────────── Rate-limit (pacing) ─────────────────
    @api.model
    def _pacing_wait(self, company, min_interval_sec):
        ICP = self.env["ir.config_parameter"].sudo()
        key = "verifactu.last_send_ts.%s" % company.id
        now = fields.Datetime.now()
        val = ICP.get_param(key)
        if val:
            try:
                last = fields.Datetime.from_string(val)
                delta = (now - last).total_seconds()
                wait = int(min_interval_sec or 0) - int(delta)
                if wait > 0:
                    wait = max(1, wait + random.randint(0, 1))
                    time.sleep(wait)
            except Exception:
                pass

    @api.model
    def _touch_company_send_ts(self, company):
        try:
            self.env["ir.config_parameter"].sudo().set_param(
                "verifactu.last_send_ts.%s" % company.id,
                fields.Datetime.to_string(fields.Datetime.now())
            )
        except Exception:
            pass

    # ───────────────── Selección de candidatas ─────────────────
    @api.model
    def _pick_invoices_batch(self, Move, company, batch, base_backoff_min, cap_backoff_min):
        common = [
            ("company_id", "=", company.id),
            ("state", "=", "posted"),
            ("verifactu_generated", "=", True),
            ("verifactu_processing", "=", False),
        ]
        sales = self._domain_sales_moves_for(Move)
        order_clause = self._order_safe()

        # PENDING
        dom_pending = list(common) + list(sales) + [("verifactu_status", "=", "pending")]
        try:
            pending = Move.search(dom_pending, limit=batch, order=order_clause)
        except Exception:
            dom_pending = [d for d in dom_pending if not (isinstance(d, tuple) and d[0] in ("type", "move_type"))]
            pending = Move.search(dom_pending, limit=batch, order=order_clause)

        if len(pending) >= batch:
            return pending
        remaining = batch - len(pending)

        # ERROR con backoff
        dom_error = list(common) + list(sales) + [("verifactu_status", "=", "error")]
        try:
            superset = Move.search(dom_error, limit=5 * remaining, order="verifactu_last_try asc, " + order_clause)
        except Exception:
            dom_error = [d for d in dom_error if not (isinstance(d, tuple) and d[0] in ("type", "move_type"))]
            superset = Move.search(dom_error, limit=5 * remaining, order=order_clause)

        now = fields.Datetime.now()
        eligible_ids = []
        for inv in superset:
            retry = int(getattr(inv, "verifactu_retry_count", 0) or 0)
            wait_min = self._next_backoff_minutes(retry, base_backoff_min, cap_backoff_min)
            last_try = getattr(inv, "verifactu_last_try", None)
            if not last_try:
                last_try = now - timedelta(days=365)
            next_try = last_try + timedelta(minutes=wait_min)
            if next_try <= now:
                eligible_ids.append(inv.id)
            if len(eligible_ids) >= remaining:
                break

        return pending | Move.browse(eligible_ids)

    # ───────────────── Backoff & CB ─────────────────
    @api.model
    def _next_backoff_minutes(self, retry_count, base_min, cap_min):
        try:
            retry = max(0, int(retry_count or 0))
        except Exception:
            retry = 0
        base = max(1, int(base_min or 5))
        cap = max(base, int(cap_min or 60))
        if retry > 20:
            retry = 20
        minutes = base * (2 ** retry)
        if minutes > cap:
            minutes = cap
        jitter_sec = random.randint(0, self._JITTER_SECONDS_MAX)
        return max(1, minutes + int(jitter_sec // 60))

    @api.model
    def _company_in_circuit_breaker(self, company, window_min, threshold):
        Move = self._move_model_for_company(company.id)
        window_dt = fields.Datetime.now() - timedelta(minutes=window_min)
        domain = [
            ("company_id", "=", company.id),
            ("state", "=", "posted"),
        ] + self._domain_sales_moves_for(Move) + [
            ("verifactu_status", "=", "error"),
            ("verifactu_last_try", "!=", False),
            ("verifactu_last_try", ">", fields.Datetime.to_string(window_dt)),
        ]
        try:
            count = Move.search_count(domain)
        except Exception:
            records = Move.search([("company_id", "=", company.id), ("state", "=", "posted")])
            count = 0
            for r in records:
                mt = getattr(r, "move_type", None) or getattr(r, "type", None)
                if mt not in ("out_invoice", "out_refund"):
                    continue
                if getattr(r, "verifactu_status", None) != "error":
                    continue
                lt = getattr(r, "verifactu_last_try", None)
                if lt and lt > window_dt:
                    count += 1

        if count >= threshold:
            _logger.warning(
                "[VeriFactu][%s] Circuit breaker activo: %s fallos en %s min.",
                company.name, count, window_min
            )
            return True
        return False

    # ───────────────── Locks ─────────────────
    @api.model
    def _acquire_db_lock(self):
        try:
            self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", (self._LOCK_KEY,))
            row = self.env.cr.fetchone()
            locked = bool(row and row[0])
            if not locked:
                _logger.info("[VeriFactu] CRON saltado: otro worker tiene el lock.")
            return locked
        except Exception:
            _logger.warning("[VeriFactu] Advisory lock no disponible; usando ICP como fallback.")
            ICP = self.env["ir.config_parameter"].sudo()
            now = fields.Datetime.now()
            val = ICP.get_param("verifactu.cron.lock")
            if val:
                try:
                    last = fields.Datetime.from_string(val)
                    if (now - last).total_seconds() < 600:
                        return False
                except Exception:
                    pass
            ICP.set_param("verifactu.cron.lock", fields.Datetime.to_string(now))
            return True

    @api.model
    def _release_db_lock(self):
        try:
            self.env.cr.execute("SELECT pg_advisory_unlock(%s)", (self._LOCK_KEY,))
        except Exception:
            try:
                self.env["ir.config_parameter"].sudo().set_param("verifactu.cron.lock", "")
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# CRON DIARIO (a una hora fija) — usa los mismos helpers del servicio base
# ─────────────────────────────────────────────────────────────────────────────

class VerifactuCronDailyService(VerifactuCronService):
    """
    Servicio de CRON diario para VeriFactu (hora fija), compatible Odoo 10→18.
    - Hereda de VerifactuCronService (reutiliza watchdog, domains, pacing, backoff, CB, etc.)
    - Toma parámetros daily_* si daily_use_custom_params=True; si no, usa los del periódico
    - Lock y pacing separados para no interferir con el cron periódico
    """
    _name = "verifactu.cron.daily.service"
    _description = "VeriFactu Cron Service (Daily @ fixed time)"

    # Lock distinto para que ambos crons puedan coexistir sin bloquearse entre sí
    _LOCK_KEY = 922337203685477111

    # Clave distinta para el pacing (intervalo mínimo entre envíos)
    _PACE_TS_KEY_TMPL = "verifactu.last_send_ts.daily.%s"

    # ENTRYPOINT
    @api.model
    def run(self):
        if not self._acquire_db_lock():
            return
        try:
            self._process_companies_daily()
        finally:
            self._release_db_lock()

    # Pacing: sobrescribimos para usar la clave diaria
    @api.model
    def _pacing_wait(self, company, min_interval_sec):
        ICP = self.env["ir.config_parameter"].sudo()
        key = self._PACE_TS_KEY_TMPL % company.id
        now = fields.Datetime.now()
        val = ICP.get_param(key)
        if val:
            try:
                last = fields.Datetime.from_string(val)
                delta = (now - last).total_seconds()
                wait = int(min_interval_sec or 0) - int(delta)
                if wait > 0:
                    wait = max(1, wait + random.randint(0, 1))
                    time.sleep(wait)
            except Exception:
                pass

    @api.model
    def _touch_company_send_ts(self, company):
        """Marca el timestamp del último envío para pacing DIARIO (clave separada)."""
        try:
            self.env["ir.config_parameter"].sudo().set_param(
                self._PACE_TS_KEY_TMPL % company.id,
                fields.Datetime.to_string(fields.Datetime.now())
            )
        except Exception:
            pass

    # Núcleo (idéntico al base pero leyendo daily_* cuando corresponda)
    @api.model
    def _process_companies_daily(self):
        Company = self.env["res.company"].sudo()
        Config = self.env["verifactu.endpoint.config"].sudo()

        for company in Company.search([]):
            cfg = Config.search([("company_id", "=", company.id)], limit=1)
            if not (cfg and getattr(cfg, "endpoint_url", None) and getattr(cfg, "daily_auto_send_enabled", False)):
                continue

            # Parametrización: si hay daily_use_custom_params → usar daily_*; si no, usar los del periódico
            use_custom = bool(getattr(cfg, "daily_use_custom_params", False))

            batch = max(1, int(
                getattr(cfg, "daily_cron_batch_size" if use_custom else "cron_batch_size", 5) or 5
            ))
            base_backoff_min = max(1, int(
                getattr(cfg, "daily_retry_backoff_min" if use_custom else "retry_backoff_min", 10) or 10
            ))
            cap_backoff_min = max(base_backoff_min, int(
                getattr(cfg, "daily_retry_backoff_cap_min" if use_custom else "retry_backoff_cap_min", 60) or 60
            ))
            min_interval_sec = max(0, int(
                getattr(cfg, "daily_request_min_interval_sec" if use_custom else "request_min_interval_sec",
                        self._DEFAULT_MIN_INTERVAL_SEC) or self._DEFAULT_MIN_INTERVAL_SEC
            ))

            Move = self._move_model_for_company(company.id)

            # 0) Watchdog de 'processing'
            try:
                self._release_stuck_processing(Move, company, ttl_min=self._WATCHDOG_TTL_MIN)
            except Exception:
                _logger.exception("[VeriFactu-DIARIO][%s] Fallo en watchdog de 'processing'.", company.name)

            # 1) Circuit breaker por compañía (reutiliza el del base)
            if self._company_in_circuit_breaker(company, self._CB_WINDOW_MIN, self._CB_THRESHOLD):
                continue

            # 2) Selección de candidatas (pending → error con backoff)
            candidates = self._pick_invoices_batch(Move, company, batch, base_backoff_min, cap_backoff_min)
            if not candidates:
                continue

            # 3) Marcar processing + last_try (commit fuera del savepoint)
            now = fields.Datetime.now()
            ok_count, fail_count = 0, 0
            try:
                candidates.with_context(self._ctx_no_force_company(disable_tracking=True)).sudo().write({
                    "verifactu_processing": True,
                    "verifactu_last_try": now
                })
                self.env.cr.commit()
            except Exception:
                _logger.exception("[VeriFactu-DIARIO][%s] No se pudieron marcar processing/last_try.", company.name)

            _logger.info(
                "[VeriFactu-DIARIO][%s] Cron diario: procesando %s facturas "
                "(batch=%s, base_backoff=%sm, cap_backoff=%sm, min_interval=%ss, custom=%s).",
                company.name, len(candidates), batch, base_backoff_min, cap_backoff_min, min_interval_sec, use_custom
            )

            # 4) Procesado por factura (savepoint + commit por factura)
            for inv in candidates:
                try:
                    self._pacing_wait(company, min_interval_sec)
                except Exception:
                    _logger.debug("[VeriFactu-DIARIO][%s] Pacing omitido por excepción menor.", company.name)

                with self.env.cr.savepoint():
                    try:
                        self._touch_company_send_ts(company)
                        inv.send_xml()
                        try:
                            inv.with_context(self._ctx_no_force_company(disable_tracking=True)).sudo().write({
                                "verifactu_processing": False,
                                "verifactu_retry_count": 0,
                            })
                        except Exception:
                            pass
                        ok_count += 1
                    except Exception as e:
                        _logger.warning(
                            "[VeriFactu-DIARIO][%s] Error al enviar %s: %s",
                            company.name, getattr(inv, "name", inv.id), e
                        )
                        try:
                            inv.with_context(self._ctx_no_force_company(disable_tracking=True)).sudo().write({
                                "verifactu_processing": False,
                                "verifactu_retry_count": (getattr(inv, "verifactu_retry_count", 0) or 0) + 1,
                                "verifactu_status": "error",
                            })
                        except Exception:
                            try:
                                inv.with_context(self._ctx_no_force_company(disable_tracking=True)).sudo().write({
                                    "verifactu_processing": False,
                                    "verifactu_status": "error"
                                })
                            except Exception:
                                pass
                        fail_count += 1

                # Commit por factura
                self.env.cr.commit()

            _logger.info("[VeriFactu-DIARIO][%s] Resumen → ok=%s, fail=%s, batch=%s",
                         company.name, ok_count, fail_count, len(candidates))

            try:
                self.env.invalidate_all()
            except Exception:
                pass
