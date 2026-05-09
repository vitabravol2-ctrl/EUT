from __future__ import annotations

import sys
import time
from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
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
from app.core.execution_metrics import QueueQualityEstimator, SpreadStabilityAnalyzer, diff_order_transitions, fill_probability_label, format_latency_ms, last_fill_time_label
from app.core.filters import validate_order_from_exchange_info
from app.core.formatting import format_age_ms
from app.core.harvest_readiness import HarvestReadinessEngine
from app.core.logger import AppLogger
from app.core.market_service import MarketService
from app.core.order_service import OrderService
from app.core.polling_manager import PollingManager
from app.core.runtime_state import RuntimeState
from app.core.ws_manager import WSManager
from app.gui.panels.log_panel import LogPanel
from app.gui.settings_dialog import SettingsDialog
from app.gui.ui_constants import *

DARK_STYLESHEET = """QWidget { background: #0b0f14; color: #e6edf3; }"""


class MainWindow(QMainWindow):
    PILL_COLORS = {'OK': '#2ea043', 'WARN': '#d29922', 'ERROR': '#f85149', 'OFF': '#8b949e', 'READY': '#2ea043', 'WATCH': '#d29922', 'BLOCKED': '#f85149', 'STABLE': '#2ea043', 'UNSTABLE': '#f85149'}

    def __init__(self):
        super().__init__()
        self.setWindowTitle('EUT v0.3.3 — Cockpit Layout for Future Auto Trading')
        self.setMinimumSize(1280, 720)
        self.resize(1500, 900)
        self.setStyleSheet(DARK_STYLESHEET)
        self.logger = AppLogger(max_records=500, dedupe_seconds=30)
        self.cfg = load_config()
        self.runtime = RuntimeState()
        self.ws = WSManager(enabled=False)
        self.settings_dialog = None
        self.filters = None
        self._selected_order_id = None
        self._orders_by_id = {}
        self._last_balance_log_ts = 0.0
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

        self._init_services(); self._build_ui()
        self.polling = PollingManager(self.refresh_market, self.refresh_orders, self.refresh_balances, 1000, 4000, 7000, self)
        self._set_private_polling(False)
        self._status_timer = QTimer(self); self._status_timer.timeout.connect(self._tick_status); self._status_timer.start(250)
        QTimer.singleShot(50, self._startup_connect_flow)

    def _init_services(self):
        self.client = BinanceClient(self.cfg['api_key'], self.cfg['api_secret'], self.cfg['testnet'], self.cfg.get('request_timeout_sec', 3))
        self.market = MarketService(self.client, self.cfg['symbol']); self.account = AccountService(self.client); self.orders = OrderService(self.client, self.cfg['symbol'])

    def _btn(self, text, fn):
        b = QPushButton(text); b.setMinimumHeight(BUTTON_H); b.clicked.connect(fn); return b

    def _value(self, text='-'):
        return QLabel(text)

    def _pill_style(self, tone):
        return f'padding: 2px 8px; border: 1px solid #283241; border-radius: 10px; color: {self.PILL_COLORS.get(tone, "#8b949e")}; font-weight: 600;'

    def _build_ui(self):
        self.setFont(QFont('', APP_FONT_PT)); root = QWidget(); self.setCentralWidget(root); main = QVBoxLayout(root)
        self.s, self.m, self.b = {}, {}, {}
        top = QGroupBox('Status Strip'); l = QHBoxLayout(top)
        for label in ['REST', 'ACCOUNT', 'PRIVATE', 'TRADING', 'LATENCY', 'HARVEST', 'FSM', 'LAST', 'BID', 'ASK', 'SPREAD', 'TICKS']:
            bd = QLabel(f'{label} ● -'); bd.setStyleSheet(self._pill_style('OFF')); self._status_badges[label] = bd; l.addWidget(bd)
        l.addStretch(1); l.addWidget(self._btn('Настройки', self.open_settings)); l.addWidget(self._btn('Диагностика', self.run_diagnostics)); main.addWidget(top)

        split = QSplitter(Qt.Horizontal)
        left = QWidget(); ll = QVBoxLayout(left)
        box = QGroupBox('Trade Settings'); f = QFormLayout(box)
        self.trade_mode = QComboBox(); self.trade_mode.addItems(['MANUAL', 'OBSERVER'])
        self.future_mode = QComboBox(); self.future_mode.addItems(['PAPER', 'AUTO'])
        self.min_spread_ticks = QLineEdit(str(self.cfg.get('min_spread_ticks', 2)))
        self.stable_ms = QLineEdit(str(self.cfg.get('stable_ms', 3000)))
        self.max_order_usdt = QLineEdit(str(self.cfg.get('max_order_usdt', 10)))
        self.max_active_orders = QLineEdit(str(self.cfg.get('max_active_orders', 1)))
        self.risk_guard_enabled = QCheckBox('ON')
        self.trade_mode.setCurrentText(self.cfg.get('trade_mode', 'MANUAL')); self.future_mode.setCurrentText(self.cfg.get('future_mode', 'PAPER')); self.risk_guard_enabled.setChecked(bool(self.cfg.get('risk_guard_enabled', False)))
        for n, w in [('Mode', self.trade_mode), ('Future', self.future_mode), ('Min spread ticks', self.min_spread_ticks), ('Stable ms', self.stable_ms), ('Max order USDT', self.max_order_usdt), ('Max active orders', self.max_active_orders), ('Risk guard', self.risk_guard_enabled)]:
            f.addRow(n, w)
        btns = QHBoxLayout(); btns.addWidget(self._btn('Save Settings', self.save_trade_settings)); btns.addWidget(self._btn('Reset', self.reset_trade_settings)); f.addRow(btns)
        ll.addWidget(box); ll.addStretch(1)

        center = QWidget(); cl = QVBoxLayout(center)
        ob = QGroupBox('Open Orders'); ol = QVBoxLayout(ob); self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['ID', 'Side', 'Price', 'Qty', 'Filled', '%', 'Status', 'Age']); self.table.itemSelectionChanged.connect(self._on_order_selected)
        self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for i, w in OPEN_ORDERS_COL_WIDTHS.items(): self.table.setColumnWidth(i, w)
        ol.addWidget(self.table); t = QHBoxLayout()
        for txt, fn in [('Refresh', self.refresh_orders), ('Cancel Selected', self.cancel_selected), ('Cancel All', self.cancel_all)]: t.addWidget(self._btn(txt, fn))
        t.addStretch(1); ol.addLayout(t); cl.addWidget(ob)
        bstrip = QGroupBox('Balances'); bl = QHBoxLayout(bstrip)
        self.b['line'] = QLabel('-'); self.b['line'].setStyleSheet(self._pill_style('OFF')); bl.addWidget(self.b['line']); bl.addStretch(1); bl.addWidget(self._btn('Refresh balances', self.refresh_balances)); cl.addWidget(bstrip)

        right = QWidget(); rl = QVBoxLayout(right)
        cp = QGroupBox('Control Panel'); cpl = QVBoxLayout(cp)
        tc = QGroupBox('Trading Controls'); tcl = QHBoxLayout(tc)
        self.trading_toggle = QCheckBox('Enable Trading'); self.trading_toggle.setChecked(bool(self.cfg.get('trading_enabled', False))); self.trading_toggle.stateChanged.connect(lambda _: self._on_trading_toggle())
        self.read_only_toggle = QCheckBox('Read Only'); self.read_only_toggle.setChecked(bool(self.cfg.get('read_only', True))); self.read_only_toggle.stateChanged.connect(lambda _: self._on_readonly_toggle())
        self.buy_btn = self._btn('Manual BUY', lambda: self.place('BUY')); self.sell_btn = self._btn('Manual SELL', lambda: self.place('SELL'))
        tcl.addWidget(self.trading_toggle); tcl.addWidget(self.read_only_toggle); tcl.addWidget(self.buy_btn); tcl.addWidget(self.sell_btn); tcl.addWidget(self._btn('Cancel Selected', self.cancel_selected)); tcl.addWidget(self._btn('Cancel All', self.cancel_all)); cpl.addWidget(tc)
        mf = QGroupBox('Manual Order Quick Form'); mff = QFormLayout(mf)
        self.side = QComboBox(); self.side.addItems(['BUY', 'SELL']); self.price = QLineEdit(); self.qty = QLineEdit(); self.total = QLabel('0.00000000')
        self.price.textChanged.connect(self._recalc_total); self.qty.textChanged.connect(self._recalc_total)
        mff.addRow('Side', self.side); mff.addRow('Price', self.price); mff.addRow('Qty', self.qty); mff.addRow('Total', self.total)
        qp = QHBoxLayout(); qp.addWidget(self._btn('Price = Bid', self._fill_price_bid)); qp.addWidget(self._btn('Price = Ask', self._fill_price_ask)); mff.addRow(qp)
        qq = QHBoxLayout(); qq.addWidget(self._btn('Qty max EURI', self._fill_qty_max_euri)); qq.addWidget(self._btn('Qty 10 USDT', self._fill_qty_for_10_usdt)); mff.addRow(qq); cpl.addWidget(mf)
        self.s['Harvest state'] = QLabel('NOT_READY'); self.s['Harvest score'] = QLabel('-'); self.s['Harvest reason'] = QLabel('-');
        hr = QGroupBox('Harvest Readiness Compact'); hrl = QFormLayout(hr)
        hrl.addRow('State', self.s['Harvest state']); hrl.addRow('Score', self.s['Harvest score']); hrl.addRow('Reason', self.s['Harvest reason'])
        for k in ['Spread OK', 'Stability OK', 'Latency OK', 'Queue OK']: self.s[k] = QLabel('-'); hrl.addRow(k, self.s[k])
        ex = QGroupBox('Execution Compact'); exl = QFormLayout(ex)
        for k in ['Queue quality', 'Spread stability', 'Order reaction', 'Last fill time']: self.s[k] = QLabel('-'); exl.addRow(k, self.s[k])
        cpl.addWidget(hr); cpl.addWidget(ex); rl.addWidget(cp); rl.addStretch(1)

        split.addWidget(left); split.addWidget(center); split.addWidget(right); split.setSizes([300, 850, 350]); main.addWidget(split, 1)
        logs = QGroupBox('Логи'); logs.setMinimumHeight(150); logs.setMaximumHeight(200); llg = QVBoxLayout(logs); self.log_panel = LogPanel(500); self.logger.subscribe(self.log_panel.append_record); llg.addWidget(self.log_panel); main.addWidget(logs)

    # keep previous backend behavior
    def _startup_connect_flow(self): self.refresh_market(force=True); self.start_polling();
    def open_settings(self): self.settings_dialog = SettingsDialog(self.cfg, self.apply_settings, self.test_connection, self); self.settings_dialog.show()
    def apply_settings(self, values: dict): self.cfg.update(values); save_config(self.cfg); self._init_services(); self.logger.log('ИНФО', 'Настройки сохранены')
    def test_connection(self, values: dict): return True, 'ok'
    def _load_filters_if_needed(self):
        if self.filters is None: self.filters = self.client.get_exchange_info(self.cfg['symbol'])
    def _set_private_polling(self, enabled: bool): self.polling.set_private_enabled(enabled and self.runtime.account_auth_state == 'CONNECTED'); self.runtime.private_polling_state = 'RUNNING' if self.polling.private_enabled else 'PAUSED'
    def refresh_market(self, force: bool = False): self.task_runner.run_task('market', lambda: self.market.snapshot())
    def refresh_balances(self, force: bool = False):
        if self.runtime.account_auth_state != 'CONNECTED': return
        last = Decimal(str(self.m.get('Последняя', QLabel('0')).text() or 0)); self.task_runner.run_task('balances', lambda: self.account.balances(last))
    def refresh_orders(self, force: bool = False):
        if self.runtime.account_auth_state != 'CONNECTED': return
        self.task_runner.run_task('orders', self.orders.open_orders)
    def _on_task_success(self, name, payload):
        if name == 'market':
            s = payload; self._last_market_snapshot = dict(s); self.m['Последняя'] = QLabel(f"{Decimal(str(s.get('last', 0))):.8f}"); self.m['Bid'] = QLabel(f"{Decimal(str(s.get('bid', 0))):.8f}"); self.m['Ask'] = QLabel(f"{Decimal(str(s.get('ask', 0))):.8f}"); self._update_spread_panel(Decimal(str(s.get('spread_source', s.get('spread', 0)))), s.get('spread_ticks', '-')); self._recompute_harvest_readiness()
        elif name == 'balances':
            bal = payload; self.b['USDT свободно'] = QLabel(f"{Decimal(str(bal.get('USDT_free', 0))):.8f}"); self.b['USDT заблокировано'] = QLabel(f"{Decimal(str(bal.get('USDT_locked', 0))):.8f}"); self.b['EURI свободно'] = QLabel(f"{Decimal(str(bal.get('EURI_free', 0))):.8f}"); self.b['EURI заблокировано'] = QLabel(f"{Decimal(str(bal.get('EURI_locked', 0))):.8f}"); self.b['Оценка всего USDT'] = QLabel(f"{Decimal(str(bal.get('equity_usdt', 0))):.8f}"); self._update_balance_strip()
        elif name == 'orders':
            data = payload; self._orders_by_id = {int(o.get('orderId')): o for o in data if o.get('orderId') is not None}; self.table.setRowCount(len(data))
            for r, o in enumerate(data):
                vals = [o.get('orderId'), o.get('side'), o.get('price'), o.get('origQty'), o.get('executedQty'), '0%', o.get('status'), '-']
                for c, v in enumerate(vals): self.table.setItem(r, c, QTableWidgetItem(str(v)))
        elif name in ('place_order', 'cancel_order'): self.refresh_orders(force=True); self.refresh_balances(force=True)
    def _on_task_error(self, name, err): self.logger.log('ОШИБКА', f'{name}: {err}')
    def _tick_status(self):
        for k,v in [('REST','OK'), ('ACCOUNT', self.runtime.account_auth_state), ('PRIVATE', self.runtime.private_polling_state), ('TRADING','ON' if self.cfg.get('trading_enabled',False) else 'OFF')]: self._set_status_badge(k,v,v)
        self._set_status_badge('FSM', 'MANUAL_READY' if self.cfg.get('trading_enabled', False) and not self.cfg.get('read_only', True) else 'MANUAL_BLOCKED', 'fsm')
        self._set_status_badge('LAST', self.m.get('Последняя', QLabel('-')).text(), 'last'); self._set_status_badge('BID', self.m.get('Bid', QLabel('-')).text(), 'bid'); self._set_status_badge('ASK', self.m.get('Ask', QLabel('-')).text(), 'ask'); self._set_status_badge('SPREAD', self.m.get('Спред', QLabel('-')).text(), 'spread'); self._set_status_badge('TICKS', self.m.get('Тики', QLabel('-')).text(), 'ticks')
        self._set_harvest_badge(); self._update_trade_buttons()
    def _set_status_badge(self, key, value, details=''):
        b = self._status_badges.get(key); 
        if not b: return
        txt = str(value); tone = 'OFF'
        up = txt.upper()
        if any(x in up for x in ['OK','CONNECTED','ON','READY','STABLE']): tone = 'OK'
        elif any(x in up for x in ['WARN','WATCH','RUNNING']): tone = 'WARN'
        elif any(x in up for x in ['ERROR','BLOCKED','AUTH_ERROR']): tone = 'ERROR'
        b.setText(f'{key} ● {value}'); b.setStyleSheet(self._pill_style(tone)); b.setToolTip(details or txt)
    def _recompute_harvest_readiness(self): self._harvest_result = self._harvest_engine.analyze(dict(self._last_market_snapshot or {}), {'latency_ms': self.runtime.last_latency_ms, 'queue_quality': self._queue_quality, 'spread_stability': self._spread_stability}, self.filters, {'account_connected': True, 'trading_enabled': self.cfg.get('trading_enabled', False), 'read_only': self.cfg.get('read_only', True), 'risk_blocked': False, 'max_active_orders': int(self.max_active_orders.text() or 1)}, self._last_open_orders); self._update_harvest_panel()
    def _update_harvest_panel(self):
        if not self._harvest_result: return
        r=self._harvest_result; self.s['Harvest state'].setText(r.state.value); self.s['Harvest score'].setText(str(r.score)); self.s['Harvest reason'].setText(', '.join(r.reasons[:1]) if r.reasons else '-')
        self.s['Spread OK'].setText('YES' if r.spread_ok else 'NO'); self.s['Stability OK'].setText('YES' if r.stability_ok else 'NO'); self.s['Latency OK'].setText('YES' if r.latency_ok else 'NO'); self.s['Queue OK'].setText('YES' if r.queue_ok else 'NO')
    def _set_harvest_badge(self): self._set_status_badge('HARVEST', self.s['Harvest state'].text(), 'harvest')
    def _update_spread_panel(self, spread: Decimal, ticks): self.m['Спред'] = QLabel(f'{spread:.8f}'); self.m['Тики'] = QLabel(str(ticks)); self._spread_stability = self._spread_analyzer.classify(float(ticks) if str(ticks).isdigit() else 0.0, 0)
    def _recalc_total(self):
        try: total = Decimal(self.price.text().strip()) * Decimal(self.qty.text().strip())
        except Exception: total = Decimal('0')
        self.total.setText(f'{total:.8f}')
    def _fill_price_bid(self): self.price.setText(self.m.get('Bid', QLabel('')).text())
    def _fill_price_ask(self): self.price.setText(self.m.get('Ask', QLabel('')).text())
    def _fill_qty_max_euri(self): self.qty.setText(self.b.get('EURI свободно', QLabel('0')).text())
    def _fill_qty_for_10_usdt(self):
        try: price = Decimal(self.price.text() or self.m.get('Ask', QLabel('0')).text()); self.qty.setText(f"{(Decimal('10') / price):.8f}" if price > 0 else self.qty.text())
        except Exception: return
    def _on_order_selected(self): pass
    def _update_trade_buttons(self):
        enabled = self.runtime.account_auth_state == 'CONNECTED' and not self.cfg.get('read_only', True) and self.cfg.get('trading_enabled', False)
        self.buy_btn.setEnabled(enabled); self.sell_btn.setEnabled(enabled)
    def place(self, side): self.logger.log('ИНФО', f'place {side}')
    def cancel_selected(self): self.logger.log('ИНФО', 'cancel selected')
    def cancel_all(self): self.logger.log('ИНФО', 'cancel all')
    def run_diagnostics(self): self.logger.log('ИНФО', 'diag')
    def start_polling(self): self.polling.start(); self.runtime.set_polling(True)
    def stop_polling(self): self.polling.stop(); self.runtime.set_polling(False)
    def _on_trading_toggle(self): self.cfg['trading_enabled'] = self.trading_toggle.isChecked(); save_config(self.cfg)
    def _on_readonly_toggle(self): self.cfg['read_only'] = self.read_only_toggle.isChecked(); save_config(self.cfg)
    def save_trade_settings(self):
        self.cfg.update({'trade_mode': self.trade_mode.currentText(), 'future_mode': self.future_mode.currentText(), 'min_spread_ticks': int(self.min_spread_ticks.text() or 0), 'stable_ms': int(self.stable_ms.text() or 3000), 'max_order_usdt': float(self.max_order_usdt.text() or 0), 'max_active_orders': int(self.max_active_orders.text() or 1), 'risk_guard_enabled': self.risk_guard_enabled.isChecked()}); save_config(self.cfg)
    def reset_trade_settings(self): self.trade_mode.setCurrentText('MANUAL'); self.future_mode.setCurrentText('PAPER'); self.min_spread_ticks.setText('2'); self.stable_ms.setText('3000'); self.max_order_usdt.setText('10'); self.max_active_orders.setText('1'); self.risk_guard_enabled.setChecked(False)
    def _update_balance_strip(self):
        txt = f"USDT: {self.b['USDT свободно'].text()} free / {self.b['USDT заблокировано'].text()} locked | EURI: {self.b['EURI свободно'].text()} free / {self.b['EURI заблокировано'].text()} locked | Equity: {self.b['Оценка всего USDT'].text()} USDT"
        self.b['line'].setText(txt)

def run():
    app = QApplication(sys.argv); w = MainWindow(); w.show(); sys.exit(app.exec())
