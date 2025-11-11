# Changelog - VeriFactu
Todas las notas de cambios de este módulo.  
El formato sigue Keep a Changelog (https://keepachangelog.com/es-ES/1.0.0/) y SemVer (https://semver.org/lang/es-ES/).

## [2.0.8] - 2025-10-08
### Añadido
- Nuevo modelo `verifactu.status.log` para registrar el histórico completo de cambios de estado de cada factura VeriFactu.
  - Guarda usuario, fecha, notas, hash actual, hash previo y código AEAT devuelto.
  - Incluye copia del XML SOAP enviado o generado por la AEAT.
  - Compatible con versiones Odoo 10 → 18 (sin romper en entornos antiguos).
- Campo `aeat_code` para almacenar el código de respuesta devuelto por la AEAT (ej. 2000, 4102, 3000…).
- Campo `xml_soap` para conservar la evidencia técnica del envío en formato binario.

### Mejorado
- Sistema de verificación de integridad (`VerifactuHashVerifier`) totalmente reescrito:
  - Verifica que el hash calculado coincida con el último hash ENVIADO registrado en logs.
  - Comprueba la continuidad de la cadena (`prev_hash` vs hash anterior real).
  - Permite encadenamientos alternativos válidos (subsanaciones o anulaciones).
  - Muestra resultados legibles en el chatter, con formato HTML claro y un único mensaje.
- El verificador ahora usa notificaciones visuales (`notify_success` / `notify_warning`) sin duplicar logs en el chatter.
- Mensajes más limpios y estructurados en los resultados de integridad (sin triplicación).

### Corregido
- Eliminados los mensajes duplicados en el chatter durante la verificación de cadena.
- Resuelto error de compatibilidad por `lambda self` en `fields.Selection` (no soportado en Odoo 10–12).
- Sustituido `fields.Datetime.now` por `lambda self: fields.Datetime.now()` para compatibilidad universal.

### Técnico
- Refactor general del código de verificación y trazabilidad.
- Estandarización del estilo de código y comentarios (bloques “──────────”).
- Preparado para extensión futura: sincronización automática del histórico con AEAT o backups externos.

---


## [2.0.7] - 2025-10-08

### Added
- Sección **“Automatizaciones”** en *Ajustes → Veri*Factu* (misma tarjeta):
  - Activación de envío periódico por `cron` → campo `cron_auto_send_enabled`.
  - Parámetros editables: `cron_batch_size`, `retry_backoff_min`, `retry_backoff_cap_min`, `request_min_interval_sec`.
- **Envío diario a hora fija**:
  - Campos `daily_auto_send_enabled` y `daily_send_time (HH:MM)`.
  - Nuevo `ir.cron` diario que reutiliza el servicio de envío.
- **Servicio universal de CRON** `verifactu.cron.service` (Odoo 10 → 18):
  - *Advisory lock* PostgreSQL para evitar solapes.
  - Backoff exponencial con *jitter* y **cap** por factura.
  - **Circuit breaker** por compañía.
  - **Watchdog** que libera `verifactu_processing` atascados.
  - **Rate-limit por compañía** (marca `verifactu.last_send_ts.<company_id>` en `ir.config_parameter`).
  - Procesado con *savepoint* por factura y `commit` fuera del *savepoint*.
- Controles de **certificado** en ajustes:
  - Subida `cert_pfx`, `cert_password`, botón **“Probar certificado”**.
- Bloque de **Licencia**:
  - Campos `verifactu_license_key`, `verifactu_license_token_display`, estado y acciones **emitir/validar** token (JWT).
- **Declaración Responsable**:
  - Subida/descarga del PDF desde ajustes (`verifactu_declaracion_file`, `action_download_declaracion`).

### Changed
- Compatibilidad ampliada **Odoo 10 → 18**:
  - Detección dinámica de dominio ventas usando `move_type` (v13+) o `type` (v10–12).
  - Entorno por compañía con `api.Environment(cr, SUPERUSER_ID, ctx)` usando `force_company` + `allowed_company_ids`.
  - Escrituras con contexto limpio para evitar *warnings* del chatter: `tracking_disable` / `mail_notrack`.
- Reorganizada la vista: la configuración de `cron` queda bajo el H2 **Automatizaciones** en el mismo bloque del módulo.

### Fixed
- Eliminado el *warning*: `Context key 'force_company' is no longer supported…` en flujos de chatter/escritura.
- Evitado error de *savepoint* liberado: `commit` se realiza **fuera** del *savepoint*.
- Fallback del dominio cuando no existen `type`/`move_type`.
- Manejo seguro de transacciones y reintentos (`verifactu_retry_count`, `verifactu_last_try`).

### Notas de migración
- No se requieren cambios en `account.move` si ya existen:
  - `verifactu_generated`, `verifactu_status`, `verifactu_processing`, `verifactu_retry_count`, `verifactu_last_try`
  - y el método `send_xml()`.
- Tras actualizar:
  1. Revisa **Ajustes → Veri*Factu → Automatizaciones** y activa lo necesario.
  2. Comprueba la hora en **Envío diario** si usas el cron diario.
  3. Verifica el certificado y licencia desde los botones de la vista.
EOF


## [2.0.6] - 2025-10-08

### Added
- Controlador universal `/verifactu/download_qr/<id>` compatible con Odoo 10 → 18.  
  - Soporte para `account.invoice` (v10–12) y `account.move` (v13+).  
  - Recupera la URL persistida `verifactu_qr_url` o la regenera dinámicamente mediante `VerifactuQRContentGenerator`.  
  - Fallback automático a la URL AEAT basada en el hash truncado si no existe URL válida.  
  - Generación del QR en memoria y descarga directa en formato PNG.  
  - Limpieza de nombres de archivo para evitar caracteres no válidos.
  
- Integración del mixin `verifactu.qr.url.mixin` para almacenar y regenerar la URL del QR AEAT.  
  - Métodos `action_open_verifactu_qr_url` y `action_regenerate_verifactu_qr_url` disponibles en factura.  
  - Invocación automática tras `action_post()` (Odoo 13+) o `action_invoice_open()` (Odoo 11–12).  

- Compatibilidad ampliada de todos los componentes VeriFactu (XML Builder, Hash Calculator, Sender, Controller) con Odoo 10 → 18.

### Fixed
- Error 2000 (“El cálculo de la huella suministrada es incorrecta”) solucionado:  
  - Se unifica la lógica entre el cálculo de huella y la estructura XML, garantizando coincidencia exacta con la AEAT.  
  - Manejo correcto del encadenamiento (`Encadenamiento`) y del campo `PrimerRegistro`.  

- Corrección del error `AttributeError: 'bool' object has no attribute 'decode'` en la plantilla `web.external_layout_standard`.  
  - Ahora se utiliza `image_data_uri()` para incrustar imágenes QR sin decodificación manual.

### Changed
- Refactor en la inserción del nodo `Encadenamiento` dentro del XML para reflejar correctamente el estado de la cadena:  
  - `Huella` incluida solo si existe hash anterior válido.  
  - `PrimerRegistro` solo si no hay encadenamiento previo.

- Actualización de logs y mensajes informativos durante el cálculo y envío a la AEAT para mejorar trazabilidad y depuración.


## [2.0.4] - 2025-10-02
### Added
- Compatibilidad completa **Odoo 10 → 18** en todos los builders (normal, no-verifactu, subsanación y anulación): campos `name/number`, `invoice_date/date_invoice/date`, `tax_ids/invoice_line_tax_ids`, `move_type/type`.
- **Snapshot del IDFactura** enviado (`verifactu_last_*`) y **preflight reset** automático si cambia (fuerza envío como nuevo).
- Inclusión de **URI de referencia** en firmas cuando el signer lo soporta (atributo `Id` en nodos firmados).
- Heurística de **parseo de respuesta AEAT** basada en texto: *canceled*, *accepted_with_errors*, *error* (por código) y *sent*.
- En mensajes de error, el *summary* ahora muestra **código y explicación** (faultstring) cuando estén disponibles.

### Changed
- Unificación de helpers de huella: `_iso_with_tz`, `_safe_str`, `_fmt_amount` y coacciones de fecha para alinear **cálculo de hash** y **XML**.
- **`previous_hash`**: se deja vacío cuando no existe (no se usa `"SINHUELLA"`), y solo se genera nodo **Encadenamiento** si hay valor.
- Totales (`CuotaTotal`, `ImporteTotal`) formateados con `_fmt_amount` (redondeo según moneda/2 decimales).
- Builders:
  - Emisor siempre desde `company_id` con **NIF normalizado**.
  - Destinatario: prioriza NIF; si no hay, crea bloque **IDOtro** con validaciones.
  - Desglose por **calificación** e **impuesto**, soporte de **recargo de equivalencia** y **BaseImponibleACoste** (régimen 06 y tipos F2/F3/R5).
  - **Subsanación**: usa exactamente el mismo *timestamp* que el cálculo de huella y encadenamiento opcional.
  - **No-Verifactu**: SOAP Envelope manteniendo cabecera de **Remisión por requerimiento**.
  - **Anulación**: versión normal con atributo `Id` para el signer; versión no-verifactu con cabecera SOAP.
- Sender:
  - Lógica de estados simplificada:  
    1) si texto contiene *anulad* ⇒ `canceled`  
    2) si texto contiene *aceptad* y *error* ⇒ `accepted_with_errors`  
    3) si hay **código** ⇒ `error` (siempre)  
    4) si texto contiene *Correcto* ⇒ `sent`  
    5) en otro caso ⇒ `error`
  - Mensajería: guarda `verifactu_detailed_error_msg` solo si cambia.

