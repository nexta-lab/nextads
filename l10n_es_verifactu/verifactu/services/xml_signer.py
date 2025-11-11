import base64
import lxml.etree as LET
from signxml import XMLSigner, methods
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding
from cryptography.hazmat.backends import default_backend
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class VerifactuXMLSigner:
    def __init__(self, config):
        """
        Recibe la configuración de VeriFactu (con el PFX y la contraseña).
        """
        self.config = config

    def sign(self, xml_string):
        """
        Firma el XML dado usando el certificado y devuelve el XML firmado.
        """
        if not self.config.cert_pfx or not self.config.cert_password:
            raise UserError(
                "No se ha configurado el certificado digital (.pfx) o la contraseña en el sistema."
            )

        try:
            cert_data = base64.b64decode(self.config.cert_pfx)

            # Cargar certificado y clave privada desde PFX
            private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                cert_data,
                self.config.cert_password.encode(),
                backend=default_backend()
            )

            pem_cert = certificate.public_bytes(Encoding.PEM).decode("utf-8")
            # Firmar el XML
            if isinstance(xml_string, str):
                xml_doc = LET.fromstring(xml_string.encode("utf-8"))
            else:
                xml_doc = LET.fromstring(xml_string)
            signer = XMLSigner(method=methods.enveloped, digest_algorithm="sha256")
            signed_doc = signer.sign(xml_doc, key=private_key, cert=pem_cert)

            _logger.info("✅ XML firmado correctamente con el certificado VeriFactu.")
            return LET.tostring(signed_doc, pretty_print=True, encoding="utf-8").decode("utf-8")

        except ValueError as e:
            _logger.error("🛑 Error al cargar el certificado PFX: %s", str(e))
            raise UserError(
                "No se pudo cargar el certificado PFX. Verifica el archivo o la contraseña.\n\nDetalles: %s" % str(e)
            )
        except Exception as e:
            _logger.exception("🛑 Error al firmar el XML: %s", str(e))
            raise UserError("Error al firmar el XML: %s" % str(e))
