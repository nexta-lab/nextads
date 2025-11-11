from odoo import models, fields


class VerifactuHelpWizard(models.TransientModel):
    _name = "verifactu.help.wizard"
    _description = "Ayuda del módulo VeriFactu"

    help_text = fields.Html(
        string="Guía del módulo",
        readonly=True,
        sanitize=False,
        default=lambda self: self._get_help_text(),
    )

    def _get_help_text(self):
        return """
        <h2>🧾 Bienvenido al módulo VeriFactu para Odoo</h2>
        <p>Este módulo ha sido diseñado para ayudarte a cumplir con la normativa de la Agencia Tributaria (AEAT) sobre la trazabilidad de facturas mediante el sistema Veri*factu.</p>

        <p>A continuación te explicamos las secciones que verás en la factura y qué puedes hacer en cada una:</p>

        <h3>🔒 Estado y Huellas (Hashes)</h3>
        <ul>
        <li><b>Hash VeriFactu:</b> Es una especie de "firma digital" que identifica de forma única esta factura según su contenido y la fecha. Se usa para asegurar que no ha sido alterada.</li>
        <li><b>Hash Anterior:</b> Es el hash de la última factura enviada antes que esta. Se guarda automáticamente al generar una nueva para mantener una cadena de integridad entre todas las facturas.</li>
        </ul>

        <h3>📤 Estado de Envío</h3>
        <ul>
        <li><b>Estado VeriFactu:</b> Indica en qué situación está esta factura respecto al sistema de la AEAT. Puede ser "pendiente", "enviado", "aceptado con errores", "rechazado", etc.</li>
        <li><b>Marcas de envío:</b> Se usan para indicar si fue enviada correctamente o si dio error.</li>
        </ul>

        <h3>📁 Descarga de Archivos</h3>
        <ul>
        <li><b>XML VeriFactu:</b> El archivo técnico generado para la factura, aún sin enviar.</li>
        <li><b>XML SOAP VeriFactu:</b> La versión que se envía a la AEAT, envuelta en un sobre SOAP según su especificación.</li>
        <li><b>QR VeriFactu:</b> Un código QR generado que puedes imprimir en la factura como identificador visual.</li>
        </ul>

        <h3>🛠️ Herramientas de Verificación</h3>
        <ul>
        <li><b>Verificar Hash:</b> Vuelve a calcular el hash para comprobar si coincide con el guardado. Si no coincide, probablemente ha habido cambios en la factura desde que se firmó.</li>
        <li><b>Verificar Firma Electrónica:</b> Comprueba si el XML contiene una firma válida según el certificado configurado.</li>
        <li><b>Verificar Integridad:</b> Abre el XML generado y comprueba que todos los datos importantes (como importe, NIF, fecha...) coinciden con los que tiene la factura en Odoo.</li>
        <li><b>Comprobar Encadenamiento:</b> Verifica si esta factura está correctamente enlazada con la anterior según las reglas del sistema VeriFactu.</li>
        </ul>

        <h3>📊 Gestión de Eventos y Modo Manual</h3>
        <ul>
        <li><b>Iniciar NO VERI*FACTU:</b> Si tienes un requerimiento de Hacienda, puedes activar este modo para enviar facturas de forma manual, sin la firma automática. Deberás indicar el código de requerimiento que te han dado.</li>
        <li><b>Activar detección de anomalías:</b> Si activas esta opción, el sistema monitorizará automáticamente si hay errores repetidos, hashes inconsistentes o cambios sospechosos.</li>
        <li><b>Exportar registros:</b> Te permite descargar un informe con todos los eventos que han sucedido en relación con esta factura (envíos, errores, verificaciones...).</li>
        <li><b>Restaurar desde copia:</b> Si hubo algún error grave, esta opción intenta restaurar los eventos desde una copia anterior.</li>
        </ul>

        <h3>📑 Gestión de Errores</h3>
        <ul>
        <li><b>Ver Error en detalle:</b> Muestra un texto completo con la descripción técnica del error que ha devuelto la AEAT.</li>
        <li><b>Ver códigos de error:</b> Abre una lista con todos los códigos de error posibles, su significado y posibles soluciones.</li>
        </ul>

        <h3>🖥️ Sistema Informático Declarado</h3>
        <ul>
            <li><b>Nombre del Sistema:</b> Es el nombre que declaras como tu software de facturación. Puede ser personalizado desde los ajustes del módulo.</li>
            <li><b>ID del Sistema:</b> Un identificador único del sistema, obligatorio en el XML VeriFactu.</li>
            <li><b>Versión del Sistema:</b> Indica la versión del software que estás usando.</li>
            <li><b>Número de Instalación:</b> Un número único por instalación. Si usas varias instalaciones de Odoo, puedes configurar uno distinto por empresa.</li>
            <li><b>Solo uso VeriFactu:</b> Indica si el sistema está exclusivamente dedicado a emitir facturas bajo VeriFactu o si también emite otros tipos.</li>
            <li><b>Multi OT posible:</b> Declaración sobre si el sistema puede manejar múltiples operadores tecnológicos.</li>
            <li><b>Indicador múltiples OT:</b> Confirma si efectivamente se están usando múltiples operadores tecnológicos.</li>
        </ul>
        
        <p style="font-size: 90%; color: gray;">
            ¿Dudas? Contacta con soporte a traves del correo rubikdevodoo@gmail.com o revisa la documentación técnica del módulo. Recuerda que este sistema ha sido desarrollado para facilitarte el cumplimiento normativo sin tener que preocuparte por los detalles técnicos.
            </p>
            """