### Fixed
- Caso en que la **huella anterior** terminaba grabándose como `False` en XML (encadenamiento) por coerciones; ahora se limpia correctamente.
- **Desalineación** entre base string de hash y XML (fecha/huso, formato de importes, presencia de encadenamiento).
- **Hash de anulación**: asegura timestamp y previous hash con misma fuente que alta.
- Evita fallos en Odoo 10/11 donde `date_invoice` o `number` pueden ser **str**.

### Notes
- Si usas firmadores externos, asegúrate de que aceptan `reference_uri` (cuando se aporte `Id`); el código hace *fallback* a firma sin URI si no lo soporta.
- Para depuración se recomienda habilitar `logger` en lugar de `print`.
## [2.0.3] - 2025-09-26
### Changed
- XML de datos de adjunto (`ir.attachment`) normalizado para compatibilidad 10→18: añadido envoltorio `<odoo><data>…</data></odoo>`, y ruta del PDF externalizada en atributo `file` (carga base64).
- Vista de ajustes: mantenido marcado moderno para 13+ y patrón legacy separado para 10–12 (sin clases `o_settings_*`).

### Fixed
- Error de carga en Odoo 14 por XML mal estructurado y rutas con espacios/tildes en `file=…`.
- Eliminado el uso del campo `public` en `ir.attachment` (no existe en instalaciones sin `website`), evitando fallos en 10–12 y entornos minimalistas.
- Manejo robusto de fechas/horas y tipos en el cálculo de hash (acepta `str/date/datetime`), previniendo `AttributeError: 'str' object has no attribute 'strftime'`.

