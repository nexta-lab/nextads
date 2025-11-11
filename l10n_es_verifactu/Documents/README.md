# Módulo VeriFactu para Odoo

Este módulo implementa la integración con el sistema VeriFactu exigido por la Agencia Tributaria Española. Está disponible para versiones de Odoo desde la 12 hasta la 18, y se entrega con soporte incluido durante 30 días tras la compra.

## Características principales

- ✅ Generación automática de XML conforme a la normativa VeriFactu.
- 🔐 Firma electrónica con certificados digitales (PFX / FNMT).
- 📤 Envío directo de facturas a la AEAT (Agencia Tributaria Española).
- 🔗 Generación de código QR y hash de la factura.
- 📝 Registro de logs e incidencias técnicas.
- 🔁 Compatible con múltiples versiones de Odoo (12–18).
- 🇪🇸 Cumple con la normativa española de facturación electrónica.

## Requisitos técnicos

Para el correcto funcionamiento del módulo es necesario instalar los siguientes paquetes de Python, utilizados para la firma electrónica y generación de XML:

### 🔧 Instalación de dependencias (Python)

Copia este archivo `requirements.txt` en la raíz del módulo y ejecuta:

#### En Linux / Mac:

```bash
pip install -r requirements.txt
```

#### En Windows:

```bash
cd "C:\Program Files\Odoo 17.0.20250408\python"
.\python.exe -m pip install -r ruta\al\módulo\l10n_es_verifactu\requirements.txt

```

## Licencia

Este módulo está protegido por la [Odoo Proprietary License v1.0 (OPL-1)](https://www.odoo.com/documentation/15.0/legal/licenses.html#odoo-apps).

> **Está prohibida su redistribución, modificación o reventa sin autorización expresa del autor.**

Incluye derechos de uso **exclusivamente** para la empresa que realiza la compra a través del canal oficial (Odoo Market, Gumroad, o venta directa).

## Soporte

🛠️ Se ofrece **soporte técnico durante 30 días** desde la fecha de compra. El soporte incluye:

- Resolución de errores derivados del módulo original.
- Ayuda en la instalación y configuración.
- Aclaraciones sobre el uso de las funcionalidades incluidas.

❌ El soporte **no incluye personalizaciones específicas** fuera del módulo original.

Para soporte, contactar por correo: [rubikdevodoo@gmail.com]

## Actualizaciones

Las actualizaciones menores (mejoras o correcciones dentro de la misma versión de Odoo) estarán disponibles de forma gratuita durante el periodo de soporte.

Versiones nuevas para versiones distintas de Odoo pueden requerir una nueva licencia.

## Autor

Desarrollado por **Juan Ormaechea**  
Contacto: [rubikdevodoo@gmail.com]
Sitio web: [https://www.mrrubik.com](https://www.mrrubik.com)

### Declaración Responsable VeriFactu

Este módulo incluye una declaración responsable de cumplimiento técnico conforme a la normativa VeriFactu (julio 2025), emitida por el autor original. La declaración es válida **únicamente si el código no ha sido modificado**. En caso de modificación, el usuario final será responsable de emitir su propia declaración.


