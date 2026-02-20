# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    analytic_distribution = fields.Json(string="Analytic Distribution", default=dict, help="Distribución analitica para este asiento.")
    account_id = fields.Many2one(comodel_name="account.account", string="Account (Override)")
    analytic_precision = fields.Integer(string="Analytic Precision", compute="_compute_analytic_precision", store=False)
    
    @api.depends("company_id")
    def _compute_analytic_precision(self):
        for move in self:
            move.analytic_precision = 2