### Notes
- Se recomienda ubicar el PDF en una ruta sin espacios/tildes (p. ej., `static/doc/declaracion_responsable.pdf`) para máxima portabilidad entre versiones.



## [2.0.2] - 2025-09-23
### Changed
- Eliminado el parámetro inválido `password=True` en la definición de campos `fields.Char`; ahora se aplica en las vistas XML (`<field password="True"/>`) para asegurar compatibilidad entre Odoo 10 y 18.
- Refactorizadas las clases `verifactu.endpoint.config` y `res.config.settings` para soportar multi-versión (10→18):
  - Sustitución de `env.company` por un helper genérico (`env.user.company_id`).
  - Eliminación de `@api.depends()` vacío en computes para evitar problemas en Odoo 10.
  - Ajustes en `default_get` y `set_values` para copiar solo campos válidos en cada versión.
- Estandarizado el sistema de notificaciones con un método `_notify()` que usa `display_notification` en Odoo 13+ y `warning` en versiones anteriores.

### Fixed
- Errores de carga de campos (`unknown parameter 'password'`) en instalaciones limpias de clientes con Odoo 14.
- Posibles inconsistencias al resetear certificados o al guardar ajustes por duplicidad de versiones del módulo.



# Changelog

## [2.0.1] - 2025-09-20
### Added
- Añadida la declaración de responsable en la pestaña de ajustes para poder descargarla o modificarla.
- Compatibilidad extendida de los modelos `verifactu.license` y `verifactu.update.checker` desde Odoo 18 hasta Odoo 11 (ajustes en f-strings, compute_sudo y manejo de fechas).
- Nuevo campo `verifactu_qr_url` en facturas (account.move / account.invoice) con generación automática de la URL de QR tras validar la factura.
- Vista extendida en facturas para mostrar el enlace del QR (clicable) y opciones de abrir o regenerar la URL.


