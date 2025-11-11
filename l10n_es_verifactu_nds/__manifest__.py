{
    "name": "Veri*Factu NDS",
    "id":"l10n_es_verifactu_es",
    "version": "16.0.0.1",
    "author": "NextaDS",
    "maintainer": "NextaDS",
    "category": "Accounting",
    "summary": "Este módulo es una extensión del módulo de Mr.Rubik.",
    "description": """
        Este módulo es una extensión del módulo verifactu de Mr.Rubik
    """,
    "depends": ["account", "base_setup", "l10n_es_verifactu"],
    "external_dependencies": {
        "python": ["cryptography", "lxml", "signxml", "qrcode", "PyJWT", "requests", "packaging"],
    },
    "data": [
        "views/invoice/qr/account_invoice_report_qr.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    'license': "LGPL-3",
}
