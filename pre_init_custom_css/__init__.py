from odoo import api, SUPERUSER_ID
import os

def _pre_init_referral(cr):
    # Source file path
    file_name = '/home/odoo/src/user/OCA/mis-builder/mis_builder/static/src/css/custom.css'
    
    # Crear el directorio si no existe
    dir_name = os.path.dirname(file_name)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    
    # Crear el archivo solo si no existe
    if not os.path.exists(file_name):
        open(file_name, 'x').close()