## [2.0.0] - 2025-09-19
### Added
- Compatibilidad completa **Odoo 11 → Odoo 18** en todos los builders:
  - `VerifactuXMLBuilder`
  - `VerifactuXMLBuilderSubsanacion`
  - `VerifactuXMLBuilderAnulacion`
  - `VerifactuXMLBuilderNoVerifactu`
  - `VerifactuXMLBuilderNoVerifactuAnulacion`
  - `VerifactuXMLBuilderNoVerifactuSubsanacion`
  - `VerifactuEnvelopeBuilder` y `VerifactuEnvelopeBuilderAnulacion`
- Nuevos *helpers* de compatibilidad:
  - Soporte para `invoice_date` / `date_invoice` / `date` (según versión).
  - Soporte para `name` / `number` en facturas.
  - Gestión de hashes `verifactu_hash` y `verifactu_previous_hash` con fallback automático.
- Validaciones más estrictas en destinatarios:
  - Método `build_id_for_xml` garantiza siempre `NIF` o `IDOtro` con `IDType`, `CodigoPais` e `ID`.

### Changed
- Unificación de lógica de fechas en formato **DD-MM-YYYY** en todos los XML.
- Normalización de `Huella` previa: si no existe, se envía `"SINHUELLA"`.
- Firma XML reforzada con `signxml` (SHA-256, enveloped, c14n11).
- Manejo de `Subsanacion` y `RechazoPrevio` alineado con especificaciones AEAT.
- Ajuste de la lógica de encadenamiento: siempre con NIF del emisor y mismo número/fecha.

### Fixed
- Error AEAT **4102** (“Falta informar campo obligatorio: ID”) solucionado:
  - Se asegura que todos los nodos firmados (`RegistroAlta`, `RegistroAnulacion`, etc.) tengan atributo `Id`.
  - Se corrige la referencia en `<ds:Reference URI="#...">`.
- Problemas al enviar facturas sin país en el cliente: ahora se fuerza validación en `build_id_for_xml`.
- Errores de duplicidad al manejar subsanaciones vs. rectificativas.

---

## Notas
- A partir de esta versión, **no es posible** “reenviar como nuevo” una factura ya transmitida.  
  - Cambios formales → **Subsanación**  
  - Cambios económicos → **Rectificativa**  
  - Factura que no debe existir → **Anulación + nueva factura**

## [1.0.9] - 2025-09-17
### Added
- **Normalizador de NIF ES**: `clean_nif_es` elimina prefijo `ES`, espacios y separadores.
- **Selector de identificador**: `build_id_for_xml` (compatible Odoo 11–18) decide automáticamente entre `<NIF>` y `<IDOtro>`:
  - `IDType=02` para **VAT-UE** (p. ej., `FR…`, `DE…`).
  - `IDType=04` para **documento fiscal extranjero**.
  - `IDType=06` para **ES sin NIF/NIE/CIF válido**.
  - Deducción de **ES por el propio VAT** aunque `country_id` esté vacío.
- **Airbag de validación**: error de usuario si se usa `<IDOtro>` sin `ID` (evita **4102**).
- **Helpers de rectificativas (11→18)** en `VerifactuXMLValidator`:
  - `get_original_invoice()` → `reversed_entry_id` (v13+) o `refund_invoice_id` (v11–12).
  - `get_original_num_and_date()` → `name/number` y `invoice_date/date_invoice`.
  - `compute_importe_rectificacion()` → calcula **siempre** `BaseRectificada` y `CuotaRectificada` (sustitución/diferencias), incluso sin enlace a la original.

