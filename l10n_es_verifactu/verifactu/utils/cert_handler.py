# Desarrollado por Juan Ormaechea (Mr. Rubik) — Todos los derechos reservados
# Este módulo está protegido por la Odoo Proprietary License v1.0
# Cualquier redistribución está prohibida sin autorización expresa.

import base64
import tempfile
import os
import re
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
from odoo.exceptions import UserError


class VerifactuCertHandler:
    def __init__(self, pfx_data, pfx_password):
        self.pfx_data = pfx_data
        self.pfx_password = pfx_password
        self.cert_path = None
        self.key_path = None
        self._certificate = None  # Guardamos para acceso posterior

    def __enter__(self):
        if not self.pfx_password:
            raise UserError("El certificado .pfx requiere una contraseña para ser cargado.")
        if not self.pfx_data:
            raise UserError("No se ha proporcionado ningún certificado .pfx para firmar.")

        if not isinstance(self.pfx_data, (bytes, str)):
            raise UserError("El certificado debe ser una cadena base64 o bytes, pero se recibió: %s" % type(self.pfx_data))

        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            base64.b64decode(self.pfx_data),
            self.pfx_password.encode(),
            backend=default_backend()
        )

        self._certificate = certificate  # Almacenamos el certificado

        # Serializar certificado y clave privada a PEM
        cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )

        # Escribir a archivos temporales
        cert_file = tempfile.NamedTemporaryFile(delete=False)
        cert_file.write(cert_pem)
        cert_file.flush()
        self.cert_path = cert_file.name

        key_file = tempfile.NamedTemporaryFile(delete=False)
        key_file.write(key_pem)
        key_file.flush()
        self.key_path = key_file.name

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cert_path and os.path.exists(self.cert_path):
            os.unlink(self.cert_path)
        if self.key_path and os.path.exists(self.key_path):
            os.unlink(self.key_path)

    def get_cert_nif_and_name(self):
        if not self._certificate:
            raise ValueError("El certificado no ha sido cargado aún")

        subject = self._certificate.subject
        fields = {attr.oid._name: attr.value for attr in subject}

        common_name = fields.get('commonName', '')
        serial_number = fields.get('serialNumber', '')

        # Extraer NIF de forma heurística
        nif = serial_number or self._extract_nif_from_string(common_name)
        nif = self._clean_nif(nif)
        name = common_name

        if not nif:
            raise ValueError("No se pudo extraer el NIF del certificado")

        return nif, name

    def _extract_nif_from_string(self, text):
        match = re.search(r'\b[ABCDEFGHJKLMNPQRSUVWXYZ0-9]{1}[0-9]{7}[0-9A-Z]\b', text)
        return match.group(0) if match else ''
    
    def _clean_nif(self, nif):
        # Elimina prefijos como IDCES-, ES-, etc., y extrae solo el NIF válido
        match = re.search(r'\b[0-9]{7,8}[A-Z]\b', nif)
        return match.group(0) if match else nif

