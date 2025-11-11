{
    "name": "Veri*Factu - Integración con la AEAT (España)",
    "id":"l10n_es_verifactu",
    "version": "2.2.0",
    "author": "Mr Rubik",
    "maintainer": "Mr Rubik",
    "website": "https://www.mrrubik.com",
    "price": 270,
    "currency": "USD",
    "category": "Accounting",
    "summary": "Integración técnica con AEAT mediante Veri*Factu para facturas electrónicas .",
    "description": """
Este módulo permite enviar facturas electrónicas a la AEAT siguiendo el esquema técnico de Veri*Factu, conforme a la normativa española vigente.

Genera un XML estructurado, lo firma digitalmente, lo adjunta a la factura y gestiona el envío a la Agencia Tributaria, registrando el estado, errores y reintentos si es necesario.

Este módulo cumple con los requisitos técnicos establecidos por la AEAT en el Real Decreto 1007/2023 y ha sido validado en el entorno oficial de pruebas.  
⚠️ En caso de cambios futuros en la normativa, podrían requerirse actualizaciones.
""",
    "depends": ["account", "base_setup"],
"external_dependencies": {
    "python": ["cryptography", "lxml", "signxml", "qrcode", "PyJWT", "requests", "packaging"],
},
    "data": [
        'data/anomaly_cron.xml',
        'data/ir_cron_verifactu.xml',
        "data/verifactu_cron_daily.xml",
        "security/ir.model.access.csv",
        "views/invoice/account_move_views.xml",
        "views/config/verifactu_mode_history_views.xml",
        "views/config/verifactu_anomaly_views.xml",
        "views/wizards/no_verifactu_requirement_wizard.xml",
        "views/wizards/verifactu_error_codes_wizard.xml",
        "views/wizards/verifactu_help_wizard.xml",
        "views/invoice/account_move_tree_verifactu.xml",
        "views/invoice/account_move_operation_date.xml",
        # "views/invoice/qr/account_invoice_report_qr.xml",
        "views/config/res_config_settings.xml",
        "data/verifactu_update_checker_cron.xml",
        "data/attachments.xml",
    ],
    "controllers": [
        "controllers/download_qr.py",
        "controllers/download_verifactu_xml.py",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_es_verifactu/static/src/css/verifactu_styles.css",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "OPL-1",
    "images": ["static/description/img/screenshot.png"],
}