### Changed
- **Builder de destinatarios**: ahora usa `build_id_for_xml` y deja de forzar `<NIF>` si no procede.
- **Emisor / Encadenamiento / SistemaInformatico**: NIF siempre saneado (sin `ES`).
- **Desglose fiscal**: para `CalificacionOperacion = S1` se usa **`<BaseImponible>`** (no `BaseImponibleOimporteNoSujeto`).
- **Rectificativas**: se incluye **siempre** el bloque `<ImporteRectificacion>` (con totales de la original en sustitución y de la propia rectificativa en diferencias).
- **VerifactuSender**:
  - Parser estructurado (`status`, `summary`, `detail`, `code`) sin depender de emojis.
  - Estados explícitos: `sent`, `accepted_with_errors`, `rejected`, `error`, `transport_error`, `canceled`.
  - Separación clara de **fallos de transporte** (`transport_error`) vs **rechazos AEAT** (`rejected`).
  - Eliminado doble `_post_message` y registros de estado incorrectos.
  - No se marca como “processed” cuando falla el envío; queda en estado reintetable.
- **Compatibilidad**: código sin *type hints* ni *f-strings* para soportar **Odoo 11 → 18**; formateo de importes con `%.2f` y fechas unificadas vía `_format_date`.

### Fixed
- **1100** “Valor o tipo incorrecto del campo” por NIF con prefijo `ES` en `<NIF>`.
- **4102** “Falta informar campo obligatorio: ID” al usar `<IDOtro>` sin `ID`.
- **1118** “Si la factura es rectificativa por sustitución el bloque ImporteRectificacion es obligatorio” — ahora siempre se informa.
- NIF con `ES` en `<SistemaInformatico>` y `IDEmisorFactura`.
- Doble mensaje en chatter y **estado “rejected”** mal registrado en errores genéricos.
- Limpieza de VAT con guiones/puntos/espacios.

### Migration
- **Recomendado**: normalizar VAT existentes (quitar `ES`) y fijar `country_id` cuando proceda.
- Para rectificativas sin enlace a la original, opcionalmente informar `verifactu_base_original`/`verifactu_cuota_original` si se desea reflejar importes de la sustituida.
- Sin cambios de modelo; actualización transparente.

## [1.0.8] - 2025-09-11
### Changed
- Ajustes menores de estabilidad y registro de logs.

## [1.0.8] - 2025-09-11
### Added
- Avisos tempranos en `action_post` y `write` cuando no hay certificado digital configurado, usando `VerifactuLogger`.
- Avisos tempranos también cuando no hay **endpoint VeriFactu** configurado.
- Mensajes claros en chatter para recordar al usuario que es necesario configurar el certificado (.pfx + contraseña) **y** el endpoint para usar VeriFactu.
- Validación de licencia integrada con mensajes de error personalizados (400/401/403/404/5xx, timeout, etc.), mostrando notificaciones claras al usuario y guardando el detalle en `last_error`.
- **Validaciones de emisor**: comprobación explícita de `company_id.name` y `company_id.vat` (normalizado) antes de construir/enviar XML; errores guiados si faltan datos.

