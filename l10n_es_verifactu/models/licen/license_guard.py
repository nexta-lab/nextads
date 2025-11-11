import jwt
from odoo import models, fields
import datetime as dt
from urllib.parse import urlparse

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0xKteCoAHR9heSSR+gAC
eVj+KhiWwf15fBSx9x1V6T14bZYl1HEGc/f/4grYSd62l/P9NbEQEkqKDS+x4YZj
AJobzKXEtzsmGpCdW0adf/we6I7EBZu0l5mCsfHpffVITBsGGTFw8Kdqr4PnJk2y
ElMx7Lx3eCQDp/IqaXiBz606fj4gQ8CpgOXTJnxn+MKV0vtPqezc50BphHqjfM3Z
L6orCUQ8MlqV9wIHwb9qfmgJPQLoU4uCU3JZBnoBmP81J0Xv6HFymm6kORQgA6O2
nA0GrTHy+Jw4TAyz5sU8lvT+dP/EjOMrCXzV/awWjmcbqQjCx4uKhOV4tBiaEgbJ
ZQIDAQAB
-----END PUBLIC KEY-----"""

class VerifactuLicenseGuard(models.AbstractModel):
    _name = "verifactu.license.guard"
    _description = "Guard de licencia VeriFactu"

    def _db_info(self):
        icp = self.env["ir.config_parameter"].sudo()
        return {
            "db_uuid": icp.get_param("database.uuid"),
            "base_url": (icp.get_param("web.base.url") or "").strip(),
        }

    def _host(self, url):
        try:
            return urlparse(url).hostname or ""
        except Exception:
            return ""

    def _host_match(self, token_base_url, system_base_url):
        """Exact host match. Si quieres permitir wildcard (*.dominio), añade lógica aquí."""
        if not token_base_url:
            return True  # si el token no fijó dominio, no forzar
        host_token = self._host(token_base_url).lower()
        host_sys = self._host(system_base_url).lower()
        if not host_token or not host_sys:
            return False
        return host_token == host_sys

    def verify_license(self):
        lic = self.env["verifactu.license"].sudo().get_singleton_record()
        ok = False
        reason = None
        expiry = None

        try:
            if not lic.license_token:
                reason = "missing_token"
                return {"ok": False, "reason": reason}

            # Verifica firma y exp (por defecto PyJWT verifica exp)
            payload = jwt.decode(
                lic.license_token,
                PUBLIC_KEY,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )

            info = self._db_info()

            # 1) db_uuid
            if payload.get("db_uuid") != info["db_uuid"]:
                reason = "db_uuid_mismatch"
            else:
                # 2) base_url (host)
                token_bu = (payload.get("base_url") or "").strip()
                if not self._host_match(token_bu, info["base_url"]):
                    reason = "base_url_mismatch"
                else:
                    # 3) límites opcionales: max_companies
                    max_companies = payload.get("max_companies")
                    if max_companies is not None:
                        companies = self.env["res.company"].sudo().search_count([])
                        if companies > int(max_companies):
                            reason = "limit_companies"
                        else:
                            ok = True
                    else:
                        ok = True

            # Expiry (si viene exp en payload → epoch)
            exp = payload.get("exp")
            if exp:
                expiry = fields.Datetime.to_string(
                    dt.datetime.utcfromtimestamp(exp)
                )

        except jwt.ExpiredSignatureError:
            reason = "expired"
        except Exception as e:
            reason = f"jwt_error: {e}"

        lic.write({
            "license_status": "valid" if ok else ("expired" if reason == "expired" else "invalid"),
            "last_error": False if ok else reason,
            "last_check": fields.Datetime.now(),
            "expiry": expiry,
        })
        return {"ok": ok, "reason": reason}