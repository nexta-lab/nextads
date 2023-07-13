# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _



class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'


    def _get_aggregated_product_quantities(self, **kwargs):
        """Returns dictionary of products and corresponding values of interest grouped by optional kit_name

        Removes descriptions where description == kit_name. kit_name is expected to be passed as a
        kwargs value because this is not directly stored in move_line_ids. Unfortunately because we
        are working with aggregated data, we have to loop through the aggregation to do this removal.

        arguments: kit_name (optional): string value of a kit name passed as a kwarg
        returns: dictionary {same_key_as_super: {same_values_as_super, ...}
        """
        aggregated_move_lines = super()._get_aggregated_product_quantities(**kwargs)
        if self.move_id and self.move_id.sale_line_id:
            kit_name = self.move_id.sale_line_id.name
            if kit_name:
                for aggregated_move_line in aggregated_move_lines:
                    aggregated_move_lines[aggregated_move_line]['description'] = ""
                    aggregated_move_lines[aggregated_move_line]['name'] = kit_name
        return aggregated_move_lines