### Changed
- Blindaje de los flujos de envío y recálculo: si no hay certificado o endpoint, se omiten los pasos de generación de XML, QR y hash para evitar errores.
- El token de licencia (JWT) ahora se muestra truncado en Ajustes, evitando exponerlo completo.
- **Emisor desacoplado del certificado en todo el módulo**: el emisor (NIF/Nombre) se toma **siempre** de `invoice.company_id` (empresa o autónomo), y el certificado se usa **solo** para firmar.
  - `VerifactuXMLBuilder` (alta): `IDEmisorFactura` y `NombreRazonEmisor` = `company_id`; `Encadenamiento.RegistroAnterior.IDEmisorFactura` actualizado; rectificativas usan `company_id` en `DatosFacturaRectificada.IDEmisorFactura`.
  - `VerifactuEnvelopeBuilder` y `VerifactuEnvelopeBuilderAnulacion`: `Cabecera/ObligadoEmision` = `company_id` (no del certificado).
  - `VerifactuXMLBuilderAnulacion` y `VerifactuXMLBuilderNoVerifactuAnulacion`: `IDEmisorFacturaAnulada` y encadenamiento basados en `company_id`.
  - `VerifactuXMLBuilderNoVerifactu` y `VerifactuXMLBuilderNoVerifactuSubsanacion`: `ObligadoEmision`, `IDEmisorFactura`, encadenamiento y rectificativas referencian `company_id`.
  - `VerifactuXMLBuilderSubsanacion`: `Subsanacion` con emisor de `company_id`; rectificativas corregidas.
  - `VerifactuHashCalculator`: cálculo de **hash** y **cancellation hash** usando NIF de `company_id` (eliminado uso de `VerifactuCertHandler`).
  - `VerifactuQRContentGenerator`: **QR** construido con NIF de `company_id`; ya no lee NIF del certificado.
  - `_verify_invoice_fields` y `_validate_emisor`: comparan/validan contra `company_id` y usan `VerifactuXMLValidator.clean_nif_es`.
  - `VerifactuSystemInfoBuilder`: `SistemaInformatico/NombreRazon` y `NIF` salen de `company_id`.
- **Normalización de NIF/CIF** unificada con `VerifactuXMLValidator.clean_nif_es` (acepta prefijo `ES`, quita espacios, mayúsculas) en todos los puntos del XML/QR/hash.

### Fixed
- Se evita que operaciones críticas de factura fallen silenciosamente cuando falta el certificado o el endpoint; ahora siempre se informa al usuario mediante un aviso en chatter.
- Corrección de errores de vista en Ajustes al mostrar el token de licencia.
- **Error 4112 (coherencia emisor/firma)**: corregida la causa raíz al dejar de poblar el emisor con datos del certificado; el XML y el SOAP usan ahora los datos de la compañía.
- **Rectificativas**: `DatosFacturaRectificada.IDEmisorFactura` ya no usa el NIF del cliente; usa el del emisor real (`company_id`).
- **Encadenamiento**: `RegistroAnterior.IDEmisorFactura` coherente con el emisor en todas las variantes (alta, subsanación, no-Verifactu, anulación).



## [1.0.7] - 2025-07-13

### Added
- Nueva sección **Configuración del sistema informático** en los ajustes del módulo:
  - Campos configurables desde `res.config.settings`:
    - `Nombre del Sistema`
    - `ID del Sistema`
    - `Versión`
    - `Número de Instalación`
    - `Solo uso VeriFactu`
    - `Multi OT posible`
    - `Indicador múltiples OT`
  - Estos valores se insertan automáticamente en el XML bajo el nodo `<SistemaInformatico>`.
- **Histórico de estados VeriFactu**:
  - Nuevo modelo `verifactu.status.log` vinculado a `account.move`.
  - Se registra automáticamente cada vez que cambia el estado `verifactu_status`.
  - Visible en la factura como tabla con fecha, estado, usuario y notas opcionales.
- Sección explicativa añadida al **wizard de ayuda**, detallando la función de cada campo del sistema declarado.

### Changed
- Refactor del `VerifactuSystemInfoBuilder`:
  - Ahora toma todos los valores desde `verifactu.endpoint.config` en lugar de usar valores hardcoded.
  - Asegura que el XML siempre incluya estos datos, incluso si el certificado no contiene nombre/NIF válidos.
- Mejora visual en la vista de configuración: 
  - Añadido separador y campos en el panel principal debajo del botón de ayuda.
  - Estilo coherente con el resto del módulo.

### Fixed
- Se asegura que los campos del sistema informático nunca queden vacíos al usar `default`, evitando errores de validación en el esquema XSD.

### Compatibility
- Totalmente compatible con Odoo 12 a 18.


## [1.0.6] - 2025-07-09
### Added
- Soporte completo para **modo VeriFactu en facturas anuladas**.
- Nueva clase `VerifactuXMLBuilderAnulacion` compatible con el esquema oficial de la AEAT:
  - Genera el XML con el nodo raíz `<RegistroFactura>`, incluyendo `<RegistroAnulacion>` como nodo firmado.
  - Inserta correctamente la firma digital `<Signature>` dentro del nodo `RegistroAnulacion`.
  - Incluye trazabilidad mediante huella anterior (`Encadenamiento`), fecha/hora con huso horario, e información del sistema informático.
