from odoo import api, SUPERUSER_ID
import os

def _pre_init_referral(cr):
    # Source file path
    file_name = '/home/odoo/src/user/OCA/mis-builder/mis_builder/static/src/css/custom.css'
    open(file_name, 'x').close()