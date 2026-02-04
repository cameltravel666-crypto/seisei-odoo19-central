# -*- coding: utf-8 -*-

import secrets
import hashlib
import json
import base64
from datetime import datetime, timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

import logging
_logger = logging.getLogger(__name__)


class QrOrder(models.Model):
    """扫码点餐订单模型"""
    _name = 'qr.order'
    _description = 'QR Order / 扫码订单'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Order Number / 订单号',
        required=True,
        readonly=True,
        default=lambda self: self._generate_order_number(),
        copy=False,
        tracking=True
    )
    
    # 关联
    session_id = fields.Many2one(
        'qr.session',
        string='Session / 会话',
        required=True,
        ondelete='cascade'
    )
    table_id = fields.Many2one(
        'qr.table',
        string='Table / 餐桌',
        related='session_id.table_id',
        store=True,
        readonly=True
    )
    pos_config_id = fields.Many2one(
        'pos.config',
        string='POS Config / POS配置',
        related='table_id.pos_config_id',
        store=True,
        readonly=True
    )
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order / POS订单',
        readonly=True,
        help='同步到 POS 系统后的订单'
    )
    pos_session_id = fields.Many2one(
        'pos.session',
        string='POS Session / POS会话',
        readonly=True,
        help='关联的 POS 会话'
    )
    restaurant_table_id = fields.Many2one(
        'restaurant.table',
        string='Restaurant Table / POS餐桌',
        related='table_id.pos_table_id',
        store=True,
        readonly=True,
        help='POS 系统中的餐桌'
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer / 客户',
        help='关联的客户（可选）'
    )
    source = fields.Selection([
        ('qr', 'QR Code / 扫码点餐'),
        ('pos', 'POS / 柜台'),
        ('kiosk', 'Kiosk / 自助终端'),
    ], string='Source / 来源', default='qr', readonly=True)

    # 订单状态
    state = fields.Selection([
        ('cart', 'Cart / 购物车'),
        ('ordered', 'Ordered / 已下单'),
        ('cooking', 'Cooking / 制作中'),
        ('serving', 'Serving / 可加菜'),
        ('paid', 'Paid / 已结账'),
        ('cancelled', 'Cancelled / 已取消'),
    ], string='Status / 状态', default='cart', required=True, tracking=True)
    
    # 订单行
    line_ids = fields.One2many(
        'qr.order.line',
        'order_id',
        string='Order Lines / 订单行'
    )
    
    # 金额
    total_amount = fields.Float(
        string='Total Amount / 总金额',
        compute='_compute_totals',
        store=True,
        tracking=True
    )
    total_qty = fields.Float(
        string='Total Quantity / 总数量',
        compute='_compute_totals',
        store=True
    )
    
    # 备注
    note = fields.Text(
        string='Note / 备注',
        help='客户特殊要求'
    )
    
    # 时间记录
    order_time = fields.Datetime(
        string='Order Time / 下单时间',
        readonly=True
    )
    cooking_time = fields.Datetime(
        string='Cooking Start / 开始制作时间',
        readonly=True
    )
    serve_time = fields.Datetime(
        string='Serve Time / 上菜时间',
        readonly=True
    )

    # 幂等性控制（防重复提交）
    print_idempotency_key = fields.Char(
        string='Print Idempotency Key',
        readonly=True,
        copy=False,
        index=True,
        help='用于防止重复打印的幂等键，格式: {qr_order_id}_{revision}'
    )
    print_revision = fields.Integer(
        string='Print Revision',
        default=0,
        readonly=True,
        help='打印版本号，每次加菜+1'
    )
    last_print_time = fields.Datetime(
        string='Last Print Time / 最后打印时间',
        readonly=True
    )

    @api.model
    def _generate_order_number(self):
        """生成订单号"""
        return f"QRO-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2).upper()}"

    @api.depends('line_ids.subtotal', 'line_ids.qty')
    def _compute_totals(self):
        """计算总金额和总数量"""
        for record in self:
            record.total_amount = sum(record.line_ids.mapped('subtotal'))
            record.total_qty = sum(record.line_ids.mapped('qty'))

    def action_submit_order(self):
        """
        提交订单

        返回: dict
        - success: True/False
        - error_code: 错误代码
        - error_message: 错误消息
        """
        self.ensure_one()

        if self.state != 'cart':
            return {
                'success': False,
                'error_code': 'INVALID_STATE',
                'error_message': '只能提交购物车状态的订单'
            }
        if not self.line_ids:
            return {
                'success': False,
                'error_code': 'EMPTY_ORDER',
                'error_message': '订单不能为空'
            }

        # 先更新状态为已下单
        self.write({
            'state': 'ordered',
            'order_time': fields.Datetime.now(),
        })

        # 同步到 POS（包含 POS Session 验证、KDS 通知、厨房打印）
        success, error_code, error_message = self._sync_to_pos()
        if not success:
            # 同步失败，回滚状态
            self.write({'state': 'cart', 'order_time': False})
            return {
                'success': False,
                'error_code': error_code,
                'error_message': error_message
            }

        # 发送实时通知到客户端
        self._send_notification('order_submitted')

        # 自动转为制作中
        self.write({
            'state': 'cooking',
            'cooking_time': fields.Datetime.now(),
        })

        return {'success': True}

    def action_add_items(self, lines_data):
        """
        加菜功能
        lines_data: [{'product_id': x, 'qty': y, 'note': z}, ...]
        """
        self.ensure_one()
        if self.state not in ['cooking', 'serving']:
            raise UserError('当前状态不允许加菜')

        # 获取当前最大批次号
        max_batch = max(self.line_ids.mapped('batch_number') or [0])
        new_batch = max_batch + 1

        # 创建新的订单行
        for line_data in lines_data:
            self.env['qr.order.line'].create({
                'order_id': self.id,
                'product_id': line_data['product_id'],
                'qty': line_data.get('qty', 1),
                'note': line_data.get('note', ''),
                'batch_number': new_batch,
            })

        # 同步加菜到 POS（包含 KDS 和打印）
        self._sync_add_items_to_pos(new_batch)

        return True

    def _sync_to_pos(self):
        """
        同步订单到 POS 系统

        返回: (success, error_code, error_message)
        - success: True/False
        - error_code: 错误代码（如 'NO_POS_SESSION'）
        - error_message: 用户友好的错误消息

        幂等性保证：
        - 生成 idempotency_key = {qr_order_id}_{revision}
        - 如果同一 key 已存在且已打印，则跳过打印
        """
        self.ensure_one()

        # 0. 幂等性检查 - 生成当前版本的 idempotency_key
        new_revision = self.print_revision + 1
        new_idempotency_key = f"{self.id}_{new_revision}"

        # 检查是否已处理过此版本
        if self.print_idempotency_key == new_idempotency_key:
            _logger.info(f"Order {self.name} already processed with key {new_idempotency_key}, skipping duplicate")
            return True, None, None

        # 1. 验证 POS Session
        pos_session = self._get_active_pos_session()
        if not pos_session:
            _logger.warning(f"No active POS session for order {self.name}, config: {self.pos_config_id.name}")
            return False, 'NO_POS_SESSION', '店内未开台，请联系服务员开启 POS 系统'

        # 2. 检查当前 QR Session 是否已有关联的 POS 订单（用于合并同一客人的多次下单）
        # 注意：不再自动合并餐桌上其他 POS 订单，避免混入前一桌客人的旧订单
        restaurant_table = self.table_id.pos_table_id
        existing_pos_order = None
        if restaurant_table:
            session_qr_orders = self.env['qr.order'].sudo().search([
                ('session_id', '=', self.session_id.id),
                ('pos_order_id', '!=', False),
                ('state', '!=', 'cancelled'),
            ], order='create_date desc')

            if session_qr_orders:
                # 使用当前 Session 已关联的 POS 订单（如果仍为 draft）
                for qr_order in session_qr_orders:
                    if qr_order.pos_order_id.state == 'draft':
                        existing_pos_order = qr_order.pos_order_id
                        _logger.warning(f"[Sync] Found existing POS order {existing_pos_order.name} from current QR session")
                        break

            if not existing_pos_order:
                _logger.warning(f"[Sync] No existing POS order linked to current QR session, will create new one")

        if existing_pos_order:
            # 3a. 追加订单行到现有 POS 订单
            _logger.info(f"Found existing POS order {existing_pos_order.name} for table {restaurant_table.table_number}, appending lines")
            self._append_lines_to_pos_order(existing_pos_order, pos_session)
            pos_order = existing_pos_order
        else:
            # 3b. 创建新的 POS 订单
            order_data = self._prepare_pos_order_data(pos_session)
            _logger.info(f"Creating new POS order for QR Order {self.name}")
            pos_order = self.env['pos.order'].create(order_data)
            _logger.info(f"Created POS Order {pos_order.name} for QR Order {self.name}")

        # 4. 更新 QR 订单的 POS 关联和幂等性字段
        self.write({
            'pos_order_id': pos_order.id,
            'pos_session_id': pos_session.id,
            'print_revision': new_revision,
            'print_idempotency_key': new_idempotency_key,
            'last_print_time': fields.Datetime.now(),
        })

        # 5. 创建 KDS 变更记录并发送通知
        self._create_kds_change(pos_order)

        # 6. 发送打印通知到 POS 前端
        # 打印代理运行在 POS 主机上，只有 POS 前端才能触发实际打印
        self._send_print_notification(pos_order)

        _logger.info(f"QR Order {self.name} synced to POS Order {pos_order.name} with idempotency_key {new_idempotency_key}")
        return True, None, None

    def _append_lines_to_pos_order(self, pos_order, pos_session):
        """将当前 QR 订单的商品行追加到现有 POS 订单"""
        for line in self.line_ids:
            product = line.product_id
            # 获取产品的税率配置
            fiscal_position = pos_session.config_id.default_fiscal_position_id
            taxes = product.taxes_id.filtered(lambda t: t.company_id == pos_session.company_id)
            if fiscal_position:
                taxes = fiscal_position.map_tax(taxes)

            # 计算含税/不含税价格
            price_unit = line.price_unit
            if taxes:
                tax_result = taxes.compute_all(
                    price_unit,
                    currency=pos_session.currency_id,
                    quantity=line.qty,
                    product=product,
                )
                price_subtotal = tax_result['total_excluded']
                price_subtotal_incl = tax_result['total_included']
            else:
                price_subtotal = price_unit * line.qty
                price_subtotal_incl = price_subtotal

            self.env['pos.order.line'].create({
                'order_id': pos_order.id,
                'product_id': product.id,
                'qty': line.qty,
                'price_unit': price_unit,
                'price_subtotal': price_subtotal,
                'price_subtotal_incl': price_subtotal_incl,
                'full_product_name': product.name,
                'customer_note': line.note or '',  # 不添加 [QR:xxx] 前缀，保持收据格式与 POS 一致
                'tax_ids': [(6, 0, taxes.ids)] if taxes else [],
                # 注意：不设置 skip_change，让 POS 前端正常处理订单
                # QR 已通过 YLHC Print Manager 发送厨房打印，POS 可以选择再次发送或忽略
            })

        # 重新计算 POS 订单总金额
        pos_order._onchange_amount_all()

        # 强制重新计算并保存金额（确保数据库中的值是最新的）
        new_amount_total = sum(line.price_subtotal_incl for line in pos_order.lines)
        new_amount_tax = sum(line.price_subtotal_incl - line.price_subtotal for line in pos_order.lines)
        pos_order.write({
            'amount_total': new_amount_total,
            'amount_tax': new_amount_tax,
        })
        _logger.warning(f"Appended {len(self.line_ids)} lines to POS order {pos_order.name}, new total={new_amount_total}, tax={new_amount_tax}")

    def _get_active_pos_session(self):
        """获取活跃的 POS 会话"""
        return self.env['pos.session'].search([
            ('config_id', '=', self.pos_config_id.id),
            ('state', '=', 'opened'),
        ], limit=1)

    def _prepare_pos_order_data(self, pos_session):
        """准备 POS 订单数据"""
        lines = []
        total_tax = 0.0
        total_amount = 0.0

        for line in self.line_ids:
            product = line.product_id
            # 获取产品的税率配置（使用 POS 会话的财务位置）
            fiscal_position = pos_session.config_id.default_fiscal_position_id
            taxes = product.taxes_id.filtered(lambda t: t.company_id == pos_session.company_id)
            if fiscal_position:
                taxes = fiscal_position.map_tax(taxes)

            # 计算含税/不含税价格
            price_unit = line.price_unit
            if taxes:
                # 计算税额
                tax_result = taxes.compute_all(
                    price_unit,
                    currency=pos_session.currency_id,
                    quantity=line.qty,
                    product=product,
                )
                price_subtotal = tax_result['total_excluded']
                price_subtotal_incl = tax_result['total_included']
                line_tax = price_subtotal_incl - price_subtotal
            else:
                price_subtotal = price_unit * line.qty
                price_subtotal_incl = price_subtotal
                line_tax = 0.0

            total_tax += line_tax
            total_amount += price_subtotal_incl

            lines.append((0, 0, {
                'product_id': product.id,
                'qty': line.qty,
                'price_unit': price_unit,
                'price_subtotal': price_subtotal,
                'price_subtotal_incl': price_subtotal_incl,
                'full_product_name': product.name,
                'customer_note': line.note or '',
                'tax_ids': [(6, 0, taxes.ids)] if taxes else [],
                # 注意：不设置 skip_change，让 POS 前端正常处理订单
            }))

        # 生成 pos_reference（格式：Order {session_id}-{sequence}）
        # 注意：不要使用 "QR"、"Self-Order"、"Kiosk" 等前缀，否则 POS 前端可能会将其识别为自助点餐订单并隐藏
        sequence = self.env['pos.order'].search_count([
            ('session_id', '=', pos_session.id)
        ]) + 1
        pos_reference = f"Order {pos_session.id:05d}-{sequence:04d}"

        # 获取 POS 配置的价格表（确保收据格式与 POS 直接下单一致）
        pricelist_id = pos_session.config_id.pricelist_id.id if pos_session.config_id.pricelist_id else False

        return {
            'session_id': pos_session.id,
            'config_id': self.pos_config_id.id,
            'table_id': self.table_id.pos_table_id.id if self.table_id.pos_table_id else False,
            'pos_reference': pos_reference,
            'pricelist_id': pricelist_id,
            'lines': lines,
            'amount_total': total_amount,
            'amount_tax': total_tax,
            'amount_paid': 0,
            'amount_return': 0,
            # 备注：pos.order 模型没有 note 字段，备注信息已存储在订单行的 customer_note 中
        }

    def _sync_add_items_to_pos(self, batch_number):
        """
        同步加菜到 POS

        幂等性保证：
        - 每次加菜生成新的 revision
        - idempotency_key = {qr_order_id}_{revision}
        """
        self.ensure_one()
        if not self.pos_order_id:
            _logger.warning(f"No POS order linked for QR order {self.name}")
            return False

        # 幂等性检查 - 生成新版本的 idempotency_key
        new_revision = self.print_revision + 1
        new_idempotency_key = f"{self.id}_{new_revision}"

        # 检查是否已处理过此版本（防止重复加菜打印）
        if self.print_idempotency_key == new_idempotency_key:
            _logger.info(f"Add items for order {self.name} already processed with key {new_idempotency_key}, skipping duplicate")
            return True

        pos_session = self.pos_order_id.session_id
        # 获取新批次的订单行
        new_lines = self.line_ids.filtered(lambda l: l.batch_number == batch_number)

        for line in new_lines:
            product = line.product_id
            # 获取产品的税率配置
            fiscal_position = pos_session.config_id.default_fiscal_position_id
            taxes = product.taxes_id.filtered(lambda t: t.company_id == pos_session.company_id)
            if fiscal_position:
                taxes = fiscal_position.map_tax(taxes)

            # 计算含税/不含税价格
            price_unit = line.price_unit
            if taxes:
                tax_result = taxes.compute_all(
                    price_unit,
                    currency=pos_session.currency_id,
                    quantity=line.qty,
                    product=product,
                )
                price_subtotal = tax_result['total_excluded']
                price_subtotal_incl = tax_result['total_included']
            else:
                price_subtotal = price_unit * line.qty
                price_subtotal_incl = price_subtotal

            self.env['pos.order.line'].create({
                'order_id': self.pos_order_id.id,
                'product_id': product.id,
                'qty': line.qty,
                'price_unit': price_unit,
                'price_subtotal': price_subtotal,
                'price_subtotal_incl': price_subtotal_incl,
                'full_product_name': product.name,
                'customer_note': f"[加菜 Batch {batch_number}] {line.note or ''}",
                'tax_ids': [(6, 0, taxes.ids)] if taxes else [],
                # 注意：不设置 skip_change，让 POS 前端正常处理订单
            })

        # 更新 POS 订单总金额（会自动重新计算税额）
        self.pos_order_id._onchange_amount_all()

        # 更新幂等性字段
        self.write({
            'print_revision': new_revision,
            'print_idempotency_key': new_idempotency_key,
            'last_print_time': fields.Datetime.now(),
        })

        # 创建 KDS 变更记录（仅包含新批次的商品）
        self._create_kds_change_for_batch(self.pos_order_id, new_lines)

        # 发送打印通知到 POS 前端（打印代理在 POS 主机上）
        self._send_print_notification_for_batch(self.pos_order_id, new_lines)

        _logger.info(f"Added {len(new_lines)} items (batch {batch_number}) to POS order {self.pos_order_id.name} with idempotency_key {new_idempotency_key}")
        return True

    def _create_kds_change_for_batch(self, pos_order, lines):
        """为指定的订单行创建 KDS 变更记录"""
        try:
            if 'ab_pos.order.change' not in self.env:
                return

            existing_changes = self.env['ab_pos.order.change'].sudo().search([
                ('order_id', '=', pos_order.id)
            ])
            next_sequence = len(existing_changes) + 1

            change = self.env['ab_pos.order.change'].sudo().create({
                'order_id': pos_order.id,
                'sequence_number': next_sequence,
                'created_at': fields.Datetime.now(),
            })

            for line in lines:
                self.env['ab_pos.order.change.line'].sudo().create({
                    'change_id': change.id,
                    'product_id': line.product_id.id,
                    'qty': line.qty,
                    'note': line.note or '',
                    'state': 'cooking',
                })

            pos_order.sudo().note_order_change()
            _logger.info(f"Created KDS change #{next_sequence} for batch with {len(lines)} lines")

        except Exception as e:
            _logger.error(f"Failed to create KDS change for batch: {e}")

    def _create_kds_change(self, pos_order):
        """
        创建 KDS 变更记录并发送通知
        这个方法模拟 POS 前端的 sendOrderInPreparationUpdateLastChange 行为
        """
        self.ensure_one()
        try:
            # 检查 ab_pos.order.change 模型是否存在
            if 'ab_pos.order.change' not in self.env:
                _logger.warning("KDS module (ab_pos.order.change) not installed, skipping KDS notification")
                return

            # 计算下一个序列号
            existing_changes = self.env['ab_pos.order.change'].sudo().search([
                ('order_id', '=', pos_order.id)
            ])
            next_sequence = len(existing_changes) + 1

            # 创建变更记录
            change = self.env['ab_pos.order.change'].sudo().create({
                'order_id': pos_order.id,
                'sequence_number': next_sequence,
                'created_at': fields.Datetime.now(),
            })

            # 为每个订单行创建变更行
            for line in self.line_ids:
                self.env['ab_pos.order.change.line'].sudo().create({
                    'change_id': change.id,
                    'product_id': line.product_id.id,
                    'qty': line.qty,
                    'note': line.note or '',
                    'state': 'cooking',
                })

            # 发送 KDS 通知（通过 pos.order 的 note_order_change 方法）
            pos_order.sudo().note_order_change()

            _logger.info(f"Created KDS change #{next_sequence} for POS order {pos_order.name} with {len(self.line_ids)} lines")

        except Exception as e:
            _logger.error(f"Failed to create KDS change for order {self.name}: {e}")

    def _filter_lines_by_categories(self, printer_categ_ids, lines=None):
        """
        按产品分类过滤订单行

        复制 POS 的 filterChangeByCategories 逻辑：
        - 如果打印机没有配置分类（printer_categ_ids 为空），则返回所有行
        - 否则，只返回产品的 pos_categ_ids 与打印机分类匹配的行
        - 支持父分类匹配（如果产品分类是打印机分类的子分类，也匹配）

        Args:
            printer_categ_ids: set of pos.category IDs that the printer handles
            lines: (optional) recordset of qr.order.line to filter, defaults to self.line_ids

        Returns:
            recordset of qr.order.line that match the printer's categories
        """
        self.ensure_one()

        # 使用提供的 lines 或默认 self.line_ids
        lines_to_filter = lines if lines is not None else self.line_ids

        # 如果打印机没有配置分类，返回所有行
        if not printer_categ_ids:
            return lines_to_filter

        # 获取所有相关分类的父分类（用于子分类匹配）
        def get_parent_categ_ids(categ):
            """递归获取分类及其所有父分类的 ID"""
            ids = set()
            while categ:
                ids.add(categ.id)
                categ = categ.parent_id
            return ids

        matched_lines = self.env['qr.order.line']
        for line in lines_to_filter:
            product = line.product_id
            if not product:
                continue

            # 获取产品的 POS 分类
            product_categs = product.pos_categ_ids
            if not product_categs:
                # 产品没有 POS 分类，跳过（不分配给任何打印机）
                continue

            # 检查是否有任何分类（包括父分类）与打印机分类匹配
            for categ in product_categs:
                categ_and_parents = get_parent_categ_ids(categ)
                if categ_and_parents & printer_categ_ids:
                    # 找到匹配，添加到结果中
                    matched_lines |= line
                    break

        return matched_lines

    def _send_print_notification(self, pos_order):
        """
        通过 ylhc_print_manager 发送打印任务到厨房打印机

        复制 POS 的打印逻辑：按产品分类分配到不同打印机

        打印流程:
        1. 查找 POS 配置关联的厨房打印机（pos.printer）
        2. 按打印机的 product_categories_ids 过滤订单行
        3. 为每个打印机生成对应的打印任务（只包含该打印机负责的产品）
        4. 使用与 POS OrderChangeReceipt 相同的数据格式
        """
        self.ensure_one()
        try:
            pos_config = pos_order.config_id
            if not pos_config:
                _logger.warning(f"No POS config for order {pos_order.name}")
                return

            # 查找 POS 配置的厨房打印机
            printers_sent = 0
            for printer in pos_config.printer_ids:
                # 获取该打印机的产品分类
                printer_categ_ids = set(printer.product_categories_ids.ids) if printer.product_categories_ids else set()

                # 按分类过滤订单行
                filtered_lines = self._filter_lines_by_categories(printer_categ_ids)

                if not filtered_lines:
                    _logger.debug(f"No matching lines for printer {printer.name} (categories: {printer_categ_ids})")
                    continue

                # 检查是否是云打印机且有关联的 YLHC 打印机
                ylhc_printer = None
                if hasattr(printer, 'ylhc_printer_id') and printer.ylhc_printer_id:
                    ylhc_printer = printer.ylhc_printer_id
                elif hasattr(printer, 'printer_type') and printer.printer_type == 'cloud_printer':
                    # 尝试通过名称匹配 ylhc.printer
                    ylhc_printer = self.env['ylhc.printer'].sudo().search([
                        ('name', '=', printer.name),
                        ('active', '=', True),
                    ], limit=1)

                if ylhc_printer:
                    # 使用过滤后的行创建打印任务
                    self._create_kitchen_print_job(ylhc_printer, pos_order, is_batch=False, qr_lines=filtered_lines)
                    printers_sent += 1
                    _logger.info(f"Created print job for QR order {self.name} on printer {ylhc_printer.name} with {len(filtered_lines)} lines")

            if printers_sent == 0:
                # 没有找到 YLHC 打印机，回退到旧方式（通知 POS 前端）
                self._send_print_notification_to_pos(pos_order)
            else:
                _logger.info(f"Sent print jobs to {printers_sent} printer(s) for QR order {self.name}")

        except Exception as e:
            _logger.error(f"Failed to send print notification for order {self.name}: {e}")
            # 出错时回退到旧方式
            try:
                self._send_print_notification_legacy(pos_order)
            except Exception as e2:
                _logger.error(f"Legacy print notification also failed: {e2}")

    def _send_print_notification_legacy(self, pos_order):
        """
        回退方式：发送打印通知到 POS 前端
        当没有配置 YLHC 打印机时使用此方式
        """
        pos_config = pos_order.config_id
        access_token = pos_config.access_token
        if not access_token:
            _logger.warning(f"POS config {pos_config.name} has no access_token, cannot send print notification")
            return

        # 准备打印数据
        lines_data = []
        for line in self.line_ids:
            product = line.product_id
            categ = product.pos_categ_ids[:1] if product.pos_categ_ids else None
            lines_data.append({
                'product_id': product.id,
                'product_name': product.name,
                'qty': line.qty,
                'note': line.note or '',
                'categ_id': categ.id if categ else False,
                'categ_sequence': categ.sequence if categ else 0,
            })

        notification_data = {
            'order_id': pos_order.id,
            'order_name': pos_order.name,
            'config_id': pos_config.id,
            'table_id': pos_order.table_id.id if pos_order.table_id else False,
            'table_name': pos_order.table_id.table_number if pos_order.table_id else '',
            'qr_order_name': self.name,
            'lines': lines_data,
        }

        pos_config._notify('QR_ORDER_PRINT', notification_data)
        _logger.info(f"Sent legacy print notification to POS frontend for QR order {self.name}")

    def _create_kitchen_print_job(self, ylhc_printer, pos_order, is_batch=False, qr_lines=None):
        """
        创建厨房打印任务

        Args:
            ylhc_printer: ylhc.printer 记录
            pos_order: pos.order 记录
            is_batch: 是否为加菜批次打印
            qr_lines: 加菜时指定的订单行（为 None 时打印所有行）
        """
        try:
            table_name = self.table_id.name if self.table_id else ''
            lines_to_print = qr_lines if qr_lines else self.line_ids

            # 生成 ESC/POS 命令
            escpos_commands = self._generate_escpos_commands(pos_order, lines_to_print, is_batch)
            escpos_base64 = base64.b64encode(escpos_commands).decode('utf-8')

            # 生成小票元数据
            receipt_data = self._generate_receipt_data(pos_order, lines_to_print, is_batch)
            # 添加 ESC/POS 命令到元数据
            receipt_data['escpos_commands'] = escpos_base64

            # 创建打印任务
            # 使用 pos_receipt_print 类型，因为 YLHC Service 只处理这种类型
            job_vals = {
                'name': f'QR厨房单 - {table_name} - {self.name}' if not is_batch else f'QR加菜单 - {table_name} - {self.name}',
                'printer_id': ylhc_printer.id,
                'type': 'pos_receipt_print',  # 使用 POS 打印类型，YLHC Service 可以识别
                'is_test': False,
                'copies': 1,
                'priority': 10,  # 高优先级
                'metadata': json.dumps(receipt_data, ensure_ascii=False),
            }

            job = self.env['ylhc.print.job'].sudo().create(job_vals)
            job.action_process()

            _logger.info(f"Created kitchen print job {job.job_id} for QR order {self.name} on printer {ylhc_printer.name}")
            return job

        except Exception as e:
            _logger.error(f"Failed to create kitchen print job: {e}")
            return None

    def _generate_escpos_commands(self, pos_order, lines, is_batch=False):
        """
        生成 ESC/POS 打印命令 - 统一 KDS 模板格式

        模板格式与 POS KDS (OrderChangePrint.vue) 保持一致:
        - 订单变更名称 (Order-XXX)
        - 订单号 (UID)
        - 桌号 + 时间 (同一行)
        - 客户信息 (如有)
        - 配送地址 (如有，且为配送订单)
        - CANCELED 分组 (取消的商品)
        - ORDERED 分组 (新增的商品)
        - 每个商品: 数量 + 名称，备注单独一行

        Returns:
            bytes: ESC/POS 命令字节序列
        """
        from datetime import timezone, timedelta as td

        # ESC/POS 命令常量
        ESC = b'\x1b'
        GS = b'\x1d'

        # 初始化命令
        INIT = ESC + b'@'                    # ESC @ - 初始化打印机
        CN_MODE = ESC + b'R\x0f'             # 选择字符集（中文）
        ALIGN_CENTER = ESC + b'a\x01'        # 居中对齐
        ALIGN_LEFT = ESC + b'a\x00'          # 左对齐
        BOLD_ON = ESC + b'E\x01'             # 粗体开
        BOLD_OFF = ESC + b'E\x00'            # 粗体关
        DOUBLE_HEIGHT = GS + b'!\x10'        # 双倍高度
        DOUBLE_WIDTH = GS + b'!\x20'         # 双倍宽度
        DOUBLE_SIZE = GS + b'!\x30'          # 双倍尺寸（宽+高）
        NORMAL_SIZE = GS + b'!\x00'          # 正常尺寸
        FEED_LINES = ESC + b'd\x03'          # 走纸 3 行
        PARTIAL_CUT = GS + b'V\x01'          # 半切

        # 构建打印内容
        commands = bytearray()
        commands.extend(INIT)
        commands.extend(CN_MODE)

        # 注意：不添加额外的页边距，打印机初始化后直接开始打印

        # === 标题：订单变更名称（缩小字体）===
        commands.extend(ALIGN_CENTER)
        commands.extend(NORMAL_SIZE)  # 使用正常尺寸，不要双倍
        commands.extend(BOLD_ON)
        # 计算变更序号（类似 KDS 的 change.name）
        change_seq = self._get_change_sequence(pos_order)
        change_name = f'Order-{change_seq:03d}'
        commands.extend(change_name.encode('gbk', errors='replace'))
        commands.extend(b'\n')

        # === 订单号 (UID) ===
        order_uid = pos_order.pos_reference or pos_order.name or self.name
        commands.extend(order_uid.encode('gbk', errors='replace'))
        commands.extend(b'\n')
        commands.extend(BOLD_OFF)

        # === 桌号 + 时间 (同一行，两端对齐，桌号放大) ===
        commands.extend(ALIGN_LEFT)
        commands.extend(DOUBLE_SIZE)  # 桌号使用双倍尺寸
        commands.extend(BOLD_ON)
        table_name = self.table_id.name if self.table_id else ''
        # 时间转换为日本时间 (JST = UTC+9)
        jst = timezone(td(hours=9))
        order_time = datetime.now(jst).strftime('%H:%M')
        # 16字符宽度（双倍宽度下有效宽度减半）
        table_time_line = self._format_two_columns(table_name, order_time, 16)
        commands.extend(table_time_line.encode('gbk', errors='replace'))
        commands.extend(b'\n')
        commands.extend(NORMAL_SIZE)
        commands.extend(BOLD_OFF)

        # === 客户信息 (如有) ===
        partner = pos_order.partner_id if pos_order.partner_id else None
        if partner:
            commands.extend(b'\n')
            commands.extend(ALIGN_CENTER)
            commands.extend(BOLD_ON)
            commands.extend('CUSTOMER DETAILS'.encode('gbk', errors='replace'))
            commands.extend(b'\n')
            commands.extend(BOLD_OFF)
            commands.extend(ALIGN_LEFT)

            if partner.name:
                commands.extend(f'{partner.name}\n'.encode('gbk', errors='replace'))
            if partner.phone:
                commands.extend(f'{partner.phone}\n'.encode('gbk', errors='replace'))
            if partner.email:
                commands.extend(f'{partner.email}\n'.encode('gbk', errors='replace'))

        # === 配送地址 (如有，且为配送订单) ===
        service_type = getattr(pos_order, 'ab_service_type', None)
        if partner and service_type == 'delivery':
            has_address = partner.street or partner.city or partner.zip
            if has_address:
                commands.extend(b'\n')
                commands.extend(ALIGN_CENTER)
                commands.extend(BOLD_ON)
                commands.extend('DELIVERY ADDRESS'.encode('gbk', errors='replace'))
                commands.extend(b'\n')
                commands.extend(BOLD_OFF)
                commands.extend(ALIGN_LEFT)

                if partner.street:
                    commands.extend(f'{partner.street}\n'.encode('gbk', errors='replace'))
                if partner.city:
                    commands.extend(f'{partner.city}\n'.encode('gbk', errors='replace'))
                if partner.zip:
                    commands.extend(f'{partner.zip}\n'.encode('gbk', errors='replace'))

        # === 分组：CANCELED 和 ORDERED ===
        # 对于 QR 订单，通常只有 ORDERED（新增商品）
        # 但保留 CANCELED 分组以支持未来的取消功能
        canceled_lines = [l for l in lines if l.qty <= 0 or l.state == 'cancelled']
        ordered_lines = [l for l in lines if l.qty > 0 and l.state != 'cancelled']

        # CANCELED 分组
        if canceled_lines:
            commands.extend(b'\n')
            commands.extend(ALIGN_CENTER)
            commands.extend(BOLD_ON)
            commands.extend('CANCELED'.encode('gbk', errors='replace'))
            commands.extend(b'\n')
            commands.extend(BOLD_OFF)
            commands.extend(ALIGN_LEFT)

            for line in canceled_lines:
                self._append_order_line(commands, line, is_canceled=True)

        # ORDERED 分组
        if ordered_lines:
            commands.extend(b'\n')
            commands.extend(ALIGN_CENTER)
            commands.extend(BOLD_ON)
            commands.extend('ORDERED'.encode('gbk', errors='replace'))
            commands.extend(b'\n')
            commands.extend(BOLD_OFF)
            commands.extend(ALIGN_LEFT)

            for line in ordered_lines:
                self._append_order_line(commands, line, is_canceled=False)

        # 走纸和切纸
        commands.extend(FEED_LINES)
        commands.extend(PARTIAL_CUT)

        return bytes(commands)

    def _get_change_sequence(self, pos_order):
        """获取订单变更序号"""
        if 'ab_pos.order.change' in self.env:
            changes = self.env['ab_pos.order.change'].sudo().search([
                ('order_id', '=', pos_order.id)
            ])
            return len(changes) + 1
        return 1

    def _format_two_columns(self, left, right, width=32):
        """格式化两列文本（左对齐 + 右对齐）"""
        left = str(left) if left else ''
        right = str(right) if right else ''
        # 计算中文字符宽度（每个中文字符占2个位置）
        left_width = sum(2 if ord(c) > 127 else 1 for c in left)
        right_width = sum(2 if ord(c) > 127 else 1 for c in right)
        spaces = max(1, width - left_width - right_width)
        return left + ' ' * spaces + right

    def _append_order_line(self, commands, line, is_canceled=False):
        """添加订单行到打印命令"""
        # ESC/POS 命令
        GS = b'\x1d'
        DOUBLE_HEIGHT = GS + b'!\x10'        # 双倍高度
        NORMAL_SIZE = GS + b'!\x00'          # 正常尺寸

        product = line.product_id
        product_name = product.name or ''
        qty = abs(int(line.qty) if line.qty == int(line.qty) else line.qty)

        # 格式: 数量 + 商品名称（放大显示）
        commands.extend(DOUBLE_HEIGHT)  # 商品名称使用双倍高度
        line_text = f'{qty}   {product_name}\n'
        commands.extend(line_text.encode('gbk', errors='replace'))
        commands.extend(NORMAL_SIZE)  # 恢复正常尺寸

        # 商品属性 (TYPE) - 如果有
        if hasattr(product, 'attribute_line_ids') and product.attribute_line_ids:
            attr_names = []
            for attr_line in product.attribute_line_ids:
                if attr_line.value_ids:
                    attr_names.extend([v.name for v in attr_line.value_ids])
            if attr_names:
                commands.extend(f'TYPE: {", ".join(attr_names)}\n'.encode('gbk', errors='replace'))

        # 备注 (NOTE) - 单独一行
        if line.note:
            commands.extend(f'NOTE: {line.note}\n'.encode('gbk', errors='replace'))

    def _generate_receipt_data(self, pos_order, lines, is_batch=False):
        """
        生成小票数据（结构化 JSON）- 统一 KDS 模板格式

        数据结构与 POS KDS (OrderChangePrint.vue) 保持一致
        打印代理（YLHC Service）会根据此数据生成实际的 ESC/POS 命令
        """
        table_name = self.table_id.name if self.table_id else ''

        # 获取变更序号
        change_seq = self._get_change_sequence(pos_order)
        change_name = f'Order-{change_seq:03d}'

        # 订单 UID
        order_uid = pos_order.pos_reference or pos_order.name or self.name

        # 客户信息
        partner = pos_order.partner_id if pos_order.partner_id else None
        customer_info = None
        if partner:
            customer_info = {
                'name': partner.name or '',
                'phone': partner.phone or '',
                'email': partner.email or '',
                'comment': partner.comment or '',
            }

        # 配送地址
        service_type = getattr(pos_order, 'ab_service_type', None)
        delivery_address = None
        if partner and service_type == 'delivery':
            if partner.street or partner.city or partner.zip:
                delivery_address = {
                    'street': partner.street or '',
                    'city': partner.city or '',
                    'zip': partner.zip or '',
                }

        # 构建订单行信息 - 分组为 CANCELED 和 ORDERED
        canceled_lines = []
        ordered_lines = []

        for line in lines:
            product = line.product_id
            categ = product.pos_categ_ids[:1] if product.pos_categ_ids else None

            # 获取产品属性值
            attr_values = []
            if hasattr(product, 'attribute_line_ids') and product.attribute_line_ids:
                for attr_line in product.attribute_line_ids:
                    if attr_line.value_ids:
                        attr_values.extend([v.name for v in attr_line.value_ids])

            line_info = {
                'product_id': product.id,
                'product_name': product.name,
                'display_name': product.display_name or product.name,
                'qty': abs(line.qty),
                'note': line.note or '',
                'state': line.state,
                'attribute_values': attr_values,
                'categ_id': categ.id if categ else False,
                'categ_name': categ.name if categ else '',
            }

            if line.qty <= 0 or line.state == 'cancelled':
                canceled_lines.append(line_info)
            else:
                ordered_lines.append(line_info)

        return {
            'source': 'qr_ordering',
            'print_type': 'kitchen_ticket',
            'template_version': 'kds_unified',  # 标记使用统一 KDS 模板

            # 订单变更信息（与 KDS 一致）
            'change_name': change_name,
            'change_sequence': change_seq,

            # 订单信息
            'order_uid': order_uid,
            'qr_order_id': self.id,
            'qr_order_name': self.name,
            'pos_order_id': pos_order.id,
            'pos_order_name': pos_order.name,

            # 餐桌信息
            'table_id': self.table_id.id if self.table_id else False,
            'table_name': table_name,

            # 时间信息
            'order_time': fields.Datetime.now().strftime('%H:%M'),
            'order_datetime': fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S'),

            # 客户信息（与 KDS 一致）
            'customer': customer_info,
            'service_type': service_type,
            'delivery_address': delivery_address,

            # 商品行 - 分组（与 KDS 一致）
            'canceled_lines': canceled_lines,
            'ordered_lines': ordered_lines,

            # 兼容旧格式
            'lines': ordered_lines + canceled_lines,
            'line_count': len(ordered_lines) + len(canceled_lines),
            'total_qty': sum(l['qty'] for l in ordered_lines),

            # 备注
            'note': self.note or '',

            # 小票格式配置
            'receipt_config': {
                'show_price': False,  # 厨房单不显示价格
                'show_total': False,
                'paper_width': '80mm',
                'auto_cut': True,
            }
        }

    def _send_print_notification_for_batch(self, pos_order, qr_lines):
        """
        发送加菜打印任务到厨房打印机

        复制 POS 的打印逻辑：按产品分类分配到不同打印机

        通过 ylhc_print_manager 发送，与 _send_print_notification 类似
        但标记为 is_batch=True，小票标题显示"加菜单"
        """
        self.ensure_one()
        try:
            pos_config = pos_order.config_id
            if not pos_config:
                _logger.warning(f"No POS config for order {pos_order.name}")
                return

            # 查找 POS 配置的厨房打印机
            printers_sent = 0
            for printer in pos_config.printer_ids:
                # 获取该打印机的产品分类
                printer_categ_ids = set(printer.product_categories_ids.ids) if printer.product_categories_ids else set()

                # 按分类过滤订单行（只过滤传入的 qr_lines）
                filtered_lines = self._filter_lines_by_categories(printer_categ_ids, lines=qr_lines)

                if not filtered_lines:
                    _logger.debug(f"No matching lines for printer {printer.name} (categories: {printer_categ_ids})")
                    continue

                # 检查是否是云打印机且有关联的 YLHC 打印机
                ylhc_printer = None
                if hasattr(printer, 'ylhc_printer_id') and printer.ylhc_printer_id:
                    ylhc_printer = printer.ylhc_printer_id
                elif hasattr(printer, 'printer_type') and printer.printer_type == 'cloud_printer':
                    ylhc_printer = self.env['ylhc.printer'].sudo().search([
                        ('name', '=', printer.name),
                        ('active', '=', True),
                    ], limit=1)

                if ylhc_printer:
                    # 使用过滤后的行创建打印任务
                    self._create_kitchen_print_job(ylhc_printer, pos_order, is_batch=True, qr_lines=filtered_lines)
                    printers_sent += 1
                    _logger.info(f"Created batch print job for QR order {self.name} on printer {ylhc_printer.name} with {len(filtered_lines)} lines")

            if printers_sent == 0:
                # 回退到旧方式
                self._send_print_notification_for_batch_legacy(pos_order, qr_lines)
            else:
                _logger.info(f"Sent batch print jobs to {printers_sent} printer(s) for QR order {self.name}")

        except Exception as e:
            _logger.error(f"Failed to send batch print notification: {e}")
            try:
                self._send_print_notification_for_batch_legacy(pos_order, qr_lines)
            except Exception as e2:
                _logger.error(f"Legacy batch print notification also failed: {e2}")

    def _send_print_notification_for_batch_legacy(self, pos_order, qr_lines):
        """
        回退方式：发送加菜打印通知到 POS 前端
        """
        pos_config = pos_order.config_id
        access_token = pos_config.access_token
        if not access_token:
            _logger.warning(f"POS config {pos_config.name} has no access_token")
            return

        lines_data = []
        for line in qr_lines:
            product = line.product_id
            categ = product.pos_categ_ids[:1] if product.pos_categ_ids else None
            lines_data.append({
                'product_id': product.id,
                'product_name': product.name,
                'qty': line.qty,
                'note': line.note or '',
                'categ_id': categ.id if categ else False,
                'categ_sequence': categ.sequence if categ else 0,
            })

        notification_data = {
            'order_id': pos_order.id,
            'order_name': pos_order.name,
            'config_id': pos_config.id,
            'table_id': pos_order.table_id.id if pos_order.table_id else False,
            'table_name': pos_order.table_id.table_number if pos_order.table_id else '',
            'qr_order_name': self.name,
            'is_batch': True,
            'lines': lines_data,
        }

        pos_config._notify('QR_ORDER_PRINT', notification_data)
        _logger.info(f"Sent legacy batch print notification for QR order {self.name}")

    def _send_notification(self, event_type):
        """发送实时通知"""
        self.ensure_one()
        # 通过 Odoo Bus 发送通知
        channel = f'qr_order_{self.session_id.access_token}'
        self.env['bus.bus']._sendone(channel, 'qr_order_update', {
            'event': event_type,
            'order_id': self.id,
            'order_name': self.name,
            'state': self.state,
            'total_amount': self.total_amount,
        })