- Compatible con opciones especiales:
  - `rechazo_previo=True` → añade nodo `<RechazoPrevio>S</RechazoPrevio>`
  - `sin_Factura_anterior=True` → añade nodo `<SinRegistroPrevio>S</SinRegistroPrevio>`

### Compatibility
- Validado con esquema XSD oficial y compatible con Odoo 12 a 18.

## [1.0.5] - 2025-07-09
### Added
- Tarea programada (`cron`) para enviar automáticamente facturas pendientes cada 10 minutos.
- Nuevo booleano `enable_verifactu_cron` en configuración para activar o desactivar este comportamiento por empresa.
- Lógica del cron compatible con multicompañía: revisa configuración y filtra facturas `posted` con `verifactu_generated=True` y estado `pending` o `error`.
- Envío de hasta 5 facturas por ejecución ordenadas por fecha (`invoice_date asc, id asc`) para evitar saturar el endpoint.
- Manejo de errores individualizado por factura, con trazas en log por empresa (`[VeriFactu][Empresa] Error...`).

### Compatibility
- Probado en Odoo 12 a 18.


## [1.0.4] - 2025-07-09
### Added
- Nuevo campo booleano `verifactu_generated` para indicar si el XML ha sido generado, incluso si no se ha enviado.
- Método `only_generate_xml_never_send()` para generar el XML y el QR sin enviarlo, útil en escenarios sin certificado o sin envío automático.
- Generación automática del XML al validar facturas, incluso si no se configuran certificados o envío automático.
- Comprobación más precisa de condiciones para enviar (`should_send_to_verifactu`), separando claramente la lógica de generación y envío.

### Changed
- `send_xml()` ahora separa internamente la generación y el envío, delegando en métodos `prepare_*` y `send_*` según VeriFactu o No-VeriFactu.
- Mejora en trazabilidad y control de reenvíos al tener el estado `verifactu_generated` disponible como referencia lógica en vistas y procesos.

### Compatibility
- Probado en Odoo 12 a 18.


## [1.0.3] - 2025-07-08
### Added
- Opción de enviar automáticamente la factura a VeriFactu al validarla (`auto_send_verifactu`).
- Generación del QR incluso sin envío, si `show_qr_always` está activado en configuración.
- Nuevo diseño del QR: ubicado al inicio del informe PDF, centrado, con dimensiones 40x40mm, cumpliendo la norma ISO/IEC 18004:2015.
- Campo `verifactu_status` añadido a la vista árbol de facturas emitidas (`account.view_out_invoice_tree`).
- Indicador textual "VERI*FACTU" opcional bajo el QR si la factura fue enviada con éxito.
  
### Changed
- El QR se recalcula automáticamente si cambian campos críticos como `name`, `amount_total`, `invoice_date`, etc.
- Ahora se permite reenviar facturas ya enviadas, sin depender del estado `posted`.

### Compatibility
- Probado en Odoo 12 a 18.


## [1.0.2] - 2025-07-02
### Added
- Añadido archivo `requirements.txt` con las dependencias Python necesarias para la firma electrónica.
- Documentación ampliada en el README con instrucciones para instalar los paquetes requeridos (`signxml`, `cryptography`, `pyOpenSSL`, `lxml[html_clean]`).

### Compatibility
- Probado en Odoo 12 a 18.


## [1.0.1] - 2025-06-27
### Changed
- Implementado encadenamiento de hash conforme al RD 1007/2023.
- Se calcula siempre el `verifactu_previous_hash` con orden basado en `verifactu_date_sent`.
- Se evita encadenamiento consigo misma en reenvíos.
- Se calcula y guarda `verifactu_hash` también en anulaciones.
- Protección añadida: no se puede modificar factura enviada sin `force_recalculate=True`.

### Compatibility
- Probado en Odoo 12 a 18.

## [1.0.0] - 2025-06-01
### Initial release
- Generación y firma de XMLs VeriFactu.
- Envío de facturas y generación de QR.
- funcionalidades base