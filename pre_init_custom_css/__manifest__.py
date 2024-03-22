# © 2024
# License AGPL-3 - See https://www.gnu.org/licenses/agpl-3.0.html
{
    "name": "Pre init custom css",
    "summary": "Crea el fichero custom.css para evitar fallos",
    "version": "14.0.1.0.3",
    "author": "NextaDS",
    "maintainers": ["Nextads"],
    "website": "https://www.nextads.es",
    "category": "account",
    "license": "AGPL-3",
    "depends": ["mis_builder"],
    "data": [
    ],
    "application": False,
    "installable": True,
    "auto_install": False,
    'pre_init_hook': '_pre_init_referral',
}
