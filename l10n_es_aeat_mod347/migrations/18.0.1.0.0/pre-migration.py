import logging

_logger = logging.getLogger(__name__)

def migrate(cr, version):
   
    _logger.info("Executing l10n_es_aeat_mod347 PRE-migration script ")
    
      
    cr.execute ("ALTER TABLE res_partner ALTER COLUMN not_in_mod347 DROP DEFAULT,ALTER COLUMN not_in_mod347 TYPE jsonb USING to_jsonb(not_in_mod347);")
    cr.execute ("ALTER TABLE res_partner ALTER COLUMN not_in_mod347 DROP DEFAULT,ALTER COLUMN not_in_mod347 TYPE jsonb USING not_in_mod347::jsonb;")
    cr.execute ("ALTER TABLE account_move ALTER COLUMN not_in_mod347 DROP DEFAULT,ALTER COLUMN not_in_mod347 TYPE jsonb USING to_jsonb(not_in_mod347);")
    cr.execute ("ALTER TABLE account_move ALTER COLUMN not_in_mod347 DROP DEFAULT,ALTER COLUMN not_in_mod347 TYPE jsonb USING not_in_mod347::jsonb;")

    cr.execute("""
        UPDATE ir_ui_view
        SET active = false
        WHERE name = %s
    """, (
        'view_move_form',
    ))

    _logger.info("l10n_es_aeat_mod347 pre-migration  finished.")
