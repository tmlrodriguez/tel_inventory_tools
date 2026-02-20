# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class InventoryRevaluation(models.Model):
    _name = "inventory.revaluation"
    _description = "Inventory Revaluation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Reference", required=True, copy=False, default=lambda self: _("New"), tracking=True, readonly=True, states={"draft": [("readonly", False)]})
    date = fields.Date(string="Date", default=fields.Date.context_today, required=True, tracking=True, readonly=True, states={"draft": [("readonly", False)]})
    company_id = fields.Many2one("res.company", string="Company", required=True, default=lambda self: self.env.company, tracking=True, readonly=True, states={"draft": [("readonly", False)]}) 
    journal_id = fields.Many2one("account.journal", string="Journal", readonly=True, compute="_compute_journal_id", store=True)
    line_ids = fields.One2many("inventory.revaluation.line", "revaluation_id", string="Lines", copy=True, readonly=True)
    state = fields.Selection([("draft", "Borrador"), ("posted", "Confirmado"), ("cancel", "Cancelado")], default="draft", string="Status", tracking=True)
    account_move_id = fields.Many2one("account.move", string="Journal Entry", readonly=True, copy=False)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    total_value_change_stored = fields.Monetary(string="Total Value Change (Stored)", currency_field="currency_id", readonly=True, copy=False)
    total_value_change = fields.Monetary(string="Total Value Change", currency_field="currency_id", compute="_compute_total_value_change", store=False, readonly=True)

    @api.depends("company_id")
    def _compute_journal_id(self):
        Journal = self.env["account.journal"]
        for rec in self:
            company = rec.company_id or self.env.company
            journal = company.account_stock_journal_id
            if journal:
                rec.journal_id = journal.id
                continue

            journal = Journal.search([
                ("company_id", "=", company.id),
                ("type", "=", "general"),
                ("name", "ilike", "valuation"),
            ], limit=1)
            rec.journal_id = journal.id if journal else False

    def _compute_total_value_change(self):
        for rec in self:
            if rec.state == "draft":
                rec.total_value_change = sum(rec.line_ids.mapped("value_change"))
            else:
                rec.total_value_change = rec.total_value_change_stored or 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("inventory.revaluation") or _("New")
        return super().create(vals_list)

    def _validate_before_post(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Solo documento en borrados se pueden confirmar."))
        if not self.journal_id:
            raise UserError(_("Diario de valoración de inventario no encontrado"))
        if not self.line_ids:
            raise UserError(_("Agregue al menos una linea para confirmar la revalorización."))

        missing_acc = self.line_ids.filtered(lambda l: not l.counterpart_account_id)
        if missing_acc:
            raise UserError(_("El campo de cuenta no se encuentra definido."))

        effective = self.line_ids.filtered(lambda l: l.value_change and abs(l.value_change) > 0.0000001)
        if not effective:
            raise UserError(_("Este costo no genera ningun cambio."))

    def action_post(self):
        for rec in self:
            rec._validate_before_post()
            rec._freeze_lines()
            move = rec._create_account_move_from_frozen()
            rec.account_move_id = move.id
            rec._apply_new_costs()
            rec.state = "posted"

            rec.message_post(body=_("Revalorización de inventario confirmada: asiento contable creado: %s") % move.name)
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == "posted":
                pass
            if not rec.total_value_change_stored:
                rec._freeze_lines()

            rec.state = "cancel"
        return True

    def _freeze_lines(self):
        self.ensure_one()
        total = 0.0
        for line in self.line_ids:
            qty = line.qty_on_hand
            current_cost = line.current_cost
            new_cost = line.new_cost
            value_change = line.value_change
            line.write({
                "qty_snapshot": qty,
                "current_cost_snapshot": current_cost,
                "new_cost_snapshot": new_cost,
                "value_change_snapshot": value_change,
            })
            total += value_change
        self.total_value_change_stored = total

    def _get_product_valuation_account(self, product):
        product = product.with_company(self.company_id)
        accounts = product._get_product_accounts()
        valuation = accounts.get("stock_valuation")
        if valuation:
            return valuation
        categ = product.categ_id
        if getattr(categ, "property_stock_valuation_account_id", False):
            return categ.property_stock_valuation_account_id
        raise UserError(_("Cuenta de Valorizacion de Inventario no definida en el producto '%s'.") % product.display_name)

    def _create_account_move_from_frozen(self):
        self.ensure_one()
        company = self.company_id
        currency = company.currency_id
        lines_cmd = []
        for line in self.line_ids:
            amount = currency.round(line.value_change_snapshot or 0.0)
            if not amount or abs(amount) <= 0.0000001:
                continue
            product = line.product_id.with_company(company)
            valuation_acc = self._get_product_valuation_account(product)
            counterpart_acc = line.counterpart_account_id
            label = f"{self.name} - {product.display_name}"
            if amount > 0:
                valuation_debit, valuation_credit = amount, 0.0
                cp_debit, cp_credit = 0.0, amount
            else:
                amount_abs = abs(amount)
                valuation_debit, valuation_credit = 0.0, amount_abs
                cp_debit, cp_credit = amount_abs, 0.0
            lines_cmd.append((0, 0, {
                "name": label,
                "account_id": valuation_acc.id,
                "debit": valuation_debit,
                "credit": valuation_credit,
                "product_id": product.id,
            }))
            lines_cmd.append((0, 0, {
                "name": label,
                "account_id": counterpart_acc.id,
                "debit": cp_debit,
                "credit": cp_credit,
                "product_id": product.id,
            }))

        if not lines_cmd:
            raise UserError(_("No se generan lineas contables. No hay nada que confirmart."))

        move = self.env["account.move"].create({
            "move_type": "entry",
            "ref": self.name,
            "date": self.date,
            "journal_id": self.journal_id.id,
            "company_id": company.id,
            "line_ids": lines_cmd,
        })
        move.action_post()
        return move

    def _apply_new_costs(self):
        self.ensure_one()
        for line in self.line_ids:
            if line.new_cost_snapshot is None:
                continue
            line.product_id.with_company(self.company_id).sudo().write({
                "standard_price": line.new_cost_snapshot
            })