# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    out_move_id = fields.Many2one("account.move",string="Delivery Valuation Journal Entry",readonly=True, copy=False)
    in_move_id = fields.Many2one("account.move", string="Return Valuation Journal Entry", readonly=True, copy=False)

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.state != "done":
                continue
            if picking.picking_type_code == "outgoing":
                if picking.out_move_id:
                    continue
                am = picking._create_picking_je(direction="out")
                if am:
                    picking.out_move_id = am.id
            elif picking.picking_type_code == "incoming":
                if picking.in_move_id:
                    continue
                am = picking._create_picking_je(direction="in")
                if am:
                    picking.in_move_id = am.id
        return res

    def _get_inventory_valuation_journal(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        if company.account_stock_journal_id:
            return company.account_stock_journal_id
        return self.env["account.journal"].search([
            ("company_id", "=", company.id),
            ("type", "=", "general"),
            ("name", "ilike", "valuation"),
        ], limit=1)

    def _get_move_done_qty(self, move):
        self.ensure_one()
        mls = move.move_line_ids.filtered(lambda ml: ml.picking_id.id == self.id)
        return sum(mls.mapped("quantity")) if mls else 0.0

    def _create_picking_je(self, direction):
        """
            Bloqueos realizados (Validar que sean correctos):
            - Si mv.value == 0 => error (no postea)
            - Si ya existe journal entry para esa dirección => error claro
        """
        self.ensure_one()

        if direction not in ("out", "in"):
            raise UserError(_("Invalid direction. Use 'out' or 'in'."))

        if direction == "out" and self.out_move_id:
            raise UserError(_(
                "Esta entrega ya tiene un asiento contable asignado.\n\n"
                "Entrega: %s\n"
                "Asiento Contable: %s"
            ) % (self.name, self.out_move_id.name))

        if direction == "in" and self.in_move_id:
            raise UserError(_(
                "Este recepción/retorno ya tiene un asiento contable asignado.\n\n"
                "Recepción/Retorno: %s\n"
                "Asiento Contable: %s"
            ) % (self.name, self.in_move_id.name))

        if direction == "out" and self.picking_type_code != "outgoing":
            return False
        if direction == "in" and self.picking_type_code != "incoming":
            return False

        journal = self._get_inventory_valuation_journal()
        if not journal:
            raise UserError(_("Diario de Valorización de Inventario no encontrado. Configura el diario correctamente en su empresa."))

        currency = self.company_id.currency_id

        moves = self.move_ids.filtered(lambda m: m.state == "done" and m.product_id and m.product_id.is_storable)
        if not moves:
            return False

        lines = []
        total = 0.0
        zero_value_products = []

        for mv in moves:
            if not self._get_move_done_qty(mv):
                continue

            value = mv.value or 0.0

            if currency.is_zero(value):
                zero_value_products.append(mv.product_id.display_name)
                continue

            amount = currency.round(abs(value))
            if not amount:
                zero_value_products.append(mv.product_id.display_name)
                continue

            if not mv.account_id:
                raise UserError(_(
                    "Cuenta contable faltante en la linea de producto: '%s'.\n"
                    "Por favor asigne la cuenta antes de seguir validando."
                ) % mv.product_id.display_name)

            accounts = mv.product_id._get_product_accounts()
            stock_acc = accounts.get("stock_valuation")
            if not stock_acc:
                raise UserError(_(
                    "La categoria del producto no tiene la cuenta de valorizacion de inventario asignada '%s'."
                ) % mv.product_id.display_name)

            ref = f"{self.name} - {mv.product_id.display_name}"

            override_line = {
                "name": ref,
                "account_id": mv.account_id.id,
                "product_id": mv.product_id.id,
            }
            if mv.analytic_distribution:
                override_line["analytic_distribution"] = mv.analytic_distribution

            if direction == "out":
                lines.append((0, 0, {
                    "name": ref,
                    "account_id": stock_acc.id,
                    "debit": 0.0,
                    "credit": amount,
                    "product_id": mv.product_id.id,
                }))
                override_line.update({"debit": amount, "credit": 0.0})
                lines.append((0, 0, override_line))

            else:
                lines.append((0, 0, {
                    "name": ref,
                    "account_id": stock_acc.id,
                    "debit": amount,
                    "credit": 0.0,
                    "product_id": mv.product_id.id,
                }))
                override_line.update({"debit": 0.0, "credit": amount})
                lines.append((0, 0, override_line))

            total += amount

        if zero_value_products:
            raise UserError(_(
                "Operación Bloqueada: uno o mas lineas tienen un valor de valorizacion de 0.\n\n"
                "Productos:\n- %s\n\n"
            ) % "\n- ".join(zero_value_products))

        if not lines or total <= 0:
            raise UserError(_(
                "No se produjeron lineas de valorizacion.\n"
            ))

        move_label = "Entrega" if direction == "out" else "Recepción/Retorno"
        am = self.env["account.move"].sudo().create({
            "move_type": "entry",
            "ref": f"{move_label} Journal Entry - {self.name}",
            "date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "line_ids": lines,
        })

        am._post()
        if "account_move_id" in self.env["stock.move"]._fields:
            moves.sudo().write({"account_move_id": am.id})

        self.message_post(body=_("%s Asiento contable creado: %s") % (move_label, am.name))
        return am