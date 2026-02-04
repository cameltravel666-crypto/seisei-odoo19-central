# -*- coding: utf-8 -*-

import hashlib
import secrets
import base64
from io import BytesIO
from datetime import datetime, timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False
    _logger.warning("qrcode library not installed. QR code image generation disabled.")


class QrTable(models.Model):
    """二维码餐桌模型 - 每个餐桌对应一个二维码"""
    _name = 'qr.table'
    _description = 'QR Code Table / 二维码餐桌'
    _order = 'sequence, name'

    name = fields.Char(
        string='Table Name / 餐桌名称',
        required=True,
        help='餐桌的显示名称，如 A1, A2, 包厢1 等'
    )
    sequence = fields.Integer(
        string='Sequence / 排序',
        default=10
    )
    
    # 关联 POS 餐厅餐桌（如果使用 pos_restaurant）
    pos_table_id = fields.Many2one(
        'restaurant.table',
        string='POS Table / POS餐桌',
        ondelete='set null',
        help='关联的 POS 餐厅餐桌'
    )
    
    # 关联 POS 配置
    pos_config_id = fields.Many2one(
        'pos.config',
        string='POS Config / POS配置',
        required=True,
        help='订单将同步到此 POS 配置'
    )
    
    # 二维码相关
    qr_token = fields.Char(
        string='QR Token',
        readonly=True,
        copy=False,
        help='二维码中的唯一标识'
    )
    qr_url = fields.Char(
        string='QR URL / 点餐链接',
        compute='_compute_qr_url',
        store=False,
        help='扫码后打开的点餐链接 (V1 原版)'
    )
    qr_url_v2 = fields.Char(
        string='QR URL V2 / 点餐链接V2',
        compute='_compute_qr_url',
        store=False,
        help='扫码后打开的点餐链接 (V2 移动端优化版)'
    )
    qr_code_image = fields.Binary(
        string='QR Code / 二维码图片',
        compute='_compute_qr_code_image',
        store=False,
        help='二维码图片（自动生成）'
    )
    
    # 状态
    active = fields.Boolean(
        string='Active / 启用',
        default=True
    )
    state = fields.Selection([
        ('available', 'Available / 空闲'),
        ('occupied', 'Occupied / 使用中'),
        ('reserved', 'Reserved / 已预订'),
    ], string='Status / 状态', default='available')
    
    # 当前会话
    current_session_id = fields.Many2one(
        'qr.session',
        string='Current Session / 当前会话',
        readonly=True,
        help='当前正在使用的点餐会话'
    )
    
    # 统计
    order_count = fields.Integer(
        string='Order Count / 订单数',
        compute='_compute_order_count'
    )

    _sql_constraints = [
        ('qr_token_unique', 'unique(qr_token)', 'QR Token must be unique!'),
        ('name_pos_config_unique', 'unique(name, pos_config_id)', 'Table name must be unique per POS config!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """创建时自动生成 QR Token（仅一次，永久不变）"""
        for vals in vals_list:
            if not vals.get('qr_token'):
                vals['qr_token'] = self._generate_qr_token()
        return super().create(vals_list)

    def write(self, vals):
        """
        拦截 write，保护 qr_token 不被意外修改。
        只有 context 带 allow_regenerate_qr_token=True 时才允许修改 token。
        这样可以防止复制、导入、批量更新等操作意外改变 token。
        """
        if 'qr_token' in vals and not self.env.context.get('allow_regenerate_qr_token'):
            # 静默移除 qr_token，不抛异常（避免批量导入失败）
            _logger.warning(
                f"Attempt to modify qr_token blocked for tables {self.ids}. "
                "Use action_regenerate_token() or set context allow_regenerate_qr_token=True"
            )
            vals = {k: v for k, v in vals.items() if k != 'qr_token'}
        return super().write(vals)

    def copy(self, default=None):
        """复制餐桌时，强制生成新的 qr_token"""
        default = dict(default or {})
        default['qr_token'] = self._generate_qr_token()
        return super().copy(default)

    def _generate_qr_token(self):
        """生成唯一的 QR Token"""
        return secrets.token_urlsafe(16)

    def action_regenerate_token(self):
        """重新生成 QR Token（使旧二维码失效）- 唯一合法的修改入口"""
        for record in self:
            # 使用 context 允许修改 token
            record.with_context(allow_regenerate_qr_token=True).write({
                'qr_token': self._generate_qr_token()
            })
            _logger.info(f"QR token regenerated for table {record.name} (id={record.id})")
            # 关闭当前会话
            if record.current_session_id:
                record.current_session_id.action_close()
        return True

    @api.depends('qr_token')
    def _compute_qr_url(self):
        """计算点餐链接 (V1 和 V2)"""
        # 使用固定的公开域名，而非系统配置的 web.base.url
        # web.base.url (ylhc-testodoo.seisei.tokyo) 用于打印代理连接
        # 扫码点餐链接统一使用 demo.nagashiro.top
        qr_base_url = self.env['ir.config_parameter'].sudo().get_param(
            'qr_ordering.base_url',
            default='https://demo.nagashiro.top'
        )
        for record in self:
            if record.qr_token:
                record.qr_url = f"{qr_base_url}/qr/order/{record.qr_token}"
                record.qr_url_v2 = f"{qr_base_url}/qr/order/{record.qr_token}?menu_ui_v2=1"
            else:
                record.qr_url = False
                record.qr_url_v2 = False

    @api.depends('qr_url')
    def _compute_qr_code_image(self):
        """生成二维码图片"""
        for record in self:
            if not record.qr_url or not QRCODE_AVAILABLE:
                record.qr_code_image = False
                continue
            try:
                # 生成二维码
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(record.qr_url)
                qr.make(fit=True)

                # 创建图片
                img = qr.make_image(fill_color="black", back_color="white")

                # 转换为 base64
                buffer = BytesIO()
                img.save(buffer, format='PNG')
                record.qr_code_image = base64.b64encode(buffer.getvalue())
            except Exception as e:
                _logger.error(f"Failed to generate QR code for table {record.name}: {e}")
                record.qr_code_image = False

    def _compute_order_count(self):
        """计算订单数量"""
        for record in self:
            record.order_count = self.env['qr.order'].search_count([
                ('table_id', '=', record.id)
            ])

    def action_view_orders(self):
        """查看该餐桌的所有订单"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Orders - {self.name}',
            'res_model': 'qr.order',
            'view_mode': 'tree,form',
            'domain': [('table_id', '=', self.id)],
            'context': {'default_table_id': self.id},
        }

    def action_open_table(self):
        """开台 - 创建新的点餐会话"""
        self.ensure_one()
        if self.state == 'occupied' and self.current_session_id:
            raise UserError('餐桌正在使用中，请先结账或关闭当前会话')
        
        session = self.env['qr.session'].create({
            'table_id': self.id,
        })
        self.write({
            'state': 'occupied',
            'current_session_id': session.id,
        })
        return session

    def action_close_table(self):
        """结账/关台 - 关闭当前会话"""
        self.ensure_one()
        if self.current_session_id:
            self.current_session_id.action_close()
        self.write({
            'state': 'available',
            'current_session_id': False,
        })
        return True

    def action_print_qr_code(self):
        """打印二维码"""
        self.ensure_one()
        # TODO: 实现二维码打印功能
        return {
            'type': 'ir.actions.act_url',
            'url': f'/qr/print/{self.qr_token}',
            'target': 'new',
        }



