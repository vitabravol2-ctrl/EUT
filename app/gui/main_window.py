from __future__ import annotations

import sys
from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
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
from app.core.binance_client import BinanceClient
from app.core.config import load_config, save_config
from app.core.execution_metrics import QueueQualityEstimator, SpreadStabilityAnalyzer
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

DARK_STYLESHEET = """QWidget { background: #0b0f14; color: #e6edf3; }
QHeaderView::section { background: #141b24; color: #e6edf3; border: 1px solid #283241; }
QTableWidget { background: #0f141b; gridline-color: #283241; }
QTableWidget::item { background: #0f141b; color: #e6edf3; }
QPushButton { background: #1f6feb; color: white; border-radius: 6px; padding: 6px 10px; }
QPushButton:disabled { background: #2f3b4a; color: #8b949e; }
"""


class TradeSettingsDialog(QDialog):
    def __init__(self, cfg: dict, on_save, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Trade Settings')
        self._on_save = on_save
        l = QFormLayout(self)
        self.min_spread_ticks = QLineEdit(str(cfg.get('min_spread_ticks', 2)))
        self.stable_ms = QLineEdit(str(cfg.get('stable_ms', 3000)))
        self.max_order_usdt = QLineEdit(str(cfg.get('max_order_usdt', 10)))
        self.max_active_orders = QLineEdit(str(cfg.get('max_active_orders', 1)))
        self.risk_guard = QCheckBox('Enabled'); self.risk_guard.setChecked(bool(cfg.get('risk_guard_enabled', False)))
        l.addRow('Mode', QLabel('MANUAL'))
        l.addRow('Min spread ticks', self.min_spread_ticks)
        l.addRow('Stable ms', self.stable_ms)
        l.addRow('Max order USDT', self.max_order_usdt)
        l.addRow('Max active orders', self.max_active_orders)
        l.addRow('Risk guard', self.risk_guard)
        row = QHBoxLayout(); row.addWidget(QPushButton('Close', clicked=self.reject)); row.addWidget(QPushButton('Save', clicked=self._save))
        l.addRow(row)

    def _save(self):
        self._on_save({'min_spread_ticks': int(self.min_spread_ticks.text() or 0), 'stable_ms': int(self.stable_ms.text() or 3000), 'max_order_usdt': float(self.max_order_usdt.text() or 0), 'max_active_orders': int(self.max_active_orders.text() or 1), 'risk_guard_enabled': self.risk_guard.isChecked()})
        self.accept()


class ManualOrderDialog(QDialog):
    def __init__(self, main: 'MainWindow', parent=None):
        super().__init__(parent)
        self.main = main
        self.setWindowTitle('Manual Order')
        l = QFormLayout(self)
        self.side = QLineEdit('BUY'); self.price = QLineEdit(); self.qty = QLineEdit(); self.total = QLabel('0.00000000')
        self.price.textChanged.connect(self._calc); self.qty.textChanged.connect(self._calc)
        l.addRow('Side', self.side); l.addRow('Price', self.price); l.addRow('Qty', self.qty); l.addRow('Total', self.total)
        q1 = QHBoxLayout(); q1.addWidget(QPushButton('Bid', clicked=self._bid)); q1.addWidget(QPushButton('Ask', clicked=self._ask)); q1.addWidget(QPushButton('10 USDT', clicked=self._q10)); q1.addWidget(QPushButton('Max EURI', clicked=self._qmax)); l.addRow(q1)
        act = QHBoxLayout(); act.addWidget(QPushButton('BUY LIMIT', clicked=lambda: self.main.place('BUY'))); act.addWidget(QPushButton('SELL LIMIT', clicked=lambda: self.main.place('SELL'))); act.addWidget(QPushButton('Close', clicked=self.reject)); l.addRow(act)

    def _calc(self):
        try: t = Decimal(self.price.text()) * Decimal(self.qty.text())
        except Exception: t = Decimal('0')
        self.total.setText(f'{t:.8f}')

    def _bid(self): self.price.setText(self.main._market_bid())
    def _ask(self): self.price.setText(self.main._market_ask())
    def _q10(self):
        try: p = Decimal(self.price.text() or self.main._market_ask()); self.qty.setText(f"{(Decimal('10') / p):.8f}" if p > 0 else '0')
        except Exception: ...
    def _qmax(self): self.qty.setText(self.main._balance_euri())


class AllDataDialog(QDialog):
    def __init__(self, main: 'MainWindow', parent=None):
        super().__init__(parent)
        self.setWindowTitle('All Data')
        l = QVBoxLayout(self)
        for group in ['Account', 'Market', 'Harvest', 'Execution', 'Runtime', 'Filters']:
            g = QGroupBox(group); gl = QVBoxLayout(g); gl.addWidget(QLabel(main._all_data_text(group))); l.addWidget(g)


class MainWindow(QMainWindow):
    PILL_COLORS = {'OK': '#2ea043', 'WARN': '#d29922', 'ERROR': '#f85149', 'OFF': '#8b949e', 'READY': '#2ea043', 'WATCH': '#d29922', 'BAD': '#f85149', 'BLOCKED': '#f85149'}

    def __init__(self):
        super().__init__()
        self.setWindowTitle('EUT v0.3.5 — Minimal Harvest Cockpit + All Data Hidden')
        self.setMinimumSize(1280, 720); self.resize(1500, 900); self.setStyleSheet(DARK_STYLESHEET)
        self.logger = AppLogger(max_records=500, dedupe_seconds=30)
        self.cfg = load_config(); self.runtime = RuntimeState(); self.ws = WSManager(enabled=False)
        self.filters = None; self._orders_by_id = {}; self._last_market_snapshot = {}; self._last_open_orders = []; self._selected_order_id = None
        self._spread_analyzer = SpreadStabilityAnalyzer(); self._queue_estimator = QueueQualityEstimator(); self._harvest_engine = HarvestReadinessEngine(); self._harvest_result = None
        self._status_badges = {}; self._init_services(); self._build_ui()
        self.task_runner = TaskRunner(4, self); self.task_runner.signals.success.connect(self._on_task_success); self.task_runner.signals.error.connect(self._on_task_error); self.task_runner.signals.finished.connect(self.task_runner.finish)
        self.polling = PollingManager(self.refresh_market, self.refresh_orders, self.refresh_balances, 1000, 4000, 7000, self)
        self._status_timer = QTimer(self); self._status_timer.timeout.connect(self._tick_status); self._status_timer.start(250); QTimer.singleShot(50, self._startup_connect_flow)

    def _init_services(self):
        self.client = BinanceClient(self.cfg['api_key'], self.cfg['api_secret'], self.cfg['testnet'], self.cfg.get('request_timeout_sec', 3))
        self.market = MarketService(self.client, self.cfg['symbol']); self.account = AccountService(self.client); self.orders = OrderService(self.client, self.cfg['symbol'])

    def _btn(self, text, fn):
        b = QPushButton(text); b.setMinimumHeight(BUTTON_H); b.clicked.connect(fn); return b

    def _pill_style(self, tone): return f'padding: 2px 8px; border: 1px solid #283241; border-radius: 10px; color: {self.PILL_COLORS.get(tone, "#8b949e")}; font-weight: 600;'

    def _build_ui(self):
        self.setFont(QFont('', APP_FONT_PT)); root = QWidget(); self.setCentralWidget(root); main = QVBoxLayout(root)
        top = QGroupBox('Status Strip'); l = QHBoxLayout(top)
        for label in ['SYSTEM', 'TRADING', 'SPREAD', 'HARVEST', 'ORDERS', 'RISK']:
            bd = QLabel(f'{label} ● -'); bd.setStyleSheet(self._pill_style('OFF')); self._status_badges[label] = bd; l.addWidget(bd)
        l.addStretch(1); main.addWidget(top)

        split = QSplitter(Qt.Horizontal)
        left = QWidget(); ll = QVBoxLayout(left)
        g = QGroupBox('Harvest Settings'); fl = QFormLayout(g)
        self.hs_mode = QLabel('MANUAL'); self.hs_min = QLabel(str(self.cfg.get('min_spread_ticks', 2))); self.hs_stable = QLabel(str(self.cfg.get('stable_ms', 3000))); self.hs_max = QLabel(str(self.cfg.get('max_order_usdt', 10))); self.hs_active = QLabel(str(self.cfg.get('max_active_orders', 1))); self.hs_risk = QLabel('ON' if self.cfg.get('risk_guard_enabled', False) else 'OFF')
        for n,w in [('Mode', self.hs_mode), ('Min spread', self.hs_min), ('Stable', self.hs_stable), ('Max order', self.hs_max), ('Max active', self.hs_active), ('Risk guard', self.hs_risk)]: fl.addRow(n, w)
        r = QHBoxLayout(); r.addWidget(self._btn('Edit Harvest Settings', self.open_trade_settings)); r.addWidget(self._btn('Reset', self.reset_trade_settings)); fl.addRow(r)
        ll.addWidget(g); ll.addStretch(1)

        center = QWidget(); cl = QVBoxLayout(center)
        ob = QGroupBox('Open Orders'); ol = QVBoxLayout(ob); self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['ID', 'Side', 'Price', 'Qty', 'Filled', '%', 'Status', 'Age']); self.table.itemSelectionChanged.connect(self._on_order_selected)
        self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for i, w in OPEN_ORDERS_COL_WIDTHS.items(): self.table.setColumnWidth(i, w)
        ol.addWidget(self.table); self.no_orders = QLabel('No open orders'); self.no_orders.setAlignment(Qt.AlignCenter); ol.addWidget(self.no_orders); cl.addWidget(ob)

        right = QWidget(); rl = QVBoxLayout(right)
        hc = QGroupBox('Harvest Indicator'); hcl = QFormLayout(hc); self.harvest_state = QLabel('NOT_READY'); self.harvest_score = QLabel('0/100'); self.harvest_reason = QLabel('-'); hcl.addRow('State', self.harvest_state); hcl.addRow('Score', self.harvest_score); hcl.addRow('Main reason', self.harvest_reason)
        sc = QGroupBox('Spread Indicator'); scl = QFormLayout(sc); self.spread_state = QLabel('BAD'); self.spread_ticks = QLabel('-'); self.spread_stable = QLabel('NO'); self.spread_life = QLabel('-'); scl.addRow('Spread', self.spread_state); scl.addRow('Ticks', self.spread_ticks); scl.addRow('Stable', self.spread_stable); scl.addRow('Lifetime', self.spread_life)
        ac = QGroupBox('Actions'); acl = QVBoxLayout(ac)
        for txt, fn in [('Manual Order', self.open_manual_order), ('Cancel Selected', self.cancel_selected), ('Cancel All', self.cancel_all), ('All Data', self.open_all_data), ('Settings', self.open_settings), ('Diagnostics', self.run_diagnostics)]: acl.addWidget(self._btn(txt, fn))
        rl.addWidget(hc); rl.addWidget(sc); rl.addWidget(ac); rl.addStretch(1)

        split.addWidget(left); split.addWidget(center); split.addWidget(right); split.setSizes([300, 850, 350]); main.addWidget(split, 1)
        logs = QGroupBox('Logs'); logs.setMinimumHeight(120); logs.setMaximumHeight(160); llg = QVBoxLayout(logs); self.log_panel = LogPanel(500); self.logger.subscribe(self.log_panel.append_record); llg.addWidget(self.log_panel); main.addWidget(logs)

    def _startup_connect_flow(self): self.refresh_market(force=True); self.start_polling()
    def open_settings(self): self.settings_dialog = SettingsDialog(self.cfg, self.apply_settings, self.test_connection, self); self.settings_dialog.show()
    def open_trade_settings(self): self.trade_settings_dialog = TradeSettingsDialog(self.cfg, self.apply_trade_settings, self); self.trade_settings_dialog.show()
    def open_manual_order(self): self.manual_order_dialog = ManualOrderDialog(self, self); self.manual_order_dialog.show()
    def open_all_data(self): self.all_data_dialog = AllDataDialog(self, self); self.all_data_dialog.show()
    def apply_settings(self, values: dict): self.cfg.update(values); save_config(self.cfg)
    def apply_trade_settings(self, values: dict): self.cfg.update(values); save_config(self.cfg); self._sync_harvest_settings_labels()
    def test_connection(self, values: dict): return True, 'ok'
    def refresh_market(self, force=False): self.task_runner.run_task('market', lambda: self.market.snapshot())
    def refresh_balances(self, force=False): self.task_runner.run_task('balances', lambda: self.account.balances(Decimal(str(self._last_market_snapshot.get('last', 0) or 0))))
    def refresh_orders(self, force=False): self.task_runner.run_task('orders', self.orders.open_orders)
    def _on_task_success(self, name, payload):
        if name == 'market': self._last_market_snapshot = dict(payload); self._update_spread(payload); self._recompute_harvest_readiness()
        elif name == 'balances': self._balances = payload
        elif name == 'orders':
            self._last_open_orders = payload; self._orders_by_id = {int(o.get('orderId')): o for o in payload if o.get('orderId') is not None}; self.table.setRowCount(len(payload)); self.no_orders.setVisible(len(payload) == 0)
            for r, o in enumerate(payload):
                vals = [o.get('orderId'), o.get('side'), o.get('price'), o.get('origQty'), o.get('executedQty'), '0%', o.get('status'), '-']
                for c, v in enumerate(vals): self.table.setItem(r, c, QTableWidgetItem(str(v)))
    def _on_task_error(self, name, err): self.logger.log('ОШИБКА', f'{name}: {err}')
    def _tick_status(self):
        self._set_status_badge('SYSTEM', 'OK', f"REST OK, Account {self.runtime.account_auth_state}, Private {self.runtime.private_polling_state}, Latency {self.runtime.last_latency_ms}ms")
        self._set_status_badge('TRADING', 'ON' if self.cfg.get('trading_enabled', False) else 'OFF')
        self._set_status_badge('SPREAD', self.spread_state.text(), f"Bid={self._market_bid()}, Ask={self._market_ask()}, Ticks={self.spread_ticks.text()}")
        self._set_status_badge('HARVEST', self.harvest_state.text(), self.harvest_reason.text())
        self._set_status_badge('ORDERS', str(len(self._last_open_orders)), f"Open orders {len(self._last_open_orders)}, selected {self._selected_order_id}")
        self._set_status_badge('RISK', 'BLOCKED' if self.cfg.get('risk_guard_enabled', False) else 'OK')
    def _set_status_badge(self, key, value, details=''):
        b = self._status_badges[key]; t = str(value).upper(); tone = 'OFF'
        if t in ('OK', 'ON', 'READY') or t.isdigit(): tone = 'OK'
        elif t in ('WATCH', 'WARN'): tone = 'WARN'
        elif t in ('BAD', 'ERROR', 'BLOCKED', 'NOT_READY'): tone = 'ERROR'
        b.setText(f'{key} ● {value}'); b.setStyleSheet(self._pill_style(tone)); b.setToolTip(details or str(value))
    def _update_spread(self, s):
        ticks = s.get('spread_ticks', '-'); self.spread_ticks.setText(str(ticks)); self.spread_stable.setText('YES' if str(ticks).isdigit() and int(ticks) >= int(self.cfg.get('min_spread_ticks', 2)) else 'NO')
        self.spread_state.setText('READY' if self.spread_stable.text() == 'YES' else 'WATCH'); self.spread_life.setText('1s')
    def _recompute_harvest_readiness(self):
        self._harvest_result = self._harvest_engine.analyze(dict(self._last_market_snapshot or {}), {'latency_ms': self.runtime.last_latency_ms, 'queue_quality': 'MEDIUM', 'spread_stability': self.spread_state.text()}, self.filters, {'account_connected': True, 'trading_enabled': self.cfg.get('trading_enabled', False), 'read_only': self.cfg.get('read_only', True), 'risk_blocked': False, 'max_active_orders': int(self.cfg.get('max_active_orders', 1))}, self._last_open_orders)
        if self._harvest_result:
            self.harvest_state.setText(self._harvest_result.state.value); self.harvest_score.setText(f'{self._harvest_result.score}/100'); self.harvest_reason.setText((self._harvest_result.reasons or ['-'])[0])
    def _on_order_selected(self):
        it = self.table.item(self.table.currentRow(), 0); self._selected_order_id = int(it.text()) if it else None
    def _market_bid(self): return f"{Decimal(str(self._last_market_snapshot.get('bid', 0))):.8f}"
    def _market_ask(self): return f"{Decimal(str(self._last_market_snapshot.get('ask', 0))):.8f}"
    def _balance_euri(self): return f"{Decimal(str(getattr(self, '_balances', {}).get('EURI_free', 0))):.8f}"
    def _sync_harvest_settings_labels(self):
        self.hs_min.setText(str(self.cfg.get('min_spread_ticks', 2))); self.hs_stable.setText(str(self.cfg.get('stable_ms', 3000))); self.hs_max.setText(str(self.cfg.get('max_order_usdt', 10))); self.hs_active.setText(str(self.cfg.get('max_active_orders', 1))); self.hs_risk.setText('ON' if self.cfg.get('risk_guard_enabled', False) else 'OFF')
    def place(self, side): self.logger.log('ИНФО', f'place {side}')
    def cancel_selected(self): self.logger.log('ИНФО', 'cancel selected')
    def cancel_all(self): self.logger.log('ИНФО', 'cancel all')
    def run_diagnostics(self): self.logger.log('ИНФО', 'diag')
    def start_polling(self): self.polling.start(); self.runtime.set_polling(True)
    def stop_polling(self): self.polling.stop(); self.runtime.set_polling(False)
    def reset_trade_settings(self): self.apply_trade_settings({'min_spread_ticks': 2, 'stable_ms': 3000, 'max_order_usdt': 10.0, 'max_active_orders': 1, 'risk_guard_enabled': False})
    def _all_data_text(self, group):
        return {
            'Account': 'REST status, Account status, Private status, Trading enabled, Read only, USDT free/locked/total, EURI free/locked/total, Equity',
            'Market': 'Last, Bid, Ask, Spread raw, Spread ticks, Tick size, REST age, Latency, WS state',
            'Harvest': 'State, Score, Reasons, spread_ok, stability_ok, latency_ok, queue_ok, entry_possible, exit_possible, suggested_side',
            'Execution': 'Queue quality, Spread stability, Order reaction, Fill probability, Last fill time, Open order watcher state',
            'Runtime': 'FSM state, TaskRunner in_flight, skipped tasks, polling timers, last errors',
            'Filters': 'tickSize, stepSize, minQty, minNotional',
        }[group]


def run():
    app = QApplication(sys.argv); w = MainWindow(); w.show(); sys.exit(app.exec())