class QrOrderLine(models.Model):
    """扫码订单行"""
    _name = 'qr.order.line'
    _description = 'QR Order Line / 订单行'
    _order = 'batch_number, sequence, id'

    order_id = fields.Many2one(
        'qr.order',
        string='Order / 订单',
        required=True,
        ondelete='cascade'
    )
    sequence = fields.Integer(
        string='Sequence / 排序',
        default=10
    )
    
    # 产品信息
    product_id = fields.Many2one(
        'product.product',
        string='Product / 菜品',
        required=True,
        domain=[('available_in_pos', '=', True)]
    )
    product_name = fields.Char(
        string='Product Name / 菜品名称',
        related='product_id.name',
        readonly=True
    )
    
    # 数量和价格
    qty = fields.Float(
        string='Quantity / 数量',
        default=1,
        required=True
    )
    price_unit = fields.Float(
        string='Unit Price / 单价',
        compute='_compute_price',
        store=True
    )
    subtotal = fields.Float(
        string='Subtotal / 小计',
        compute='_compute_price',
        store=True
    )
    
    # 批次（用于区分首次下单和加菜）
    batch_number = fields.Integer(
        string='Batch / 批次',
        default=1,
        help='批次号：1=首次下单，2+=加菜'
    )
    
    # 备注
    note = fields.Char(
        string='Note / 备注',
        help='特殊要求：少辣、不要香菜等'
    )
    
    # 状态
    state = fields.Selection([
        ('pending', 'Pending / 待提交'),
        ('submitted', 'Submitted / 已提交'),
        ('cooking', 'Cooking / 制作中'),
        ('served', 'Served / 已上菜'),
        ('cancelled', 'Cancelled / 已取消'),
    ], string='Status / 状态', default='pending')

    @api.depends('product_id', 'qty')
    def _compute_price(self):
        """计算价格"""
        for line in self:
            if line.product_id:
                line.price_unit = line.product_id.lst_price
                line.subtotal = line.price_unit * line.qty
            else:
                line.price_unit = 0
                line.subtotal = 0

