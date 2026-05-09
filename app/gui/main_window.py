from __future__ import annotations

import sys
import time
from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from app.core.account_service import AccountService
from app.core.async_runner import TaskRunner
from app.core.binance_client import BinanceClient, normalize_binance_error
from app.core.config import load_config, save_config
from app.core.execution_metrics import (
    QueueQualityEstimator,
    SpreadStabilityAnalyzer,
    diff_order_transitions,
    fill_probability_label,
    format_latency_ms,
    last_fill_time_label,
)
from app.core.filters import validate_order_from_exchange_info
from app.core.harvest_readiness import HarvestReadinessEngine, HarvestReadinessState
from app.core.formatting import format_age_ms
from app.core.logger import AppLogger
from app.core.market_service import MarketService
from app.core.order_service import OrderService
from app.core.polling_manager import PollingManager
from app.core.runtime_state import RuntimeState
from app.core.ws_manager import WSManager
from app.gui.panels.log_panel import LogPanel
from app.gui.settings_dialog import SettingsDialog
from app.gui.ui_constants import *


DARK_STYLESHEET = """
QWidget { background: #0b0f14; color: #e6edf3; }
QMainWindow { background: #0b0f14; }
QGroupBox { background: #10161d; border: 1px solid #283241; border-radius: 8px; margin-top: 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #e6edf3; }
QLabel { color: #e6edf3; }
QLineEdit, QComboBox, QTextEdit { background: #0d131a; border: 1px solid #283241; border-radius: 4px; padding: 4px; color: #e6edf3; }
QPushButton { background: #202a36; border: 1px solid #283241; border-radius: 4px; padding: 6px 10px; color: #e6edf3; }
QPushButton:hover { background: #2b3746; }
QPushButton:pressed { background: #243447; }
QHeaderView::section { background: #18212b; color: #e6edf3; border: 1px solid #283241; padding: 5px; }
QTableWidget { background: #111821; alternate-background-color: #10161d; gridline-color: #283241; border: 1px solid #283241; }
QTableWidget::item:selected { background: #243447; color: #e6edf3; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('EUT v0.2.8 — Stable Manual Trading Terminal + Real Data Cockpit')
        self.setMinimumSize(1280, 720)
        self.resize(1500, 900)
        self.setStyleSheet(DARK_STYLESHEET)
        self.logger = AppLogger(max_records=500, dedupe_seconds=30)
        self.cfg = load_config()
        self.runtime = RuntimeState()
        self.ws = WSManager(enabled=False)
        self.settings_dialog = None
        self.filters = None
        self._last_market = None
        self._selected_order_id = None
        self._orders_by_id = {}
        self._last_balance_log_ts = 0.0
        self._last_market_log = None
        self._spread_value = None
        self._spread_since = None
        self._latency_warning_ms = 400
        self._order_reaction_ms = None
        self._last_fill_ts = None
        self._prev_open_order_ids = set()
        self._spread_analyzer = SpreadStabilityAnalyzer()
        self._queue_estimator = QueueQualityEstimator()
        self._spread_stability = 'BAD'
        self._queue_quality = 'MEDIUM'
        self._last_market_snapshot = {}
        self._last_open_orders = []
        self._harvest_engine = HarvestReadinessEngine()
        self._harvest_result = None
        self._last_harvest_state = None
        self._status_badges = {}

        self.task_runner = TaskRunner(4, self)
        self.task_runner.signals.success.connect(self._on_task_success)
        self.task_runner.signals.error.connect(self._on_task_error)
        self.task_runner.signals.finished.connect(self.task_runner.finish)

        self._init_services()
        self._build_ui()
        self.polling = PollingManager(self.refresh_market, self.refresh_orders, self.refresh_balances, 1000, 4000, 7000, self)
        self._set_private_polling(False)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_timer.start(250)
        QTimer.singleShot(50, self._startup_connect_flow)

    def _startup_connect_flow(self):
        self.refresh_market(force=True)
        self.start_polling()
        has_keys = bool(self.cfg.get('api_key') and self.cfg.get('api_secret'))
        if not has_keys:
            self.logger.log('AUTH', 'API ключи не заданы, приватный контур приостановлен')
            return
        self.task_runner.run_task('auth', self.client.get_account)

    def _init_services(self):
        self.client = BinanceClient(self.cfg['api_key'], self.cfg['api_secret'], self.cfg['testnet'], self.cfg.get('request_timeout_sec', 3))
        self.market = MarketService(self.client, self.cfg['symbol'])
        self.account = AccountService(self.client)
        self.orders = OrderService(self.client, self.cfg['symbol'])

    def _btn(self, text, fn):
        b = QPushButton(text)
        b.setMinimumHeight(BUTTON_H)
        b.setMinimumWidth(BUTTON_MIN_W)
        b.clicked.connect(fn)
        return b

    def _value(self, text='-'):
        lbl = QLabel(text)
        lbl.setMinimumWidth(VALUE_LABEL_MIN_W)
        return lbl

    def _build_ui(self):
        self.setFont(QFont('', APP_FONT_PT))
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(8)

        self.s, self.m, self.b = {}, {}, {}

        top = QGroupBox('Status Strip')
        top.setMinimumHeight(64)
        top.setMaximumHeight(86)
        top_l = QHBoxLayout(top)
        top_l.setSpacing(8)
        for label, key in [('REST', 'Публичный REST'), ('ACCOUNT', 'Аккаунт'), ('PRIVATE', 'Приватный канал'), ('TRADING', 'Торговля'), ('LATENCY', 'Задержка'), ('HARVEST', 'HARVEST')]:
            badge = QLabel(f'{label} ● -')
            badge.setStyleSheet('padding: 3px 8px; border: 1px solid #283241; border-radius: 10px; color: #8b949e;')
            self._status_badges[key] = badge
            self.s[key] = badge
            top_l.addWidget(badge)
        self.settings_btn = self._btn('Настройки', self.open_settings)
        self.diag_btn = self._btn('Проверить систему', self.run_diagnostics)
        top_l.addStretch(1)
        top_l.addWidget(self.settings_btn)
        top_l.addWidget(self.diag_btn)
        main.addWidget(top)

        center_splitter = QSplitter(Qt.Horizontal)

        left_col = QWidget()
        left_l = QVBoxLayout(left_col)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_inner = QWidget()
        left_inner_l = QVBoxLayout(left_inner)

        market_box = QGroupBox('Market Summary')
        market_f = QFormLayout(market_box)
        for key in ['Последняя', 'Bid', 'Ask', 'Спред', 'Тики', 'Lifetime', 'Stable', 'Latency', 'Возраст REST']:
            self.m[key] = self._value('0.00000000' if key != 'Возраст REST' else '-')
            market_f.addRow(QLabel(key), self.m[key])
        market_btns = QHBoxLayout()
        market_btns.addWidget(self._btn('Обновить', self.refresh_market))
        market_btns.addWidget(self._btn('Старт опроса', self.start_polling))
        market_btns.addWidget(self._btn('Стоп опроса', self.stop_polling))
        market_f.addRow(market_btns)

        balances_box = QGroupBox('Balances Summary')
        bal_f = QFormLayout(balances_box)
        bal_keys = ['USDT свободно', 'USDT заблокировано', 'EURI свободно', 'EURI заблокировано', 'USDT total', 'EURI total', 'Оценка всего USDT']
        for key in bal_keys:
            self.b[key] = self._value('0.00000000')
            bal_f.addRow(QLabel(key), self.b[key])
        self.balance_refresh_btn = self._btn('Обновить балансы', self.refresh_balances)
        bal_f.addRow(self.balance_refresh_btn)

        settings_box = QGroupBox('Trade Settings — coming next')
        settings_f = QFormLayout(settings_box)
        settings_f.addRow('Mode', QLabel('Manual'))
        settings_f.addRow('Max order USDT', QLabel('-'))
        settings_f.addRow('Min spread ticks', QLabel('-'))
        settings_f.addRow('Risk guard', QLabel('OFF'))

        left_inner_l.addWidget(market_box)
        left_inner_l.addWidget(balances_box)
        left_inner_l.addWidget(settings_box)
        left_inner_l.addStretch(1)
        left_scroll.setWidget(left_inner)
        left_l.addWidget(left_scroll)

        center_col = QWidget()
        center_l = QVBoxLayout(center_col)
        orders_box = QGroupBox('Открытые ордера')
        orders_l = QVBoxLayout(orders_box)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['ID', 'Сторона', 'Цена', 'Количество', 'Исполнено', 'Исполнено %', 'Статус', 'Возраст'])
        self.table.itemSelectionChanged.connect(self._on_order_selected)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(TABLE_ROW_H)
        self.table.horizontalHeader().setFixedHeight(TABLE_HEADER_H)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for i, w in OPEN_ORDERS_COL_WIDTHS.items():
            self.table.setColumnWidth(i, w)
        orders_l.addWidget(self.table)
        order_btns = QHBoxLayout()
        self.refresh_orders_btn = self._btn('Обновить', self.refresh_orders)
        self.cancel_btn = self._btn('Отменить выбранный', self.cancel_selected)
        self.cancel_all_btn = self._btn('Отменить все', self.cancel_all)
        order_btns.addWidget(self.refresh_orders_btn)
        order_btns.addWidget(self.cancel_btn)
        order_btns.addWidget(self.cancel_all_btn)
        order_btns.addStretch(1)
        orders_l.addLayout(order_btns)
        center_l.addWidget(orders_box)

        right_col = QWidget()
        right_l = QVBoxLayout(right_col)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_inner = QWidget()
        right_inner_l = QVBoxLayout(right_inner)

        manual_box = QGroupBox('Ручная торговля')
        manual_f = QFormLayout(manual_box)
        self.side = QComboBox(); self.side.addItems(['BUY', 'SELL'])
        self.price = QLineEdit(); self.qty = QLineEdit(); self.total = self._value('0.00000000')
        self.price.textChanged.connect(self._recalc_total)
        self.qty.textChanged.connect(self._recalc_total)
        manual_f.addRow('Сторона', self.side)
        manual_f.addRow('Цена', self.price)
        manual_f.addRow('Количество', self.qty)
        manual_f.addRow('Сумма', self.total)
        quick_price = QHBoxLayout()
        self.price_bid_btn = self._btn('Цена = Bid', self._fill_price_bid)
        self.price_ask_btn = self._btn('Цена = Ask', self._fill_price_ask)
        quick_price.addWidget(self.price_bid_btn); quick_price.addWidget(self.price_ask_btn)
        manual_f.addRow(quick_price)
        quick_qty = QHBoxLayout()
        self.qty_max_btn = self._btn('Qty max EURI', self._fill_qty_max_euri)
        self.qty_10_btn = self._btn('Qty на 10 USDT', self._fill_qty_for_10_usdt)
        quick_qty.addWidget(self.qty_max_btn); quick_qty.addWidget(self.qty_10_btn)
        manual_f.addRow(quick_qty)
        self.buy_btn = self._btn('Купить LIMIT', lambda: self.place('BUY'))
        self.sell_btn = self._btn('Продать LIMIT', lambda: self.place('SELL'))
        trade_btns = QHBoxLayout(); trade_btns.addWidget(self.buy_btn); trade_btns.addWidget(self.sell_btn)
        manual_f.addRow(trade_btns)

        activity_box = QGroupBox('Активность ордера')
        act_f = QFormLayout(activity_box)
        for key in ['Активный ордер', 'Время жизни', 'Очередь', 'Reprice count']:
            self.s[key] = self._value('-')
            act_f.addRow(QLabel(key), self.s[key])

        fsm_box = QGroupBox('Runtime FSM')
        fsm_f = QFormLayout(fsm_box)
        self.s['State'] = self._value('-')
        fsm_f.addRow(QLabel('State'), self.s['State'])
        exec_box = QGroupBox('Execution Metrics')
        exec_f = QFormLayout(exec_box)
        for key in ['Queue quality', 'Spread stability', 'Market latency', 'Order reaction', 'Fill probability', 'Last fill time']:
            self.s[key] = self._value('-')
            exec_f.addRow(QLabel(key), self.s[key])

        harvest_box = QGroupBox('Harvest Readiness')
        harvest_f = QFormLayout(harvest_box)
        for key in ['Harvest state', 'Harvest score', 'Harvest reason', 'Spread OK', 'Stability OK', 'Latency OK', 'Queue OK', 'Entry', 'Exit', 'Suggested']:
            self.s[key] = self._value('-')
            harvest_f.addRow(QLabel(key), self.s[key])

        right_inner_l.addWidget(harvest_box)
        right_inner_l.addWidget(manual_box)
        right_inner_l.addWidget(activity_box)
        right_inner_l.addWidget(fsm_box)
        right_inner_l.addWidget(exec_box)
        right_inner_l.addStretch(1)
        right_scroll.setWidget(right_inner)
        right_l.addWidget(right_scroll)

        center_splitter.addWidget(left_col)
        center_splitter.addWidget(center_col)
        center_splitter.addWidget(right_col)
        center_splitter.setStretchFactor(0, 0)
        center_splitter.setStretchFactor(1, 1)
        center_splitter.setStretchFactor(2, 0)
        center_splitter.setSizes([400, 760, 340])
        left_col.setMinimumWidth(360)
        left_col.setMaximumWidth(420)
        right_col.setMinimumWidth(320)
        right_col.setMaximumWidth(360)
        main.addWidget(center_splitter, 1)

        logs_box = QGroupBox('Логи')
        logs_box.setMinimumHeight(160)
        logs_box.setMaximumHeight(220)
        logs_l = QVBoxLayout(logs_box)
        self.log_panel = LogPanel(500)
        self.logger.subscribe(self.log_panel.append_record)
        self.clear_logs_btn = self._btn('Очистить логи', self.log_panel.clear)
        logs_l.addWidget(self.log_panel)
        logs_l.addWidget(self.clear_logs_btn)
        main.addWidget(logs_box)

    def open_settings(self):
        self.settings_dialog = SettingsDialog(self.cfg, self.apply_settings, self.test_connection, self)
        self.settings_dialog.show()

    def apply_settings(self, values: dict):
        self.cfg.update(values)
        save_config(self.cfg)
        self._init_services()
        self._tick_status()
        self.logger.log('ИНФО', 'Настройки сохранены')

    def test_connection(self, values: dict):
        self.apply_settings(values)
        try:
            self.client.get_account()
            self.runtime.set_account_auth('CONNECTED')
            self._set_private_polling(True)
            self.refresh_balances(); self.refresh_orders(); self._load_filters_if_needed()
            self.logger.log('AUTH', 'Аккаунт Binance подключен')
            return True, 'Подключение успешно'
        except Exception as e:
            self.runtime.set_account_auth('AUTH_ERROR')
            self._set_private_polling(False)
            self.logger.log('ОШИБКА', normalize_binance_error(e))
            return False, normalize_binance_error(e)

    def _load_filters_if_needed(self):
        if self.filters is None:
            self.filters = self.client.get_exchange_info(self.cfg['symbol'])
            price_filter = (self.filters or {}).get('PRICE_FILTER', {})
            tick_size = Decimal(str(price_filter.get('tickSize', 0) or 0))
            self.market.set_tick_size(tick_size if tick_size > 0 else None)

    def _set_private_polling(self, enabled: bool):
        self.polling.set_private_enabled(enabled and self.runtime.account_auth_state == 'CONNECTED')
        self.runtime.private_polling_state = 'RUNNING' if self.polling.private_enabled else 'PAUSED'

    def refresh_market(self, force: bool = False):
        self.task_runner.run_task('market', lambda: self.market.snapshot())

    def refresh_balances(self, force: bool = False):
        if self.runtime.account_auth_state != 'CONNECTED':
            return
        last = Decimal(str(self.m['Последняя'].text() or 0))
        self.task_runner.run_task('balances', lambda: self.account.balances(last))

    def refresh_orders(self, force: bool = False):
        if self.runtime.account_auth_state != 'CONNECTED':
            return
        self.task_runner.run_task('orders', self.orders.open_orders)

    def _on_task_success(self, name, payload):
        if name == 'auth':
            self.runtime.set_account_auth('CONNECTED')
            self._set_private_polling(True)
            self._load_filters_if_needed()
            self.refresh_balances(force=True)
            self.refresh_orders(force=True)
            self.logger.log('AUTH', 'Binance account connected')
        elif name == 'market':
            s = payload
            self.runtime.mark_rest_update()
            self.runtime.last_latency_ms = float(s.get('latency_ms', 0.0) or 0.0)
            self.m['Последняя'].setText(f"{Decimal(str(s.get('last', 0))):.8f}")
            self.m['Bid'].setText(f"{Decimal(str(s.get('bid', 0))):.8f}")
            self.m['Ask'].setText(f"{Decimal(str(s.get('ask', 0))):.8f}")
            spread = Decimal(str(s.get('spread_source', s.get('spread', 0))))
            self._update_spread_panel(spread, s.get('spread_ticks', '-'))
            self.m['Возраст REST'].setText(str(s.get('rest_age', '-')))
            self._last_market_snapshot = dict(s)
            self._update_execution_metrics(best_unchanged=bool(s.get('best_unchanged', False)))
            self._recalc_equity_total()
            self._recompute_harvest_readiness()
        elif name == 'balances':
            bal = payload
            self.b['USDT свободно'].setText(f"{Decimal(str(bal.get('USDT_free', 0))):.8f}")
            self.b['USDT заблокировано'].setText(f"{Decimal(str(bal.get('USDT_locked', 0))):.8f}")
            self.b['EURI свободно'].setText(f"{Decimal(str(bal.get('EURI_free', 0))):.8f}")
            self.b['EURI заблокировано'].setText(f"{Decimal(str(bal.get('EURI_locked', 0))):.8f}")
            usdt_total = Decimal(str(bal.get('USDT_free', 0))) + Decimal(str(bal.get('USDT_locked', 0)))
            euri_total = Decimal(str(bal.get('EURI_free', 0))) + Decimal(str(bal.get('EURI_locked', 0)))
            self.b['USDT total'].setText(f"{usdt_total:.8f}")
            self.b['USDT total'].setToolTip(f"free={self.b['USDT свободно'].text()}\nlocked={self.b['USDT заблокировано'].text()}")
            self.b['EURI total'].setText(f"{euri_total:.8f}")
            self.b['EURI total'].setToolTip(f"free={self.b['EURI свободно'].text()}\nlocked={self.b['EURI заблокировано'].text()}")
            self.b['Оценка всего USDT'].setText(f"{Decimal(str(bal.get('equity_usdt', 0))):.8f}")
            self.runtime.mark_balances_update()
            self._recompute_harvest_readiness()
            now = time.time()
            if (now - self._last_balance_log_ts) >= 10:
                self.logger.log('БАЛАНС', f"USDT={self.b['USDT свободно'].text()} EURI={self.b['EURI свободно'].text()}")
                self._last_balance_log_ts = now
        elif name == 'orders':
            data = payload
            current_ids = {int(o.get('orderId')) for o in data if o.get('orderId') is not None}
            self._handle_order_transitions(current_ids)
            self._orders_by_id = {int(o.get('orderId')): o for o in data if o.get('orderId') is not None}
            self.table.setRowCount(len(data))
            now_ms = int(time.time() * 1000)
            for r, o in enumerate(data):
                executed = Decimal(str(o.get('executedQty', 0) or 0))
                orig = Decimal(str(o.get('origQty', 0) or 0))
                filled = (executed / orig * Decimal('100')) if orig > 0 else Decimal('0')
                age = format_age_ms(max(0, now_ms - int(o.get('time', now_ms))))
                vals = [o.get('orderId'), o.get('side'), f"{Decimal(str(o.get('price', 0) or 0)):.8f}", f"{orig:.8f}", f"{executed:.8f}", f'{filled:.1f}%', o.get('status'), age]
                for c, v in enumerate(vals):
                    self.table.setItem(r, c, QTableWidgetItem(str(v)))
            self.runtime.mark_orders_update()
            self._last_open_orders = list(data)
            self._update_order_activity()
            self._recompute_harvest_readiness()
        elif name == 'place_order':
            side = str(payload.get('side', ''))
            self._order_reaction_ms = float(payload.get('_reaction_ms', 0.0) or 0.0)
            self.logger.log('EXEC', f'Order reaction: {int(self._order_reaction_ms)} ms')
            self.logger.log('ОРДЕР', f'LIMIT {side} отправлен')
            self.refresh_orders(force=True)
            self.refresh_balances(force=True)
        elif name == 'cancel_order':
            reaction = payload[0] if isinstance(payload, tuple) else payload
            if isinstance(reaction, dict):
                self._order_reaction_ms = float(reaction.get('_reaction_ms', 0.0) or 0.0)
                self.logger.log('EXEC', f'Order reaction: {int(self._order_reaction_ms)} ms')
            self.logger.log('ОРДЕР', 'Отмена ордера выполнена')
            self.refresh_orders(force=True)
            self.refresh_balances(force=True)

    def _on_task_error(self, name, err):
        if name == 'auth':
            self.runtime.set_account_auth('AUTH_ERROR')
            self._set_private_polling(False)
        self.logger.log('ОШИБКА', f'{name}: {err}')

    def place(self, side):
        if self.runtime.account_auth_state != 'CONNECTED':
            return self.logger.log('РИСК', 'Торговля недоступна: аккаунт не подключен')
        if self.cfg.get('read_only', True):
            return self.logger.log('РИСК', 'Торговля запрещена: включен режим только чтение')
        if not self.cfg.get('trading_enabled', False):
            return self.logger.log('РИСК', 'Торговля отключена в настройках')
        price = self.price.text().strip(); qty = self.qty.text().strip()
        if not price or not qty:
            return self.logger.log('РИСК', 'Заполните цену и количество')
        self._load_filters_if_needed()
        ok, msg = validate_order_from_exchange_info(price, qty, self.filters)
        if not ok:
            return self.logger.log('ОШИБКА', msg)
        if QMessageBox.question(self, 'Подтверждение ордера', f'Отправить {side} LIMIT {qty} по {price}?') != QMessageBox.Yes:
            return
        self.task_runner.run_task('place_order', lambda: self.orders.place_limit(side, qty, price))

    def cancel_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return QMessageBox.warning(self, 'Внимание', 'Выберите ордер для отмены')
        item = self.table.item(row, 0)
        if not item:
            return QMessageBox.warning(self, 'Внимание', 'orderId не найден')
        oid = int(item.text())
        if QMessageBox.question(self, 'Подтверждение', f'Отменить ордер {oid}?') != QMessageBox.Yes:
            return
        self.task_runner.run_task('cancel_order', lambda: self.orders.cancel(oid))

    def cancel_all(self):
        if QMessageBox.question(self, 'Подтверждение', 'Отменить все открытые ордера?') != QMessageBox.Yes:
            return
        self.task_runner.run_task('cancel_order', self.orders.cancel_all)

    def run_diagnostics(self):
        self.logger.log('ИНФО', 'Public REST: OK')
        self.logger.log('AUTH', f"Account: {self.runtime.account_auth_state}")
        self.logger.log('БАЛАНС', f"USDT={self.b['USDT свободно'].text()} EURI={self.b['EURI свободно'].text()}")
        self.logger.log('ИНФО', f'Open orders: {self.table.rowCount()}')
        self.logger.log('ИНФО', f"Trading: {'ON' if self.cfg.get('trading_enabled', False) else 'OFF'}")
        self.logger.log('ИНФО', f"TaskRunner: in_flight={len(self.task_runner.in_flight)}")
        self.logger.log('ИНФО', 'Диагностика завершена')

    def _tick_status(self):
        self._set_status_badge('Публичный REST', 'OK', 'Public market REST calls are healthy')
        self._set_status_badge('Аккаунт', self.runtime.account_auth_state, 'Binance account auth state')
        self._set_status_badge('Приватный канал', self.runtime.private_polling_state, 'Private polling gate')
        self._set_status_badge('Торговля', 'ON' if self.cfg.get('trading_enabled', False) else 'OFF', 'Global trading switch')
        latency = self.runtime.last_public_latency_ms or '0ms'
        if self.runtime.last_latency_ms > self._latency_warning_ms:
            latency = f'{latency} WARNING'
        self._set_status_badge('Задержка', str(latency), 'Observed market request latency')
        self.m['Latency'].setText(str(latency))
        self._set_harvest_badge()
        self._refresh_order_ages()
        self._update_order_activity()
        self._update_runtime_fsm()
        self._update_trade_buttons()


    def _recompute_harvest_readiness(self):
        balances_ctx = {
            'account_connected': self.runtime.account_auth_state == 'CONNECTED',
            'trading_enabled': self.cfg.get('trading_enabled', False),
            'read_only': self.cfg.get('read_only', True),
            'risk_blocked': False,
            'max_active_orders': 10,
        }
        snapshot = dict(self._last_market_snapshot or {})
        snapshot['spread_lifetime_ms'] = int((time.time() - self._spread_since) * 1000) if self._spread_since else 0
        execution = {
            'latency_ms': self.runtime.last_latency_ms,
            'queue_quality': self._queue_quality,
            'spread_stability': self._spread_stability,
        }
        self._harvest_result = self._harvest_engine.analyze(snapshot, execution, self.filters, balances_ctx, self._last_open_orders)
        self._update_harvest_panel()
        self._log_harvest_state_if_changed()

    def _update_harvest_panel(self):
        if not self._harvest_result:
            return
        r = self._harvest_result
        self.s['Harvest state'].setText(r.state.value)
        self.s['Harvest score'].setText(str(r.score))
        self.s['Harvest reason'].setText(', '.join(r.reasons[:2]) if r.reasons else '-')
        self.s['Spread OK'].setText('YES' if r.spread_ok else 'NO')
        self.s['Stability OK'].setText('YES' if r.stability_ok else 'NO')
        self.s['Latency OK'].setText('YES' if r.latency_ok else 'NO')
        self.s['Queue OK'].setText('YES' if r.queue_ok else 'NO')
        self.s['Entry'].setText('POSSIBLE' if r.entry_possible else 'NO')
        self.s['Exit'].setText('POSSIBLE' if r.exit_possible else 'NO')
        self.s['Suggested'].setText(r.suggested_side)

    def _set_harvest_badge(self):
        state = self._harvest_result.state.value if self._harvest_result else 'NOT_READY'
        self.s['HARVEST'].setText(state)
        color_map = {
            'READY': '#2ea043',
            'WATCH': '#d29922',
            'NOT_READY': '#8b949e',
            'BLOCKED': '#f85149',
        }
        self.s['HARVEST'].setStyleSheet(f"color: {color_map.get(state, '#8b949e')}; font-weight: 700;")
        self._set_status_badge('HARVEST', state, state)

    def _set_status_badge(self, key: str, value: str, details: str = ''):
        badge = self._status_badges.get(key)
        if not badge:
            return
        text_key = next((k for k, v in [('Публичный REST', 'REST'), ('Аккаунт', 'ACCOUNT'), ('Приватный канал', 'PRIVATE'), ('Торговля', 'TRADING'), ('Задержка', 'LATENCY'), ('HARVEST', 'HARVEST')] if k == key), None)
        title = {'Публичный REST': 'REST', 'Аккаунт': 'ACCOUNT', 'Приватный канал': 'PRIVATE', 'Торговля': 'TRADING', 'Задержка': 'LATENCY', 'HARVEST': 'HARVEST'}.get(key, key)
        color = '#8b949e'
        val = str(value).upper()
        if any(x in val for x in ['OK', 'READY', 'ON', 'CONNECTED']):
            color = '#2ea043'
        elif any(x in val for x in ['WARN', 'WATCH', 'RUNNING']):
            color = '#d29922'
        elif any(x in val for x in ['ERROR', 'BLOCKED', 'AUTH_ERROR']):
            color = '#f85149'
        badge.setText(f'{title} ● {value}')
        badge.setStyleSheet(f'padding: 3px 8px; border: 1px solid #283241; border-radius: 10px; color: {color}; font-weight: 600;')
        badge.setToolTip(details or str(value))

    def _log_harvest_state_if_changed(self):
        if not self._harvest_result:
            return
        state = self._harvest_result.state.value
        if state == self._last_harvest_state:
            return
        self._last_harvest_state = state
        reason = ', '.join(self._harvest_result.reasons[:2]) if self._harvest_result.reasons else 'no reason'
        self.logger.log('HARVEST', f'[{state}] {reason}')

    def _recalc_total(self):
        try:
            total = Decimal(self.price.text().strip()) * Decimal(self.qty.text().strip())
        except Exception:
            total = Decimal('0')
        self.total.setText(f'{total:.8f}')

    def _recalc_equity_total(self):
        usdt = Decimal(self.b['USDT свободно'].text()) + Decimal(self.b['USDT заблокировано'].text())
        euri = Decimal(self.b['EURI свободно'].text()) + Decimal(self.b['EURI заблокировано'].text())
        self.b['Оценка всего USDT'].setText(f"{(usdt + euri * Decimal(self.m['Последняя'].text())):.8f}")

    def _update_spread_panel(self, spread: Decimal, ticks):
        if self._spread_since is None:
            self._spread_since = time.time()
        elif spread != self._spread_value:
            self._spread_since = time.time()
        self._spread_value = spread
        lifetime = int((time.time() - self._spread_since) * 1000) if self._spread_since else 0
        self.m['Спред'].setText(f'{spread:.8f}')
        self.m['Тики'].setText(str(ticks))
        self.m['Lifetime'].setText(f'{lifetime} ms')
        self.m['Stable'].setText('СТАБИЛЕН' if lifetime >= 3000 else 'НЕСТАБИЛЕН')
        try:
            tick_val = float(ticks)
        except Exception:
            tick_val = 0.0
        self._spread_stability = self._spread_analyzer.classify(tick_val, lifetime)
        if spread > 0 and (ticks == '-' or ticks is None):
            self.m['Тики'].setText('1+')

    def _fill_price_bid(self):
        self.price.setText(self.m['Bid'].text())

    def _fill_price_ask(self):
        self.price.setText(self.m['Ask'].text())

    def _fill_qty_max_euri(self):
        self.qty.setText(self.b['EURI свободно'].text())

    def _fill_qty_for_10_usdt(self):
        try:
            price = Decimal(self.price.text() or self.m['Ask'].text())
            if price > 0:
                self.qty.setText(f"{(Decimal('10') / price):.8f}")
        except Exception:
            return

    def _on_order_selected(self):
        row = self.table.currentRow()
        if row >= 0 and self.table.item(row, 0):
            self._selected_order_id = int(self.table.item(row, 0).text())

    def _update_order_activity(self):
        order = self._orders_by_id.get(self._selected_order_id) if self._selected_order_id else None
        if not order and self._orders_by_id:
            order = max(self._orders_by_id.values(), key=lambda x: int(x.get('time', 0) or 0))
        self.s['Активный ордер'].setText(str(order.get('orderId')) if order else '-')
        if order:
            self.s['Время жизни'].setText(format_age_ms(max(0, int(time.time() * 1000) - int(order.get('time', 0) or 0))))
        else:
            self.s['Время жизни'].setText('-')
        self.s['Очередь'].setText('-')
        self.s['Reprice count'].setText('0')

    def _refresh_order_ages(self):
        now_ms = int(time.time() * 1000)
        for r in range(self.table.rowCount()):
            oid_item = self.table.item(r, 0)
            if not oid_item:
                continue
            order = self._orders_by_id.get(int(oid_item.text()))
            if order:
                self.table.setItem(r, 7, QTableWidgetItem(format_age_ms(max(0, now_ms - int(order.get('time', now_ms))))))

    def _update_runtime_fsm(self):
        if self.runtime.account_auth_state != 'CONNECTED':
            self.s['State'].setText('DISCONNECTED')
        elif self.cfg.get('read_only', True) or not self.cfg.get('trading_enabled', False):
            self.s['State'].setText('MANUAL_BLOCKED')
        else:
            self.s['State'].setText('MANUAL_READY')

    def _update_trade_buttons(self):
        reason = None
        if self.runtime.account_auth_state != 'CONNECTED':
            reason = 'аккаунт не подключён'
        elif self.cfg.get('read_only', True):
            reason = 'включён режим только чтение'
        elif not self.cfg.get('trading_enabled', False):
            reason = 'торговля выключена в настройках'
        elif self.filters is None:
            reason = 'фильтры Binance не загружены'
        enabled = reason is None
        for btn in (self.buy_btn, self.sell_btn):
            btn.setEnabled(enabled)
            btn.setToolTip('' if enabled else reason)

    def _update_execution_metrics(self, best_unchanged: bool):
        self._queue_quality = self._queue_estimator.classify(self._spread_stability, best_unchanged, self.runtime.last_latency_ms, self._latency_warning_ms)
        self.s['Queue quality'].setText(self._queue_quality)
        self.s['Spread stability'].setText(self._spread_stability)
        self.s['Market latency'].setText(format_latency_ms(self.runtime.last_latency_ms))
        self.s['Order reaction'].setText(format_latency_ms(self._order_reaction_ms))
        self.s['Fill probability'].setText(fill_probability_label(0, 0))
        self.s['Last fill time'].setText(last_fill_time_label(self._last_fill_ts))

    def _handle_order_transitions(self, current_ids: set[int]):
        transitions = diff_order_transitions(self._prev_open_order_ids, current_ids)
        for event in transitions:
            if event.transition == 'NEW':
                self.logger.log('EXEC', f'Open order NEW #{event.order_id}')
                continue
            self.logger.log('EXEC', f'Open order disappeared #{event.order_id}')
            status = self.orders.order_status(event.order_id)
            final_status = str(status.get('status', 'UNKNOWN'))
            if final_status == 'FILLED':
                self.logger.log('EXEC', 'Order FILLED')
                self._last_fill_ts = time.time()
                self.logger.log('EXEC', 'Last fill time updated')
            elif final_status == 'CANCELED':
                self.logger.log('EXEC', 'Order CANCELED')
        self._prev_open_order_ids = set(current_ids)

    def start_polling(self):
        if self.polling.start():
            self.runtime.set_polling(True)
            self.logger.log('ИНФО', 'Опрос запущен')

    def stop_polling(self):
        self.polling.stop()
        self.runtime.set_polling(False)
        self.logger.log('ИНФО', 'Опрос остановлен')


def run():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    w = MainWindow(); w.show(); sys.exit(app.exec())
