# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class InventoryRevaluationLine(models.Model):
    _name = "inventory.revaluation.line"
    _description = "Inventory Revaluation Line"
    _order = "id asc"

    revaluation_id = fields.Many2one("inventory.revaluation", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="revaluation_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="revaluation_id.currency_id", readonly=True)
    state = fields.Selection(related="revaluation_id.state", store=True, readonly=True)

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True
    )

    counterpart_account_id = fields.Many2one(
        "account.account",
        string="Account",
        required=True,
    )

    # Live draft values (NOT stored)
    qty_on_hand = fields.Float(string="Current Quantity", compute="_compute_qty_on_hand", store=False, readonly=True)
    current_cost = fields.Float(string="Current Cost", compute="_compute_current_cost", store=False, readonly=True)

    new_cost = fields.Float(
        string="New Cost",
        required=True,
    )

    value_change = fields.Monetary(
        string="Value Change",
        currency_field="currency_id",
        compute="_compute_value_change",
        store=False,
        readonly=True,
    )

    # Frozen snapshot fields (persisted per line)
    qty_snapshot = fields.Float(string="Qty (Snapshot)", readonly=True, copy=False)
    current_cost_snapshot = fields.Float(string="Current Cost (Snapshot)", readonly=True, copy=False)
    new_cost_snapshot = fields.Float(string="New Cost (Snapshot)", readonly=True, copy=False)
    value_change_snapshot = fields.Monetary(string="Value Change (Snapshot)", currency_field="currency_id", readonly=True, copy=False)

    @api.depends("product_id", "company_id")
    def _compute_qty_on_hand(self):
        for rec in self:
            if not rec.product_id:
                rec.qty_on_hand = 0.0
                continue
            rec.qty_on_hand = rec.product_id.with_company(rec.company_id).qty_available

    @api.depends("product_id", "company_id")
    def _compute_current_cost(self):
        for rec in self:
            rec.current_cost = rec.product_id.with_company(rec.company_id).standard_price if rec.product_id else 0.0

    @api.depends("qty_on_hand", "current_cost", "new_cost")
    def _compute_value_change(self):
        for rec in self:
            if rec.new_cost is None:
                rec.value_change = 0.0
                continue
            rec.value_change = rec.qty_on_hand * (rec.new_cost - rec.current_cost)