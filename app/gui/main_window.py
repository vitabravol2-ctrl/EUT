from __future__ import annotations

import sys
from decimal import Decimal
import time
import traceback

from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView, QTextEdit
from shiboken6 import isValid

from app.core.account_service import AccountService
from app.core.fill_observer import FillObserver, MarketActivity
from app.core.async_runner import TaskRunner
from app.core.binance_client import BinanceAPIError, BinanceClient
from app.core.config import load_config, save_config
from app.core.execution_metrics import QueueQualityEstimator, SpreadStabilityAnalyzer
from app.core.filters import extract_symbol_filters, format_decimal_for_step, format_decimal_for_tick, floor_to_step, floor_to_tick, normalize_price, normalize_qty, validate_order, validate_order_from_exchange_info
from app.core.harvest_readiness import HarvestReadinessEngine
from app.core.harvest_cycle import CycleState, HarvestCycle
from app.core.logger import AppLogger
from app.core.market_service import MarketService
from app.core.order_service import OrderService
from app.core.polling_manager import PollingManager
from app.core.pair_profiles import get_pair_config, list_pairs
from app.core.spread_stability_engine import ReadinessState, SpreadStabilityEngine
from app.core.runtime_state import RuntimeState
from app.core.trade_ledger import TradeLedger
from app.core.ws_manager import WSManager
from app.core.reconcile import safe_status, should_clear_active_order
from app.gui.panels.log_panel import LogPanel
from app.gui.settings_dialog import SettingsDialog
from app.gui.ui_constants import *

DEBUG_FORCE_START = False

DARK_STYLESHEET = """
QWidget { background: #0b0f14; color: #e6edf3; }
QPushButton {
  background: #1f2a37;
  color: #e6edf3;
  border: 1px solid #324155;
  border-radius: 6px;
  padding: 6px 10px;
  font-weight: 600;
}
QPushButton:hover { background: #2b3a4b; }
QPushButton:pressed { background: #17212c; }
QPushButton:disabled { background: #4b5563; color: #9ca3af; border-color: #4b5563; }
"""

class TradeSettingsDialog(QDialog):
    def __init__(self, cfg: dict, on_save, parent=None):
        super().__init__(parent); self._on_save = on_save; self.setWindowTitle('Trade / Harvest Settings')
        l = QFormLayout(self)
        self.symbol = QLineEdit(str(cfg.get('symbol', 'EURIUSDT')))
        self.min_spread_ticks = QLineEdit(str(cfg.get('min_spread_ticks', 2))); self.target_profit_ticks = QLineEdit(str(cfg.get('target_profit_ticks', 1))); self.stable_ms = QLineEdit(str(cfg.get('min_stable_ms', 3000)))
        self.allow_partial = QCheckBox('YES'); self.allow_partial.setChecked(bool(cfg.get('allow_partial_fills', True))); self.min_partial = QLineEdit(str(cfg.get('min_partial_fill_euri', 0)))
        self.reprice_on_move = QCheckBox('YES'); self.reprice_on_move.setChecked(bool(cfg.get('reprice_on_move', True))); self.cancel_on_collapse = QCheckBox('YES'); self.cancel_on_collapse.setChecked(bool(cfg.get('cancel_on_spread_collapse', True)))
        self.max_buy_exposure = QLineEdit(str(cfg.get('max_buy_usdt_exposure', 10)))
        self.max_sell_exposure = QLineEdit(str(cfg.get('max_sell_usdt_exposure', 10)))
        self.risk_guard = QCheckBox('Enabled'); self.risk_guard.setChecked(bool(cfg.get('risk_guard_enabled', False)))
        self.target_inv = QLineEdit(str(cfg.get('target_inventory_ratio', 0.5)))
        self.soft_inv = QLineEdit(str(cfg.get('inventory_soft_limit', 0.65)))
        self.hard_inv = QLineEdit(str(cfg.get('inventory_hard_limit', 0.80)))
        l.addRow('Mode', QLabel('LIVE TRADE'))
        for n,w in [('Symbol',self.symbol),('Max BUY exposure USDT',self.max_buy_exposure),('Max SELL exposure USDT',self.max_sell_exposure),('Target inv ratio',self.target_inv),('Inv soft limit',self.soft_inv),('Inv hard limit',self.hard_inv),('Min spread ticks',self.min_spread_ticks),('Target profit ticks',self.target_profit_ticks),('Min stable ms',self.stable_ms),('Allow partial fills',self.allow_partial),('Min partial fill EURI',self.min_partial),('Reprice on bid/ask move',self.reprice_on_move),('Cancel on spread collapse',self.cancel_on_collapse),('Risk guard',self.risk_guard)]: l.addRow(n,w)
        row=QHBoxLayout(); row.addWidget(QPushButton('Save', clicked=self._save)); row.addWidget(QPushButton('Close', clicked=self.reject)); l.addRow(row)
    def _save(self):
        self._on_save({'symbol': self.symbol.text().strip() or 'EURIUSDT', 'harvest_mode': 'LIVE_TRADE', 'min_spread_ticks': int(self.min_spread_ticks.text() or 2), 'target_profit_ticks': int(self.target_profit_ticks.text() or 1), 'min_stable_ms': int(self.stable_ms.text() or 3000), 'max_buy_usdt_exposure': float(self.max_buy_exposure.text() or 10), 'max_sell_usdt_exposure': float(self.max_sell_exposure.text() or 10), 'target_inventory_ratio': float(self.target_inv.text() or 0.5), 'inventory_soft_limit': float(self.soft_inv.text() or 0.65), 'inventory_hard_limit': float(self.hard_inv.text() or 0.8), 'allow_partial_fills': self.allow_partial.isChecked(), 'min_partial_fill_euri': float(self.min_partial.text() or 0), 'reprice_on_move': self.reprice_on_move.isChecked(), 'cancel_on_spread_collapse': self.cancel_on_collapse.isChecked(), 'risk_guard_enabled': self.risk_guard.isChecked()}); self.accept()

class ManualOrderDialog(QDialog):
    def __init__(self, main, parent=None):
        super().__init__(parent); self.main=main; self.setWindowTitle('Manual Order'); l=QFormLayout(self)
        self.bid=QLabel('-'); self.ask=QLabel('-'); self.side=QComboBox(); self.side.addItems(['BUY','SELL']); self.price=QLineEdit(); self.qty=QLineEdit(); self.total=QLabel('0.00000000')
        self.price.textChanged.connect(self._calc); self.qty.textChanged.connect(self._calc)
        l.addRow('Bid',self.bid); l.addRow('Ask',self.ask); l.addRow('Side',self.side); l.addRow('Price',self.price); l.addRow('Qty',self.qty); l.addRow('Total',self.total)
        r=QHBoxLayout(); r.addWidget(QPushButton('Use bid', clicked=self._bid)); r.addWidget(QPushButton('Use ask', clicked=self._ask)); r.addWidget(QPushButton('10 USDT', clicked=self._q10)); r.addWidget(QPushButton('Max EURI', clicked=self._qmax)); l.addRow(r)
        a=QHBoxLayout(); a.addWidget(QPushButton('BUY LIMIT', clicked=lambda: self._submit('BUY'))); a.addWidget(QPushButton('SELL LIMIT', clicked=lambda: self._submit('SELL'))); l.addRow(a)
        self.sync_market()
    def sync_market(self): self.bid.setText(self.main._market_bid()); self.ask.setText(self.main._market_ask())
    def _calc(self):
        try: self.total.setText(f"{(Decimal(self.price.text())*Decimal(self.qty.text())):.8f}")
        except Exception: self.total.setText('0.00000000')
    def _bid(self): self.price.setText(self.main._market_bid())
    def _ask(self): self.price.setText(self.main._market_ask())
    def _q10(self):
        p=Decimal(self.price.text() or self.main._market_ask() or '0')
        self.qty.setText(f"{(Decimal('10')/p):.8f}" if p>0 else '0')
    def _qmax(self): self.qty.setText(self.main._balance_euri())
    def _submit(self, side): self.main.place(side, self.price.text(), self.qty.text())

class AllDataDialog(QDialog):
    def __init__(self, main, parent=None):
        super().__init__(parent); self.setWindowTitle('All Data Diagnostics'); l=QVBoxLayout(self)
        tabs = QTabWidget(self)
        for g in ['Account', 'Market', 'Runtime', 'Orders', 'Filters', 'Execution']:
            tab = QWidget()
            tab_l = QVBoxLayout(tab)
            view = QTextEdit()
            view.setReadOnly(True)
            view.setText(main._all_data_text(g))
            tab_l.addWidget(view)
            tabs.addTab(tab, g)
        l.addWidget(tabs)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('EUT v0.3.9 — Operator Terminal'); self.setMinimumSize(1280,760); self.setStyleSheet(DARK_STYLESHEET); self.setFont(QFont('', APP_FONT_PT))
        self.logger=AppLogger(max_records=500,dedupe_seconds=30); self.cfg=load_config(); self.runtime=RuntimeState(); self.ws=WSManager(enabled=True)
        self._last_market_snapshot={}; self._last_open_orders=[]; self._balances={}; self._status_badges={}; self._orders_by_id={}; self._selected_order_id=None; self._exchange_filters={}
        self._pair_config = get_pair_config(self.cfg.get('symbol', 'EURIUSDT'))
        self._spread_analyzer=SpreadStabilityAnalyzer(); self._queue_estimator=QueueQualityEstimator(); self._harvest_engine=HarvestReadinessEngine(); self._private_ok=False
        self._spread_engine=SpreadStabilityEngine(Decimal('0.0001'), int(self.cfg.get('min_spread_ticks',2)), int(self.cfg.get('min_stable_ms',3000)), stay_ready_ticks=int(self.cfg.get('min_spread_ticks',2)), ready_hysteresis_ms=int(self.cfg.get('ready_drop_debounce_ms',4000)))
        self._spread_metrics=None; self._last_spread_readiness=None
        self._fill_observer=self._build_fill_observer()
        self._cycle=HarvestCycle()
        self._active_buy_order_id=None; self._active_sell_order_id=None
        self._pending_buy_grace_until=0.0; self._pending_buy_order=None
        self._pending_sell_grace_until=0.0; self._pending_sell_order=None
        self._order_visibility_grace_sec=3.0
        self._last_reprice_at=0.0
        max_reprice_per_sec = float(self.cfg.get('max_reprice_per_sec', 0) or 0)
        self._reprice_throttle_sec=(1.0 / max_reprice_per_sec) if max_reprice_per_sec > 0 else self._pair_config.top_check_interval_sec
        self._fill_observation=None; self._last_fill_possible=None; self._last_slow_market=None
        self._live_running=False; self._live_confirmed=False; self._buy_started_at=0.0; self._sell_started_at=0.0; self._last_wait_log_at=0.0; self._cycle_started_at=time.time(); self._last_fill_time='-'
        self._log_throttle_until={}; self._runtime_label_cache={}; self._runtime_label_last_update=0.0
        self._ui_model = {}
        self._stale_label_warn_until = {}
        self._inventory_state='UNKNOWN'; self._inventory_color='#9e9e9e'; self._last_inventory_log_signature=None
        self._orders_live_last_refresh=0.0; self._balance_live_last_refresh=0.0; self._orders_live_interval_sec=1.0; self._balance_live_interval_sec=1.0
        self._orders_gui_last_sync=0.0; self._orders_gui_interval_sec=1.0
        self._sell_capacity_signature=None; self._buy_top_state='UNKNOWN'; self._sell_top_state='UNKNOWN'
        self._quote_birth: dict[int, float] = {}
        self._data_mode = 'REST'
        self._last_data_mode = None
        self._last_market_ts = 0.0
        self._last_market_source = 'NONE'
        self._session_started_at = time.time()
        self._last_live_tick_log_at = 0.0
        self._trade_ledger = TradeLedger()
        self._trade_stats = {}
        self._init_services(); self._build_ui(); self._refresh_trade_stats_from_ledger(); self._sync_trade_settings_labels()
        self.task_runner=TaskRunner(4,self); self.task_runner.signals.success.connect(self._on_task_success); self.task_runner.signals.error.connect(self._on_task_error); self.task_runner.signals.finished.connect(self.task_runner.finish)
        self.polling=PollingManager(self.refresh_market,self.refresh_orders,self.refresh_balances,300,500,3000,self)
        self._status_timer=QTimer(self); self._status_timer.timeout.connect(self._tick_status); self._status_timer.start(300); QTimer.singleShot(50,self._startup_connect_flow)
        self.live_timer = QTimer(self); self.live_timer.timeout.connect(self._live_tick)


    @property
    def _runtime_active(self):
        return self._live_running

    @_runtime_active.setter
    def _runtime_active(self, value):
        self._live_running = bool(value)

    @property
    def _harvest_running(self):
        return self._live_running

    @_harvest_running.setter
    def _harvest_running(self, value):
        self._live_running = bool(value)
    def _init_services(self):
        self.client=BinanceClient(self.cfg['api_key'],self.cfg['api_secret'],self.cfg['testnet'],self.cfg.get('request_timeout_sec',3)); self.market=MarketService(self.client,self.cfg['symbol']); self.account=AccountService(self.client, self._pair_config.base_asset, self._pair_config.quote_asset); self.orders=OrderService(self.client,self.cfg['symbol'])
    def _build_ui(self):
        root=QWidget(); self.setCentralWidget(root); main=QVBoxLayout(root); top=QGroupBox('Status Strip'); l=QHBoxLayout(top)
        for k in ['CONNECTED','DATA','FILTERS','BALANCE','MARKET','FILL','SPREAD','LIVE','CYCLE','ORDER','RISK']:
            b=QLabel(f'{k} -'); self._status_badges[k]=b; l.addWidget(b)
        self._status_balance_euri=QLabel('BASE - / locked -'); l.addWidget(self._status_balance_euri)
        self._status_balance_usdt=QLabel('QUOTE - / locked -'); l.addWidget(self._status_balance_usdt)
        main.addWidget(top)
        split=QSplitter(Qt.Horizontal)
        left=QGroupBox('Trade / Harvest Settings'); fl=QFormLayout(left); self.ts_symbol=QLabel(); self.ts_mode=QLabel('LIVE TRADE'); self.ts_pair_profile=QLabel('-'); self.ts_buy_exp=QLabel(); self.ts_sell_exp=QLabel(); self.ts_min=QLabel(); self.ts_profit=QLabel(); self.ts_stable=QLabel(); self.ts_partial=QLabel(); self.ts_min_partial=QLabel(); self.ts_reprice=QLabel(); self.ts_collapse=QLabel(); self.ts_cycle_age=QLabel(); self.ts_risk=QLabel()
        self.pair_selector = QComboBox(); self.pair_selector.addItems(list_pairs()); self.pair_selector.currentTextChanged.connect(self._on_pair_selected)
        for n,w in [('PAIR',self.pair_selector),('Mode',self.ts_mode),('Symbol',self.ts_symbol),('Pair profile',self.ts_pair_profile),('Max BUY exposure USDT',self.ts_buy_exp),('Max SELL exposure USDT',self.ts_sell_exp),('Min spread ticks',self.ts_min),('Target profit ticks',self.ts_profit),('Min stable ms',self.ts_stable),('Allow partial fills',self.ts_partial),('Min partial fill EURI',self.ts_min_partial),('Reprice on bid/ask move',self.ts_reprice),('Cancel on spread collapse',self.ts_collapse),('Risk guard',self.ts_risk)]: fl.addRow(n,w)
        self.start_button = QPushButton('HARVEST OFF')
        self.start_button.setCheckable(True)
        self.start_button.toggled.connect(self.toggle_harvest)
        self.stop_button = self.start_button
        self.edit_settings_button = self._btn('Edit Settings', self.open_trade_settings)
        fl.addRow(self.start_button); fl.addRow(self.edit_settings_button)
        cycle=QGroupBox('Runtime / Stats'); cf=QFormLayout(cycle); self.cs_state=QLabel(); self.cs_target=QLabel(); self.cs_bought=QLabel(); self.cs_sold=QLabel(); self.cs_open=QLabel(); self.cs_avg_buy=QLabel(); self.cs_avg_sell=QLabel(); self.cs_pnl=QLabel(); self.cs_order=QLabel(); self.cs_reason=QLabel(); self.cs_buy_working=QLabel(); self.cs_sell_working=QLabel(); self.cs_buy_remaining=QLabel(); self.cs_sell_remaining=QLabel(); self.cs_cycle_age=QLabel(); self.cs_last_fill=QLabel('-'); self.cs_buy_order_id=QLabel('-'); self.cs_sell_order_id=QLabel('-'); self.cs_buy_status=QLabel('-'); self.cs_sell_status=QLabel('-'); self.cs_top_bid_status=QLabel('-'); self.cs_top_ask_status=QLabel('-'); self.cs_buy_age=QLabel('-'); self.cs_sell_age=QLabel('-'); self.cs_avail_sell_qty=QLabel('-'); self.cs_pending_sell_qty=QLabel('-'); self.cs_avail_buy_usdt=QLabel('-'); self.cs_inv_exposure=QLabel('-'); self.ss_readiness=QLabel('NOT_READY')
        self.cs_inv_portfolio=QLabel('-'); self.cs_inv_base_value=QLabel('-'); self.cs_inv_quote_value=QLabel('-'); self.cs_inv_ratio=QLabel('-'); self.cs_inv_drift=QLabel('-')
        self.cs_trades=QLabel('0'); self.cs_winrate=QLabel('0.0%'); self.cs_data_source=QLabel('REST'); self.cs_open_orders=QLabel('0')
        for n,w in [('ENGINE',self.cs_state),('DATA SOURCE',self.cs_data_source),('BUY STATE',self.cs_buy_status),('BUY TOP',self.cs_top_bid_status),('SELL STATE',self.cs_sell_status),('SELL TOP',self.cs_top_ask_status),('Inventory Drift',self.cs_inv_drift),('PnL',self.cs_pnl),('Trades',self.cs_trades),('Winrate',self.cs_winrate),('Open Orders',self.cs_open_orders),('Last Fill',self.cs_last_fill)]: cf.addRow(n,w)
        stats_box=QGroupBox('Trade Stats'); sf=QFormLayout(stats_box)
        self.ts_total=QLabel('0'); self.ts_buy_fills=QLabel('0'); self.ts_sell_fills=QLabel('0'); self.ts_cycles=QLabel('0'); self.ts_winrate=QLabel('0.0%'); self.ts_realized=QLabel('0.00000000'); self.ts_avg=QLabel('0.00000000'); self.ts_ticks=QLabel('0.00'); self.ts_fees=QLabel('0.00000000'); self.ts_runtime=QLabel('0s')
        self.ts_bought_qty=QLabel('0.00000000'); self.ts_bought_quote=QLabel('0.00000000'); self.ts_sold_qty=QLabel('0.00000000'); self.ts_sold_quote=QLabel('0.00000000'); self.ts_matched_sold_qty=QLabel('0.00000000')
        self.ts_inventory_qty=QLabel('0.00000000'); self.ts_inventory_quote=QLabel('0.00000000'); self.ts_open_position_qty=QLabel('0.00000000'); self.ts_avg_buy_price=QLabel('0.00000000'); self.ts_avg_sell_price=QLabel('0.00000000')
        for n,w in [('Trades total',self.ts_total),('BUY fills',self.ts_buy_fills),('SELL fills',self.ts_sell_fills),('Bought qty',self.ts_bought_qty),('Bought quote',self.ts_bought_quote),('Sold qty',self.ts_sold_qty),('Sold quote',self.ts_sold_quote),('Matched sold qty',self.ts_matched_sold_qty),('Inventory sold qty',self.ts_inventory_qty),('Inventory sold quote',self.ts_inventory_quote),('Open position qty',self.ts_open_position_qty),('Avg buy',self.ts_avg_buy_price),('Avg sell',self.ts_avg_sell_price),('Completed cycles',self.ts_cycles),('Winrate %',self.ts_winrate),('Realized PnL',self.ts_realized),('Avg profit / trade',self.ts_avg),('Spread captured ticks',self.ts_ticks),('Fees',self.ts_fees),('Session runtime',self.ts_runtime)]: sf.addRow(n,w)
        center=QGroupBox('Open Orders'); cl=QVBoxLayout(center); self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['side','price','qty','filled','remain','age','top-status']); self.table.itemSelectionChanged.connect(self._on_order_selected); self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); cl.addWidget(self.table); self.no_orders=QLabel('No open orders'); cl.addWidget(self.no_orders)
        spread_box=QGroupBox('Spread Stability'); sl=QFormLayout(spread_box)
        self.ss_ticks=QLabel('-'); self.ss_lifetime=QLabel('-'); self.ss_bid=QLabel('-'); self.ss_ask=QLabel('-'); self.ss_ratio=QLabel('-'); self.ss_collapse=QLabel('0')
        for n,w in [('Spread ticks',self.ss_ticks),('Spread lifetime',self.ss_lifetime),('Bid stable',self.ss_bid),('Ask stable',self.ss_ask),('Stable ratio',self.ss_ratio),('Collapse count',self.ss_collapse),('Readiness',self.ss_readiness)]: sl.addRow(n,w)
        self.fo_bid=QLabel('-'); self.fo_ask=QLabel('-'); self.fo_window=QLabel('-'); self.fo_activity=QLabel('-'); self.fo_possible=QLabel('NO')
        for n,w in [('Fill: bid lifetime',self.fo_bid),('Fill: ask lifetime',self.fo_ask),('Fill: window',self.fo_window),('Fill: market activity',self.fo_activity),('Fill: possible',self.fo_possible)]: sl.addRow(n,w)
        right=QGroupBox('Actions'); rl=QVBoxLayout(right)
        self.manual_order_button = self._btn('Manual Order', self.open_manual_order)
        self.cancel_selected_button = self._btn('Cancel Selected', self.cancel_selected)
        self.cancel_all_button = self._btn('Cancel All', self.cancel_all)
        self.all_data_button = self._btn('All Data', self.open_all_data)
        self.settings_button = self._btn('Settings', self.open_settings)
        for button in [self.manual_order_button, self.cancel_selected_button, self.cancel_all_button, self.all_data_button, self.settings_button]:
            rl.addWidget(button)
        self.start_harvest_btn=self.start_button; self.stop_harvest_btn=self.stop_button; self.cancel_selected_btn=self.cancel_selected_button; self.cancel_all_btn=self.cancel_all_button
        self.manual_order_btn=self.manual_order_button; self.all_data_btn=self.all_data_button; self.settings_btn=self.settings_button
        self.start_harvest_btn.setObjectName('btn_start'); self.stop_harvest_btn.setObjectName('btn_stop'); self.cancel_selected_btn.setObjectName('btn_cancel')
        self.cancel_all_btn.setObjectName('btn_cancel'); self.all_data_btn.setObjectName('btn_info'); self.settings_btn.setObjectName('btn_info')
        self.setStyleSheet(self.styleSheet() + """
QPushButton#btn_start { background: #1e7f3e; border-color: #2fa85a; }
QPushButton#btn_start:hover { background: #24964a; }
QPushButton#btn_start:pressed { background: #166730; }
QPushButton#btn_stop { background: #aa2e25; border-color: #d44b3f; }
QPushButton#btn_stop:hover { background: #c6372c; }
QPushButton#btn_stop:pressed { background: #8a261f; }
QPushButton#btn_cancel { background: #9a5a12; border-color: #c87816; }
QPushButton#btn_cancel:hover { background: #b56a13; }
QPushButton#btn_cancel:pressed { background: #7e4a0f; }
QPushButton#btn_info { background: #1f5fb8; border-color: #2e7ce5; }
QPushButton#btn_info:hover { background: #2a71d5; }
QPushButton#btn_info:pressed { background: #184f9a; }
""")
        split.addWidget(left); split.addWidget(center); split.addWidget(cycle); split.addWidget(right); split.setStretchFactor(1, 3); main.addWidget(split)
        logs=QGroupBox('Logs'); ll=QVBoxLayout(logs); self.log_panel=LogPanel(1000); self.logger.subscribe(self.log_panel.append_record); ll.addWidget(self.log_panel); main.addWidget(logs)
        self.logger.log('INFO', '[GUI] action wired HARVEST_TOGGLE')
        self.logger.log('INFO', '[GUI] action wired MANUAL')
        self.logger.log('INFO', '[GUI] action wired CANCEL_SELECTED')
        self.logger.log('INFO', '[GUI] action wired CANCEL_ALL')
        self.logger.log('INFO', '[GUI] action wired ALL_DATA')
        self.logger.log('INFO', '[GUI] action wired SETTINGS')
        self.logger.log('INFO', '[GUI] action wired EDIT_SETTINGS')

    def closeEvent(self, event):
        self._live_running = False
        if hasattr(self, 'live_timer') and self.live_timer:
            self.live_timer.stop()
        if hasattr(self, '_status_timer') and self._status_timer:
            self._status_timer.stop()
        if hasattr(self, 'polling') and self.polling:
            try:
                self.polling.stop()
            except Exception:
                pass
        try:
            self.task_runner.signals.success.disconnect(self._on_task_success)
            self.task_runner.signals.error.disconnect(self._on_task_error)
            self.task_runner.signals.finished.disconnect(self.task_runner.finish)
        except Exception:
            pass
        super().closeEvent(event)

    def _btn(self,t,f): b=QPushButton(t); b.clicked.connect(f); return b
    def _startup_connect_flow(self):
        self._bootstrap_sequence()

    def _bootstrap_sequence(self):
        self.logger.log('INFO', '[BOOT] start')
        steps = (
            ('load filters', self._load_exchange_filters),
            ('market snapshot', self._bootstrap_market_snapshot),
            ('balances refresh', self._bootstrap_balances_refresh),
            ('open orders refresh', self._bootstrap_open_orders_refresh),
            ('polling start', self.start_polling),
        )
        for step_name, step_fn in steps:
            self.logger.log('INFO', f'[BOOT] {step_name}')
            try:
                result = step_fn()
                if result is False:
                    raise RuntimeError('returned False')
            except Exception as exc:
                self._private_ok = False
                self.logger.log('ERROR', f'[BOOT] failed step={step_name} error={exc}')
                if step_name == 'balances refresh':
                    self.logger.log('ERROR', f'[ERROR] account endpoint failed: {exc}')
                return
        self.logger.log('INFO', '[WS] connecting')
        self.ws.connect()
        self.logger.log('INFO', '[BOOT] ready')

    def _bootstrap_market_snapshot(self):
        self._on_task_success('market', self.market.snapshot())

    def _bootstrap_balances_refresh(self):
        try:
            payload = self.account.balances(Decimal(str(self._last_market_snapshot.get('last', 0) or 0)))
        except Exception as exc:
            if isinstance(exc, BinanceAPIError) and exc.status_code in (401, 403):
                self.logger.log('ERROR', f'[ERROR] account endpoint failed: HTTP {exc.status_code} {exc}')
            raise
        self._on_task_success('balances', payload)

    def _bootstrap_open_orders_refresh(self):
        self._on_task_success('orders', self.orders.open_orders())
    def open_settings(self):
        try:
            self.settings_dialog=SettingsDialog(self.cfg,self.apply_settings,self.test_connection,self); self.settings_dialog.show()
        except Exception as e:
            self.logger.log('ERROR', f'[ERROR] GUI action failed action=SETTINGS error={e}')
    def open_trade_settings(self):
        try:
            self.trade_settings_dialog=TradeSettingsDialog(self.cfg,self.apply_trade_settings,self); self.trade_settings_dialog.show()
        except Exception as e:
            self.logger.log('ERROR', f'[ERROR] GUI action failed action=EDIT_SETTINGS error={e}')
    def open_manual_order(self):
        try:
            self.manual_order_dialog=ManualOrderDialog(self,self); self.manual_order_dialog.show()
        except Exception as e:
            self.logger.log('ERROR', f'[ERROR] GUI action failed action=MANUAL error={e}')
    def open_all_data(self):
        try:
            self.logger.log('INFO', '[GUI] All Data clicked')
            self.all_data_dialog=AllDataDialog(self,self); self.all_data_dialog.show()
            self.logger.log('INFO', '[GUI] All Data opened')
        except Exception as e:
            self.logger.log('ERROR', f'[ERROR] All Data failed: {e}')

    def show_all_data(self):
        self.open_all_data()
    def apply_settings(self,v): self.cfg.update(v); save_config(self.cfg)
    def _build_fill_observer(self):
        fill_window_ms = int(self.cfg.get('fill_window_ms', self.cfg.get('min_stable_ms', 3000)))
        block_high_activity = bool(self.cfg.get('fill_block_high_activity', False))
        return FillObserver(int(self.cfg.get('min_spread_ticks',2)), int(self.cfg.get('min_stable_ms',3000)), symbol=str(self.cfg.get('symbol', 'EURIUSDT')), fill_window_ms=fill_window_ms, block_high_activity=block_high_activity)
    def apply_trade_settings(self,v): self.cfg.update(v); save_config(self.cfg); self._sync_trade_settings_labels(); self._fill_observer=self._build_fill_observer()
    def _on_pair_selected(self, symbol: str):
        if not symbol or symbol == self.cfg.get('symbol'):
            return
        self._switch_pair(symbol)
    def _switch_pair(self, symbol: str):
        prev_symbol = self.cfg.get('symbol', 'EURIUSDT')
        self.logger.log('INFO', f'[PAIR] switching {prev_symbol} -> {symbol}')
        self._live_running = False
        self._cycle = HarvestCycle()
        self._active_buy_order_id = None; self._active_sell_order_id = None
        self._pending_buy_order = None; self._pending_sell_order = None
        self._pending_buy_grace_until = 0.0; self._pending_sell_grace_until = 0.0
        self._orders_by_id = {}
        self._last_open_orders = []
        self._exchange_filters = {}
        self.cfg['symbol'] = symbol
        self._pair_config = get_pair_config(symbol)
        self.cfg['min_stable_ms'] = self._pair_config.default_stable_ms
        self.cfg['min_spread_ticks'] = self._pair_config.default_spread_ticks
        self.cfg['reprice_on_move'] = self._pair_config.aggressive_reprice
        if symbol == 'BTCU':
            self.cfg['min_stable_ms'] = 500
            self.cfg['fill_window_ms'] = 300
            self.cfg['fill_block_high_activity'] = False
        self.market.set_symbol(symbol); self.orders.set_symbol(symbol); self.account.set_assets(self._pair_config.base_asset, self._pair_config.quote_asset)
        max_reprice_per_sec = float(self.cfg.get('max_reprice_per_sec', 0) or 0)
        self._reprice_throttle_sec = (1.0 / max_reprice_per_sec) if max_reprice_per_sec > 0 else self._pair_config.top_check_interval_sec
        self._orders_live_interval_sec = self._pair_config.quote_refresh_interval_sec
        self._fill_observer = self._build_fill_observer()
        self.logger.log('INFO', f"[PAIR] profile {self._pair_config.profile}")
        self._load_exchange_filters()
        self.logger.log('INFO', f'[FILTERS] reloaded {symbol}')
        self.refresh_balances(True); self.refresh_orders(True); self.refresh_market(True)
        self._sync_trade_settings_labels()
        save_config(self.cfg)
        self.logger.log('INFO', '[RUNTIME] symbol state reset complete')
    def test_connection(self,v): return True,'ok'
    def refresh_market(self,force=False): self.task_runner.run_task('market', lambda: self.market.snapshot())
    def refresh_balances(self,force=False): self.task_runner.run_task('balances', lambda: self.account.balances(Decimal(str(self._last_market_snapshot.get('last',0) or 0))))
    def refresh_orders(self,force=False): self.task_runner.run_task('orders', self.orders.open_orders)
    def _should_log(self, key: str, cooldown_sec: float = 45.0) -> bool:
        now = time.time()
        if now < self._log_throttle_until.get(key, 0.0):
            return False
        self._log_throttle_until[key] = now + cooldown_sec
        return True

    def _log_throttled(self, key: str, message: str, cooldown_sec: float = 45.0):
        if self._should_log(key, cooldown_sec):
            self.logger.log('INFO', message)

    def _refresh_orders_live(self, reason: str = 'runtime', force: bool = False):
        now = time.time()
        if not force and (now - self._orders_live_last_refresh) < self._orders_live_interval_sec:
            return self._last_open_orders
        orders = self.orders.open_orders()
        self._orders_live_last_refresh = now
        self._log_throttled('orders_live_refresh', f'[ORDERS] live refresh count={len(orders)} reason={reason}', 30.0)
        self._sync_open_orders(orders)
        return orders

    def _refresh_balances_live(self, reason: str = 'runtime', force: bool = False):
        now = time.time()
        if not force and (now - self._balance_live_last_refresh) < self._balance_live_interval_sec:
            return self._balances
        balances = self.account.balances(Decimal(str(self._last_market_snapshot.get('last',0) or 0)))
        prev = self._balances
        self._balances = balances
        self._balance_live_last_refresh = now
        self._private_ok = True
        euri_delta = abs(Decimal(str(balances.get('BASE_free', 0))) - Decimal(str(prev.get('BASE_free', 0)))) if prev else Decimal('0')
        if euri_delta > Decimal('0.0001'):
            self.logger.log('INFO', f"[BALANCE] changed reason={reason} {self._pair_config.base_asset}_free={balances.get('BASE_free', 0)}")
        else:
            self._log_throttled('balance_live_refresh', f"[BALANCE] live refresh reason={reason} {self._pair_config.base_asset}_free={balances.get('BASE_free', 0)}", 45.0)
        return balances


    def _is_would_take_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        code = getattr(exc, 'code', None)
        return code == -2010 or 'would immediately match and take' in text

    def _fresh_market_bid_ask(self) -> tuple[Decimal, Decimal]:
        market = dict(self._last_market_snapshot or {})
        ws_fresh = self._last_market_source == 'WS' and self.ws.status.state == 'OK' and (time.time() - self._last_market_ts) <= 1.5
        if (not ws_fresh) or Decimal(str(market.get('bid', 0) or 0)) <= 0 or Decimal(str(market.get('ask', 0) or 0)) <= 0:
            market = self.market.snapshot()
            market['source'] = 'REST'
            self._on_task_success('market', market)
        bid = Decimal(str(market.get('bid', 0) or 0))
        ask = Decimal(str(market.get('ask', 0) or 0))
        return bid, ask

    def _safe_maker_buy_price(self, bid: Decimal, ask: Decimal, tick: Decimal) -> Decimal:
        price = floor_to_tick(bid, tick)
        if price >= ask and tick > 0:
            price = floor_to_tick(ask - tick, tick)
        return price

    def _safe_maker_sell_price(self, target_tp_price: Decimal, bid: Decimal, ask: Decimal, tick: Decimal) -> Decimal:
        maker_sell_price = max(target_tp_price, ask)
        if maker_sell_price <= bid and tick > 0:
            maker_sell_price = bid + tick
        sell_price = floor_to_tick(maker_sell_price, tick)
        if sell_price <= bid and tick > 0:
            sell_price = floor_to_tick(bid + tick, tick)
        return sell_price

    def _place_safe_maker_buy(self, qty: Decimal, reason: str = ''):
        step, tick, _ = self._current_filters()
        qty_n = floor_to_step(qty, step)
        if qty_n <= 0:
            return None
        bid_fresh, ask_fresh = self._fresh_market_bid_ask()
        price = self._safe_maker_buy_price(bid_fresh, ask_fresh, tick)
        qty_s = format_decimal_for_step(qty_n, step)
        price_s = format_decimal_for_tick(price, tick)
        if Decimal(price_s) >= ask_fresh and tick > 0:
            price_s = format_decimal_for_tick(ask_fresh - tick, tick)
        try:
            return self.orders.place_limit_maker('BUY', qty_s, price_s)
        except Exception as e:
            if self._is_would_take_error(e):
                self.logger.log('INFO', f'[BUY] maker rejected would_take price={price_s} bid={bid_fresh} ask={ask_fresh} reason={reason}')
                bid_retry, ask_retry = self._fresh_market_bid_ask()
                retry_price = self._safe_maker_buy_price(bid_retry, ask_retry, tick)
                retry_s = format_decimal_for_tick(retry_price, tick)
                if Decimal(retry_s) >= ask_retry and tick > 0:
                    retry_s = format_decimal_for_tick(ask_retry - tick, tick)
                try:
                    return self.orders.place_limit_maker('BUY', qty_s, retry_s)
                except Exception as e2:
                    if self._is_would_take_error(e2):
                        self.logger.log('INFO', '[BUY] maker rejected would_take skip')
                        return None
                    raise
            raise

    def _place_safe_maker_sell(self, qty: Decimal, target_price: Decimal, reason: str = ''):
        step, tick, _ = self._current_filters()
        qty_n = floor_to_step(qty, step)
        if qty_n <= 0:
            return None
        fresh_bid, fresh_ask = self._fresh_market_bid_ask()
        safe_price = self._safe_maker_sell_price(target_price, fresh_bid, fresh_ask, tick)
        price = format_decimal_for_tick(safe_price, tick)
        if Decimal(price) <= fresh_bid and tick > 0:
            price = format_decimal_for_tick(fresh_bid + tick, tick)
        qty_s = format_decimal_for_step(qty_n, step)
        try:
            return self.orders.place_limit_maker('SELL', qty_s, price)
        except Exception as e:
            if self._is_would_take_error(e):
                fresh_bid, fresh_ask = self._fresh_market_bid_ask()
                safe_price = self._safe_maker_sell_price(target_price, fresh_bid, fresh_ask, tick)
                retry_price = format_decimal_for_tick(safe_price, tick)
                if Decimal(retry_price) <= fresh_bid and tick > 0:
                    retry_price = format_decimal_for_tick(fresh_bid + tick, tick)
                try:
                    return self.orders.place_limit_maker('SELL', qty_s, retry_price)
                except Exception as e2:
                    if self._is_would_take_error(e2):
                        self.logger.log('INFO', '[SELL] maker rejected would_take skip')
                        return None
                    raise
            raise

    def _cleanup_duplicate_side_orders(self) -> bool:
        changed = False
        side_map: dict[str, list[dict]] = {'BUY': [], 'SELL': []}
        for order in self._last_open_orders:
            side = str(order.get('side', '')).upper()
            if side in side_map and order.get('orderId'):
                side_map[side].append(order)
        for side, orders in side_map.items():
            if len(orders) <= 1:
                continue
            keep, *duplicates = sorted(orders, key=lambda o: int(o.get('updateTime') or o.get('time') or 0), reverse=True)
            for duplicate in duplicates:
                duplicate_id = int(duplicate.get('orderId'))
                try:
                    self.orders.cancel(duplicate_id)
                    self.logger.log('INFO', f'[ORDERS] duplicate {side} canceled id={duplicate_id}')
                    changed = True
                except Exception as e:
                    self.logger.log('INFO', f'[ORDERS] duplicate {side} cancel failed id={duplicate_id} err={e}')
            keep_id = int(keep.get('orderId'))
            if side == 'BUY':
                self._active_buy_order_id = keep_id
            else:
                self._active_sell_order_id = keep_id
        if changed:
            self._refresh_orders_live('duplicate_cleanup', force=True)
        return changed

    def _on_task_success(self,name,payload):
        if not isValid(self):
            return
        if name=='market':
            market = dict(payload or {})
            bid = Decimal(str(market.get('bid', 0) or 0))
            ask = Decimal(str(market.get('ask', 0) or 0))
            valid_market = bid > 0 and ask > 0 and ask > bid
            if valid_market:
                self._last_market_snapshot = market
                self._last_market_ts = time.time()
                source = str(market.get('source', '')).upper()
                self._last_market_source = source if source in ('WS', 'REST') else ('WS' if self.ws.status.state == 'OK' else 'REST')
                if self._last_market_source == 'WS':
                    if self.ws.status.state != 'OK':
                        self.ws.mark_ok()
                        self.logger.log('INFO', '[WS] subscribed')
                        self.logger.log('INFO', '[WS] first tick')
                    else:
                        self.logger.log('INFO', '[WS] heartbeat ok')
            metrics=self._spread_engine.observe(bid, ask, float(market.get('latency_ms',0)))
            self._spread_metrics=metrics
            tick = Decimal(str(self._exchange_filters.get('tickSize', '0.0001') or '0.0001'))
            spread_raw = ask - bid if ask > bid else Decimal('0')
            spread_ticks = self._compute_spread_ticks(bid, ask)
            self._log_throttled('market_snapshot', f"[MARKET] symbol={self.cfg.get('symbol','EURIUSDT')} bid={bid} ask={ask} tickSize={tick} spread_raw={spread_raw} spread_ticks={spread_ticks}", 5.0)
            self._set_label_text(self.ss_ticks, f"raw={metrics.snapshot.spread:.8f} | ticks={int(spread_ticks)}")
            self._set_label_text(self.ss_lifetime, f"{metrics.state.spread_lifetime_ms}ms")
            self._set_label_text(self.ss_bid, f"{metrics.state.best_bid_unchanged_ms}ms")
            self._set_label_text(self.ss_ask, f"{metrics.state.best_ask_unchanged_ms}ms")
            self._set_label_text(self.ss_ratio, f"{metrics.state.stable_spread_ratio*100:.0f}%")
            self._set_label_text(self.ss_collapse, str(metrics.state.spread_collapse_count))
            self._set_label_text(self.ss_readiness, metrics.state.readiness.value)
            self._fill_observation=self._fill_observer.observe(
                Decimal(str(payload.get('bid',0))),
                Decimal(str(payload.get('ask',0))),
                metrics.snapshot.spread_ticks,
                metrics.state.spread_lifetime_ms,
            )
            self._set_label_text(self.fo_bid, f"{self._fill_observation.bid_lifetime_ms}ms")
            self._set_label_text(self.fo_ask, f"{self._fill_observation.ask_lifetime_ms}ms")
            self._set_label_text(self.fo_window, f"{self._fill_observation.fill_window_estimate_ms}ms")
            self._set_label_text(self.fo_activity, self._fill_observation.market_activity.value)
            self._set_label_text(self.fo_possible, 'YES' if self._fill_observation.fill_possible else 'NO')
            slow_market = self._fill_observation.market_activity == MarketActivity.LOW
            if self._fill_observation.fill_possible != self._last_fill_possible:
                if self._fill_observation.fill_possible:
                    self.logger.log('INFO', '[FILL] POSSIBLE')
                else:
                    self.logger.log('INFO', self._fill_not_possible_diag())
                self._last_fill_possible = self._fill_observation.fill_possible
            if slow_market != self._last_slow_market:
                self.logger.log('INFO', f"[FILL] slow_market={'YES' if slow_market else 'NO'}")
                self._last_slow_market = slow_market
            if metrics.state.readiness != self._last_spread_readiness:
                self.logger.log('INFO', f"[SPREAD] {metrics.state.readiness.value} ticks={int(spread_ticks)} lifetime={metrics.state.spread_lifetime_ms}ms")
                self._last_spread_readiness=metrics.state.readiness
            if self._cycle.state == CycleState.IDLE:
                old, new = self._cycle.transition(CycleState.WAIT_READY, 'boot')
                self.logger.log('FSM', f'{old.value} -> {new.value} reason=boot')
            if metrics.state.spread_collapse_count > 0 and metrics.state.readiness == ReadinessState.NOT_READY:
                self.logger.log('INFO', '[SPREAD] COLLAPSE')
        elif name=='balances':
            self._balances=payload; self._private_ok=True
            self._update_status_strip()
        elif name=='orders': self._sync_open_orders(payload)
    def _on_task_error(self,name,err):
        self.logger.log('ERROR', f'{name}: {err}');
        if name in ('orders','balances'): self._private_ok=False
    def _sync_open_orders(self, payload):
        prev_count = len(self._last_open_orders)
        self._last_open_orders = payload
        now = time.time()
        must_render = (now - self._orders_gui_last_sync) >= self._orders_gui_interval_sec or len(payload) != prev_count
        if must_render:
            self._render_orders(payload)
            self._orders_gui_last_sync = now
        if len(payload) != prev_count:
            self.logger.log('INFO', f'[ORDERS] count changed {prev_count}->{len(payload)}')
        open_ids={int(o.get('orderId')) for o in payload if o.get('orderId')}
        if self._active_buy_order_id and self._active_buy_order_id not in open_ids:
            self.logger.log('INFO', f'[RUNTIME] active BUY resolved id={self._active_buy_order_id}')
            self._quote_birth.pop(self._active_buy_order_id, None)
            self._active_buy_order_id=None
        if self._active_sell_order_id and self._active_sell_order_id not in open_ids and now >= self._pending_sell_grace_until:
            self.logger.log('INFO', f'[RUNTIME] active SELL resolved id={self._active_sell_order_id}')
            self._quote_birth.pop(self._active_sell_order_id, None)
            self._active_sell_order_id=None
            self._pending_sell_order=None
    def has_active_buy(self) -> bool: return self._active_buy_order_id is not None
    def has_active_sell(self) -> bool: return self._active_sell_order_id is not None

    def _render_orders(self,payload):
        rows = list(payload)
        self._orders_by_id={int(o.get('orderId')):o for o in rows if o.get('orderId')}; self.table.setRowCount(len(rows)); self.no_orders.setVisible(len(rows)==0)
        for r,o in enumerate(rows):
            orig = Decimal(str(o.get('origQty', '0') or '0')); exe = Decimal(str(o.get('executedQty', '0') or '0')); rem = max(Decimal('0'), orig-exe)
            ts = int(o.get('updateTime') or o.get('time') or 0); age_ms = str(max(0, int(time.time() * 1000) - ts)) if ts > 0 else '-'
            side = str(o.get('side', '-'))
            bid_top = self._safe_label_text(self.cs_top_bid_status, '-')
            ask_top = self._safe_label_text(self.cs_top_ask_status, '-')
            top_status = 'TOP' if ((side == 'BUY' and bid_top == 'TOP') or (side == 'SELL' and ask_top == 'TOP')) else ('WATCH' if str(o.get('status', '')).upper() in ('NEW', 'PARTIALLY_FILLED') else 'IDLE')
            vals=[side,f"{Decimal(str(o.get('price', '0') or '0')):.8f}",f"{orig:.8f}",f"{exe:.8f}",f"{rem:.8f}",age_ms,top_status]
            for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))

    def _on_buy_fill(self, qty: Decimal, price: Decimal):
        event = self._trade_ledger.record_buy(qty, price, fee=Decimal('0'), timestamp=time.time())
        self.logger.log('INFO', f'[LEDGER] BUY qty={qty:.8f} price={price:.8f} quote={event["quote"]:.8f} open_lots={event["open_lots"]}')
        self._refresh_trade_stats_from_ledger()
        snap = self._trade_ledger.snapshot()
        self.logger.log('INFO', f'[LEDGER] snapshot pnl={snap["realized_pnl"]:.8f} trades={snap["completed_cycles"]} open={snap["open_position_qty"]:.8f}')

    def _on_sell_fill(self, qty: Decimal, price: Decimal):
        tick = Decimal(str(self._exchange_filters.get('tickSize', '0.0001') or '0.0001'))
        result = self._trade_ledger.record_sell(qty, price, fee=self._ledger_fee_rate(), tick_size=tick, timestamp=time.time())
        if result['matched_qty'] > 0:
            self.logger.log('INFO', f'[TRADE] completed qty={result["matched_qty"]:.8f} buy_avg={result["avg_buy"]:.8f} sell={price:.8f} pnl={result["realized"]:.8f} ticks={result["ticks"]:.2f}')
            self.logger.log('INFO', f'[PNL] realized={result["realized"]:.8f} total={self._trade_ledger.realized_pnl:.8f}')
        if result['inventory_qty'] > 0:
            self.logger.log('INFO', f'[INV_SELL] qty={result["inventory_qty"]:.8f} quote={result["inventory_quote"]:.8f}')
        self._refresh_trade_stats_from_ledger()
        snap = self._trade_ledger.snapshot()
        self.logger.log('INFO', f'[LEDGER] snapshot pnl={snap["realized_pnl"]:.8f} trades={snap["completed_cycles"]} open={snap["open_position_qty"]:.8f}')

    def _ledger_fee_rate(self) -> Decimal:
        symbol = str(self.cfg.get('symbol', 'EURIUSDT')).upper()
        if symbol in {'BTCU', 'EURIUSDT'}:
            return Decimal('0')
        return Decimal(str(self.cfg.get('fee_rate', self._pair_config.taker_fee_rate) or self._pair_config.taker_fee_rate))

    def _refresh_trade_stats_from_ledger(self):
        s = self._trade_ledger.snapshot()
        self._trade_stats = {'total': s['total_fills'], 'buy_fills': s['buy_fills'], 'sell_fills': s['sell_fills'], 'cycles': s['completed_cycles'], 'wins': s['winning_cycles'], 'realized_pnl': s['realized_pnl'], 'ticks': s['spread_captured_ticks_total'], 'fees': s['fees'], 'inventory_sells_count': int(s['inventory_sell_qty'] > 0), 'inventory_sells_qty': s['inventory_sell_qty'], 'inventory_sells_quote': s['inventory_sell_quote']}
        self._mark_ui_dirty()

    def _mark_ui_dirty(self):
        self._update_runtime_stats_from_ledger()


    def _update_runtime_stats_from_ledger(self):
        s = self._trade_ledger.snapshot()
        cycles = max(1, s['completed_cycles'])
        avg = (s['realized_pnl'] / Decimal(cycles)) if s['completed_cycles'] > 0 else Decimal('0')
        updates = [
            ('ts_total', self.ts_total, str(s['total_fills'])),
            ('ts_buy_fills', self.ts_buy_fills, str(s['buy_fills'])),
            ('ts_sell_fills', self.ts_sell_fills, str(s['sell_fills'])),
            ('ts_bought_qty', self.ts_bought_qty, f"{s['total_buy_qty']:.8f}"),
            ('ts_sold_qty', self.ts_sold_qty, f"{s['total_sell_qty']:.8f}"),
            ('ts_open_position_qty', self.ts_open_position_qty, f"{s['open_position_qty']:.8f}"),
            ('ts_avg_buy_price', self.ts_avg_buy_price, f"{s['avg_buy']:.8f}"),
            ('ts_avg_sell_price', self.ts_avg_sell_price, f"{s['avg_sell']:.8f}"),
            ('ts_realized', self.ts_realized, f"{s['realized_pnl']:.8f}"),
            ('ts_cycles', self.ts_cycles, str(s['completed_cycles'])),
            ('ts_winrate', self.ts_winrate, f"{s['winrate']:.2f}%"),
            ('ts_fees', self.ts_fees, f"{s['fees']:.8f}"),
            ('ts_avg', self.ts_avg, f"{avg:.8f}"),
            ('ts_bought_quote', self.ts_bought_quote, f"{s['total_buy_quote']:.8f}"),
            ('ts_sold_quote', self.ts_sold_quote, f"{s['total_sell_quote']:.8f}"),
            ('ts_matched_sold_qty', self.ts_matched_sold_qty, f"{s['matched_sell_qty']:.8f}"),
            ('ts_inventory_qty', self.ts_inventory_qty, f"{s['inventory_sell_qty']:.8f}"),
            ('ts_inventory_quote', self.ts_inventory_quote, f"{s['inventory_sell_quote']:.8f}"),
            ('ts_ticks', self.ts_ticks, f"{s['spread_captured_ticks_total']:.2f}"),
            ('cs_trades', self.cs_trades, str(s['total_fills'])),
            ('cs_winrate', self.cs_winrate, f"{s['winrate']:.2f}%"),
            ('cs_pnl', self.cs_pnl, f"{s['realized_pnl']:.8f}"),
        ]
        for key, label, value in updates:
            self._safe_label_set(label, value, key=key)

    def _risk_ok(self) -> tuple[bool, str]:
        if not self.cfg.get('trading_enabled', False):
            return False, 'trading disabled'
        if not self._private_ok:
            return False, 'trading not connected'
        if not self._balances:
            return False, 'balances not loaded'
        risk_blocked = bool(self._balances.get('risk_blocked', False))
        if self.cfg.get('risk_guard_enabled', False) and risk_blocked:
            return False, 'risk guard blocked'
        if not self._spread_metrics:
            return False, 'spread not ready'
        spread_ready = self._spread_metrics.state.readiness == ReadinessState.READY
        spread_ticks = Decimal('0')
        if self._last_market_snapshot and self._exchange_filters:
            bid = Decimal(str(self._last_market_snapshot.get('bid', '0')))
            ask = Decimal(str(self._last_market_snapshot.get('ask', '0')))
            tick = Decimal(str(self._exchange_filters.get('tickSize', '0.0001')))
            if bid > 0 and ask > bid and tick > 0:
                spread_ticks = (ask - bid) / tick
        min_spread_ticks = Decimal(str(self.cfg.get('min_spread_ticks', 2)))
        if not spread_ready and spread_ticks < min_spread_ticks:
            return False, 'spread not ready'
        if not self._fill_observation or not self._fill_observation.fill_possible:
            return False, 'fill not possible'
        return True, 'ok'

    def _fill_not_possible_diag(self) -> str:
        if not self._fill_observation:
            return '[FILL] not possible reason=no observation'
        obs = self._fill_observation
        min_required = max(int(self.cfg.get('min_stable_ms', 3000)), int(self.cfg.get('fill_window_ms', self.cfg.get('min_stable_ms', 3000))))
        bid = self._last_market_snapshot.get('bid', '0') if self._last_market_snapshot else '0'
        ask = self._last_market_snapshot.get('ask', '0') if self._last_market_snapshot else '0'
        spread_ticks = self._spread_metrics.snapshot.spread_ticks if self._spread_metrics else Decimal('0')
        reasons = []
        if spread_ticks < Decimal(str(self.cfg.get('min_spread_ticks', 2))):
            reasons.append('spread below min')
        is_btcu = str(self.cfg.get('symbol', 'EURIUSDT')).upper() == 'BTCU'
        if not is_btcu and obs.bid_lifetime_ms < int(self.cfg.get('min_stable_ms', 3000)):
            reasons.append('bid unstable')
        if not is_btcu and obs.ask_lifetime_ms < int(self.cfg.get('min_stable_ms', 3000)):
            reasons.append('ask unstable')
        if not is_btcu and obs.fill_window_estimate_ms < int(self.cfg.get('fill_window_ms', self.cfg.get('min_stable_ms', 3000))):
            reasons.append('window too short')
        reason = ', '.join(reasons) if reasons else 'unknown'
        return f'[FILL] not possible reason={reason} bid={bid} ask={ask} spread_ticks={spread_ticks:.2f} bid_lifetime_ms={obs.bid_lifetime_ms} ask_lifetime_ms={obs.ask_lifetime_ms} market_activity={obs.market_activity.value} min_required={min_required}'

    def _set_harvest_button_checked(self, checked: bool):
        blocker = QSignalBlocker(self.start_button)
        self.start_button.setChecked(bool(checked))
        del blocker

    def _update_harvest_button(self):
        state = 'OFF'
        color = '#9e9e9e'
        if not self._private_ok and self._live_running:
            state = 'BLOCKED'
            color = '#f44336'
        elif self._live_running:
            state = 'ON'
            color = '#4caf50'
        elif self._cycle.state == CycleState.WAIT_READY:
            state = 'WAITING'
            color = '#fbc02d'
        self.start_button.setText(f'HARVEST {state}')
        self.start_button.setStyleSheet(f'background: {color}; font-weight: 700;')
        self._set_harvest_button_checked(self._live_running)

    def toggle_harvest(self, checked: bool):
        if checked:
            self.start_harvest()
        else:
            self.stop_harvest()

    def start_harvest(self):
        try:
            self.logger.log('INFO', '[GUI] HARVEST toggle ON')
            self.logger.log('INFO', f'[GUI] private_ok={self._private_ok} live={self._live_running}')
            debug_force = bool(globals().get("DEBUG_FORCE_START", False))
            if not self._private_ok and not debug_force:
                self.logger.log('RISK', '[RISK] blocked: not connected')
                self._set_harvest_button_checked(False)
                return
            if debug_force:
                self.logger.log('INFO', '[GUI] DEBUG_FORCE_START direct runtime call')
            self._start_live_runtime()
        except Exception as e:
            self._set_harvest_button_checked(False)
            self.logger.log('ERROR', f'[ERROR] GUI action failed action=HARVEST_ON error={e}')

    def _start_live_runtime(self):
        try:
            self.logger.log('INFO', '[LIVE] _start_live_runtime enter')
            self._live_running = True
            self._runtime_active = True
            self._cycle_started_at = time.time()
            old, new = self._cycle.transition(CycleState.WAIT_READY, 'start requested')
            self.logger.log('FSM', f'{old.value} -> {new.value} reason=transition WAIT_READY')
            self.logger.log('INFO', '[LIVE] runtime started')
            if hasattr(self, 'live_timer') and self.live_timer:
                if self.live_timer.isActive():
                    self.live_timer.stop()
                self.live_timer.start(500)
            return old, new
        except Exception as e:
            self.logger.log('ERROR', f'[ERROR] start runtime failed: {e}')
            raise

    def stop_harvest(self):
        try:
            self._live_running = False
            if hasattr(self, 'live_timer') and self.live_timer and self.live_timer.isActive():
                self.live_timer.stop()
            self.logger.log('INFO', '[GUI] HARVEST toggle OFF')
            self.logger.log('INFO', '[LIVE] runtime stopped')
            self._runtime_active = False
            if self._cycle.state == CycleState.ERROR:
                old, new = self._cycle.transition(CycleState.STOPPED, 'stop from error')
                self.logger.log('FSM', f'{old.value} -> {new.value} reason=stop from error')
                return
            if self._cycle.state in (CycleState.BUY_WORKING, CycleState.BUY_PARTIAL) and self._cycle.buy_order_id:
                try:
                    self.orders.cancel(self._cycle.buy_order_id)
                    self.logger.log('INFO', '[BUY] cancelled by STOP')
                except Exception as e:
                    self.logger.log('ERROR', f'[BUY] cancel failed reason={e}')
                old, new = self._cycle.transition(CycleState.STOPPED, 'stop after buy')
                self.logger.log('FSM', f'{old.value} -> {new.value} reason=stop after buy')
            elif self._cycle.open_position_qty > 0:
                old, new = self._cycle.transition(CycleState.EXIT_PENDING, 'stop with position')
                self.logger.log('FSM', f'{old.value} -> {new.value} reason=stop with position')
            else:
                if self._cycle.state == CycleState.IDLE:
                    self.logger.log('INFO', '[LIVE] already idle')
                old, new = self._cycle.transition(CycleState.STOPPED, 'stop idle')
                self.logger.log('FSM', f'{old.value} -> {new.value} reason=stop idle')
        except Exception as e:
            self.logger.log('ERROR', f'[ERROR] GUI action failed action=HARVEST_OFF error={e}')

    def _live_tick(self):
        if not self._live_running:
            return
        now = time.time()
        if now - self._last_live_tick_log_at >= 3.0:
            self.logger.log('INFO', '[LIVE] tick calling run_live_cycle')
            self._last_live_tick_log_at = now
        self.logger.log('INFO', '[LIVE] tick before run_live_cycle')
        try:
            self._run_live_cycle()
        except Exception as e:
            self.logger.log('ERROR', f'[ERROR] live cycle failed: {e}')
        self.logger.log('INFO', '[LIVE] tick after run_live_cycle')

    def _run_live_cycle(self):
        self.logger.log('INFO', '[RUNTIME] cycle enter')
        c = self._cycle
        fill_state = self._safe_label_text(self.fo_possible, '-')
        self._log_throttled('runtime_cycle_enter', f"[RUNTIME] cycle enter live={self._live_running} private={self._private_ok} data={self._data_mode} fill={fill_state} spread={self._spread_metrics.state.readiness.value if self._spread_metrics else 'NOT_READY'}", 10.0)
        if not self._live_running:
            self._log_throttled('live_wait_not_running', '[LIVE] waiting reason=harvest off', 7.0)
            return
        try:
            self._cleanup_duplicate_side_orders()
            if c.net_inventory_euri < 0:
                self.logger.log('RISK', '[RISK] inventory underflow corrected')
                c.net_inventory_euri = Decimal('0')
            if c.state != CycleState.WAIT_READY:
                old, new = c.transition(CycleState.WAIT_READY, 'continuous runtime')
                self.logger.log('FSM', f'{old.value} -> {new.value} reason=continuous runtime')
            ok, reason = self._risk_ok()
            if not ok:
                now = time.time()
                if now - self._last_wait_log_at >= 7:
                    self.logger.log('INFO', f'[LIVE] waiting reason={reason}')
                    self._last_wait_log_at = now
                return
            bid = Decimal(str(self._last_market_snapshot.get('bid', '0')))
            ask = Decimal(str(self._last_market_snapshot.get('ask', '0')))
            if bid <= 0 or ask <= 0 or ask <= bid:
                self._log_throttled('live_wait_market_stale', '[LIVE] waiting reason=market stale', 7.0)
                return
            filters = self.get_symbol_filters()
            if not filters:
                self._log_throttled('live_wait_filters_missing', '[LIVE] waiting reason=filters unavailable', 7.0)
                return
            tick = Decimal(str(filters.get('tickSize', '0.0001')))
            step = Decimal(str(filters.get('stepSize', '0.0001')))
            min_spread_ticks = Decimal(str(self.cfg.get('min_spread_ticks', 2)))
            spread_ticks = self._compute_spread_ticks(bid, ask)
            if spread_ticks < min_spread_ticks:
                self._log_throttled('live_wait_spread_not_ready', '[LIVE] waiting reason=spread not ready', 7.0)
                return
            max_long = Decimal(str(self.cfg.get('max_long_inventory_euri', 500)))
            max_short = Decimal(str(self.cfg.get('max_short_inventory_euri', -500)))
            net_inv = c.net_inventory_euri
            open_order_ids = {int(o.get('orderId')) for o in self._last_open_orders if o.get('orderId')}

            buy_grace_active = c.buy_order_id and time.time() < self._pending_buy_grace_until
            sell_grace_active = c.sell_order_id and time.time() < self._pending_sell_grace_until

            # BUY engine (independent)
            inv = self._inventory_metrics()
            inv_mode, inv_risk, _ = self._inventory_risk_state(inv['ratio'])
            risk_state = inv_risk if inv_risk else 'OK'
            available_buy_usdt = Decimal(str(self._balances.get('QUOTE_free', 0)))
            buy_quote = Decimal(str(self.cfg.get('max_buy_usdt_exposure', 10))) * inv['buy_mult']
            min_buy_free = Decimal(str(self.cfg.get('min_buy_free_usdt', 5.0)))
            buy_allowed = inv_risk not in ('HEAVY', 'DANGER') and not (c.sell_order_id and inv['ratio'] > Decimal(str(self.cfg.get('target_inventory_ratio', 0.5))))
            if net_inv < max_long and available_buy_usdt >= max(min_buy_free, buy_quote):
                if not buy_allowed:
                    if inv_risk in ('HEAVY', 'DANGER'):
                        self.logger.log('RISK', 'buy blocked: inventory heavy')
                    else:
                        self.logger.log('INFO', '[BUY] skipped: exit priority')
                buy_status = None
                if buy_allowed:
                    if c.buy_order_id:
                        try:
                            st = self.orders.order_status(c.buy_order_id)
                            buy_status = safe_status(st)
                            self._ui_model_set('cs_buy_status', str(buy_status))
                            exec_qty = Decimal(str(st.get('executedQty', '0')))
                            delta = exec_qty - c.buy_filled_qty
                            if delta > 0:
                                c.apply_buy_fill(delta, Decimal(str(st.get('price') or bid)))
                                self.logger.log('INFO', f'[BUY] fill qty={delta}')
                                self._on_buy_fill(delta, Decimal(str(st.get('price') or bid)))
                                # GUI updates are timer-driven only (SELL branch).
                                self._refresh_balances_live('buy_fill')
                                # GUI updates are timer-driven only (SELL branch).
                                self._refresh_orders_live('buy_fill')
                                self.logger.log('INFO', '[SELL] increase quote qty=inventory refresh')
                                self.logger.log('INFO', f'[INVENTORY] net={c.net_inventory_euri}')
                        except Exception as e:
                            self.logger.log('INFO', f'[RUNTIME] reconcile BUY status fetch failed -> {e}')
                            buy_status = None
                if buy_allowed and c.buy_order_id and c.buy_order_id in open_order_ids:
                    if self._pending_buy_order == c.buy_order_id:
                        self._pending_buy_order = None
                        self._pending_buy_grace_until = 0.0
                if buy_allowed and c.buy_order_id and c.buy_order_id not in open_order_ids and buy_grace_active:
                    pass
                elif buy_allowed and c.buy_order_id and c.buy_order_id not in open_order_ids:
                    self.logger.log('INFO', '[BUY] lost, reconciling')
                if buy_allowed and should_clear_active_order(c.buy_order_id, buy_status, open_order_ids) and not buy_grace_active:
                    c.buy_order_id = None
                    self._active_buy_order_id = None
                    self._pending_buy_order = None
                    self._pending_buy_grace_until = 0.0
                if buy_allowed and not c.buy_order_id and not buy_grace_active and not self._pending_buy_order:
                    qty_n = floor_to_step(buy_quote / bid, step) if bid > 0 else Decimal('0')
                    if qty_n > 0:
                        resp = self._place_safe_maker_buy(qty_n, reason='run_live_cycle')
                        if not resp:
                            return
                        c.buy_order_id = int(resp.get('orderId'))
                        c.buy_requested_qty = qty_n
                        c.target_qty = qty_n
                        self._active_buy_order_id = c.buy_order_id
                        self._pending_buy_order = c.buy_order_id
                        self._pending_buy_grace_until = time.time() + self._order_visibility_grace_sec
                        self._buy_started_at = time.time()
                        self._quote_birth[c.buy_order_id] = time.time()
                        self._ui_model_set('cs_top_bid_status', 'WORKING')
                else:
                    ob = self._orders_by_id.get(c.buy_order_id, {})
                    working_price = Decimal(str(ob.get('price') or bid))
                    min_reprice_ticks = Decimal(str(self.cfg.get('minimum_buy_reprice_ticks', self.cfg.get('minimum_reprice_ticks', 1))))
                    tick_move = abs(bid - working_price) / tick if tick > 0 else Decimal('0')
                    quote_age_ms = int((time.time() - self._quote_birth.get(c.buy_order_id, 0.0)) * 1000) if c.buy_order_id else 0
                    min_quote_lifetime_ms = int(self.cfg.get('minimum_quote_lifetime_ms', 0) or 0)
                    if bid == working_price:
                        self._ui_model_set('cs_top_bid_status', 'TOP')
                        self.logger.log('INFO', '[BUY] already top')
                    elif tick_move < min_reprice_ticks or quote_age_ms < min_quote_lifetime_ms:
                        self.logger.log('INFO', f'[BUY] reprice skipped noise delta_ticks={int(tick_move)} min={int(min_reprice_ticks)}')
                    elif bid != working_price and tick_move >= min_reprice_ticks and quote_age_ms >= min_quote_lifetime_ms:
                        self._ui_model_set('cs_top_bid_status', 'OUTBID')
                        self.logger.log('INFO', '[BUY] outbid')
                        if (time.time() - self._last_reprice_at) >= self._reprice_throttle_sec:
                            self._ui_model_set('cs_top_bid_status', 'REPRICING')
                            self.logger.log('INFO', f'[BUY] reposting best_bid old={working_price} new={bid}')
                            try:
                                self.orders.cancel(c.buy_order_id)
                            except Exception as e:
                                self.logger.log('INFO', '[RUNTIME] cancel race ignored')
                            c.buy_order_id = None
                            self._active_buy_order_id = None
                            self.logger.log('INFO', '[RUNTIME] repost continue')
                            self._last_reprice_at = time.time()
                    else:
                        self._ui_model_set('cs_top_bid_status', 'TOP')
                        if self._buy_top_state != 'TOP':
                            self.logger.log('INFO', '[BUY] top acquired')
                        self._buy_top_state = 'TOP'

            # SELL maintain (exchange-balance driven only)
            try:
                exchange_free_euri = Decimal(str(self._balances.get('BASE_free', 0)))
                pending_sell_qty = Decimal('0')
                if c.sell_order_id:
                    so = self._orders_by_id.get(c.sell_order_id, {})
                    pending_sell_qty = floor_to_step(max(Decimal('0'), Decimal(str(so.get('origQty') or '0')) - Decimal(str(so.get('executedQty') or '0'))), step)
                available_for_sell = floor_to_step(max(Decimal('0'), exchange_free_euri), step)
                available_sell_qty = floor_to_step(max(Decimal('0'), exchange_free_euri), step)
                self._ui_model_set('cs_avail_sell_qty', str(available_sell_qty))
                self._ui_model_set('cs_pending_sell_qty', str(pending_sell_qty))
                self._ui_model_set('cs_avail_buy_usdt', f"{available_buy_usdt:.2f}")
                self._ui_model_set('cs_inv_exposure', '-')
                min_qty = Decimal(str(filters.get('minQty', '0') or '0'))
                min_sell_free = min_qty if min_qty > 0 else Decimal(str(self.cfg.get('min_sell_free_euri', 1.0)))
                if available_sell_qty <= Decimal('0') and not c.sell_order_id:
                    self._ui_model_set('cs_top_ask_status', 'NO BTC TO SELL')
                    self.logger.log('INFO', '[SELL] disabled no exchange inventory')
                elif net_inv > max_short and exchange_free_euri >= min_sell_free:
                    if not c.sell_order_id and c.buy_filled_qty > 0:
                        self.logger.log('INFO', f'[SELL] inventory detected qty={exchange_free_euri}')
                    sell_status = None
                    if c.sell_order_id:
                        try:
                            st = self.orders.order_status(c.sell_order_id)
                            sell_status = safe_status(st)
                            self._ui_model_set('cs_sell_status', str(sell_status))
                            exec_qty = Decimal(str(st.get('executedQty', '0')))
                            delta = exec_qty - c.sell_filled_qty
                            if delta > 0:
                                c.apply_sell_fill(delta, Decimal(str(st.get('price') or ask)))
                                self.logger.log('INFO', f'[SELL] fill qty={delta}')
                                self._on_sell_fill(delta, Decimal(str(st.get('price') or ask)))
                                # GUI updates are timer-driven only (SELL branch).
                                self.logger.log('INFO', f'[INVENTORY] net={c.net_inventory_euri}')
                                # GUI updates are timer-driven only (SELL branch).
                                # GUI updates are timer-driven only (SELL branch).
                                # GUI updates are timer-driven only (SELL branch).
                        except Exception as e:
                            self.logger.log('INFO', f'[RUNTIME] reconcile SELL status fetch failed -> {e}')
                            sell_status = None
                    if c.sell_order_id and c.sell_order_id in open_order_ids:
                        self._log_throttled('sell_active', '[SELL] active', 45.0)
                        if self._pending_sell_order == c.sell_order_id:
                            self._pending_sell_order = None
                            self._pending_sell_grace_until = 0.0
                    if c.sell_order_id and c.sell_order_id not in open_order_ids and sell_grace_active:
                        pass
                    elif c.sell_order_id and c.sell_order_id not in open_order_ids:
                        self.logger.log('INFO', '[RUNTIME] SELL vanished -> reconciled')
                        self.logger.log('INFO', '[RUNTIME] reconcile SELL')
                        self.logger.log('INFO', '[RUNTIME] registry cleaned')
                        self.logger.log('INFO', '[RUNTIME] optimistic cleared')
                    if should_clear_active_order(c.sell_order_id, sell_status, open_order_ids) and not sell_grace_active:
                        c.sell_order_id = None
                        self._active_sell_order_id = None
                        self._pending_sell_order = None
                        self._pending_sell_grace_until = 0.0
                    # GUI updates are timer-driven only (SELL branch).
                    # GUI updates are timer-driven only (SELL branch).
                    # GUI updates are timer-driven only (SELL branch).
                    # GUI updates are timer-driven only (SELL branch).
                    exchange_free_euri = floor_to_step(max(Decimal('0'), Decimal(str(self._balances.get('BASE_free', 0)))), step)
                    max_sell_usdt = Decimal(str(self.cfg.get('max_sell_usdt_exposure', 10))) * inv['sell_mult']
                    active_sell_remaining_qty = Decimal('0')
                    if c.sell_order_id and c.sell_order_id in open_order_ids:
                        os = self._orders_by_id.get(c.sell_order_id, {})
                        active_sell_remaining_qty = floor_to_step(max(Decimal('0'), Decimal(str(os.get('origQty') or '0')) - Decimal(str(os.get('executedQty') or '0'))), step)
                    sell_capacity_total = floor_to_step(exchange_free_euri + active_sell_remaining_qty, step)
                    exposure_target_qty = floor_to_step(max_sell_usdt / ask, step) if ask > 0 else Decimal('0')
                    target_sell_qty = min(sell_capacity_total, exposure_target_qty)
                    capacity_signature = (str(exchange_free_euri), str(active_sell_remaining_qty), str(target_sell_qty))
                    if capacity_signature != self._sell_capacity_signature:
                        self.logger.log('INFO', f'[SELL] capacity total free={exchange_free_euri} active_remaining={active_sell_remaining_qty} total={sell_capacity_total}')
                        self._sell_capacity_signature = capacity_signature
                    min_resize_delta_cfg = Decimal(str(self.cfg.get('min_resize_delta_euri', 1.0)))
                    min_resize_delta = max(step * Decimal('5'), Decimal(str(self.cfg.get('min_partial_fill_euri', 0))), min_resize_delta_cfg)
                    if c.sell_order_id and c.sell_order_id in open_order_ids and ask > 0 and not sell_grace_active:
                        os = self._orders_by_id.get(c.sell_order_id, {})
                        working_price = Decimal(str(os.get('price') or ask))
                        working_qty = floor_to_step(max(Decimal('0'), Decimal(str(os.get('origQty') or '0')) - Decimal(str(os.get('executedQty') or '0'))), step)
                        new_tp_price = floor_to_tick(max(ask, c.buy_avg_price + (Decimal(str(self.cfg.get('target_profit_ticks', 1))) * tick)), tick)
                        same_price = abs(working_price - new_tp_price) < tick if tick > 0 else (working_price == new_tp_price)
                        same_qty = abs(working_qty - target_sell_qty) < step if step > 0 else (working_qty == target_sell_qty)
                        if same_price and same_qty:
                            pass
                            pass
                        qty_delta = abs(target_sell_qty - working_qty)
                        if target_sell_qty > 0 and ask == working_price and qty_delta < min_resize_delta:
                            pass
                            pass
                        elif target_sell_qty > 0 and ask != working_price and (abs(ask - working_price) / tick if tick > 0 else Decimal('0')) >= Decimal(str(self.cfg.get('minimum_sell_reprice_ticks', self.cfg.get('minimum_reprice_ticks', 1)))):
                            quote_age_ms = int((time.time() - self._quote_birth.get(c.sell_order_id, 0.0)) * 1000) if c.sell_order_id else 0
                            min_quote_lifetime_ms = int(self.cfg.get('minimum_sell_quote_lifetime_ms', self.cfg.get('minimum_quote_lifetime_ms', 0)) or 0)
                            if quote_age_ms < min_quote_lifetime_ms:
                                pass
                            else:
                                self.logger.log('INFO', f'[SELL] reposting best_ask old={working_price} new={ask}')
                                self.orders.cancel(c.sell_order_id)
                                self._quote_birth.pop(c.sell_order_id, None)
                                c.sell_order_id = None
                                self._active_sell_order_id = None
                                self._pending_sell_order = None
                                self._pending_sell_grace_until = 0.0
                        elif target_sell_qty > 0 and qty_delta >= min_resize_delta and target_sell_qty < working_qty:
                            self.logger.log('INFO', f'[SELL] resize requested old_qty={working_qty} new_qty={target_sell_qty}')
                            self.logger.log('INFO', '[SELL] cancel for resize')
                            self.orders.cancel(c.sell_order_id)
                            self.logger.log('INFO', '[SELL] resize confirmed')
                            # GUI updates are timer-driven only (SELL branch).
                            # GUI updates are timer-driven only (SELL branch).
                            c.sell_order_id = None
                            self._active_sell_order_id = None
                            self._pending_sell_order = None
                            self._pending_sell_grace_until = 0.0
                        elif target_sell_qty > working_qty and qty_delta >= min_resize_delta:
                            if exchange_free_euri >= min_resize_delta:
                                self.logger.log('INFO', f'[SELL] resize requested old_qty={working_qty} new_qty={target_sell_qty}')
                                self.logger.log('INFO', '[SELL] cancel for resize')
                                self.orders.cancel(c.sell_order_id)
                                self.logger.log('INFO', '[SELL] resize confirmed')
                                # GUI updates are timer-driven only (SELL branch).
                                # GUI updates are timer-driven only (SELL branch).
                                c.sell_order_id = None
                                self._active_sell_order_id = None
                                self._pending_sell_order = None
                                self._pending_sell_grace_until = 0.0
                            else:
                                self.logger.log('INFO', '[SELL] resize up skipped insufficient new free inventory')
                    if not c.sell_order_id and not sell_grace_active and not self._pending_sell_order:
                        sell_qty = floor_to_step(min(exchange_free_euri, target_sell_qty), step)
                        if sell_qty < min_qty:
                            self.logger.log('INFO', '[SELL] skipped: no free inventory after refresh')
                        elif sell_qty > 0:
                            min_exit = c.buy_avg_price + (Decimal(str(self.cfg.get('target_profit_ticks', 1))) * tick)
                            self.logger.log('INFO', '[EXIT] unload mode') if risk_state in ('HEAVY', 'DANGER') else None
                            self.logger.log('INFO', f'[SELL] TP protected qty={sell_qty} price={min_exit}') if ask < min_exit else None
                            try:
                                resp = self._place_safe_maker_sell(sell_qty, min_exit, reason='run_live_cycle')
                                if not resp:
                                    return
                            except Exception as e:
                                if 'insufficient' in str(e).lower() and 'balance' in str(e).lower():
                                    # GUI updates are timer-driven only (SELL branch).
                                    # GUI updates are timer-driven only (SELL branch).
                                    if c.sell_order_id and c.sell_order_id not in {int(o.get('orderId')) for o in self._last_open_orders if o.get('orderId')}:
                                        c.sell_order_id = None
                                        self._active_sell_order_id = None
                                    self._pending_sell_order = None
                                    self._pending_sell_grace_until = 0.0
                                    self._last_reprice_at = time.time() + 3.0
                                    self.logger.log('INFO', '[SELL] blocked: insufficient free EURI after refresh')
                                    self.logger.log('INFO', '[SELL] cooldown after balance error')
                                    return
                                raise
                            c.sell_order_id = int(resp.get('orderId'))
                            c.sell_requested_qty = sell_qty
                            self._active_sell_order_id = c.sell_order_id
                            self._pending_sell_order = c.sell_order_id
                            self._pending_sell_grace_until = time.time() + self._order_visibility_grace_sec
                            self._sell_started_at = time.time()
                            self._quote_birth[c.sell_order_id] = time.time()
                            self._ui_model_set('cs_top_ask_status', 'WORKING')
                            self.logger.log('INFO', '[SELL] armed')
                            # GUI updates are timer-driven only (SELL branch).
                    else:
                        os = self._orders_by_id.get(c.sell_order_id, {})
                        working_price = Decimal(str(os.get('price') or ask))
                        min_reprice_ticks = Decimal(str(self.cfg.get('minimum_sell_reprice_ticks', self.cfg.get('minimum_reprice_ticks', 1))))
                        min_exit = c.buy_avg_price + (Decimal(str(self.cfg.get('target_profit_ticks', 1))) * tick)
                        protected_ask = max(ask, min_exit)
                        tick_move = abs(protected_ask - working_price) / tick if tick > 0 else Decimal('0')
                        quote_age_ms = int((time.time() - self._quote_birth.get(c.sell_order_id, 0.0)) * 1000) if c.sell_order_id else 0
                        min_quote_lifetime_ms = int(self.cfg.get('minimum_sell_quote_lifetime_ms', self.cfg.get('minimum_quote_lifetime_ms', 0)) or 0)
                        if ask < min_exit:
                            sell_age = max(0, time.time() - self._sell_started_at) if c.sell_order_id else 0
                            relax_after = int(self.cfg.get('inventory_unload_relax_after_sec', 20) or 20)
                            mode, risk_state, _ = self._inventory_risk_state(inv['ratio'])
                            if risk_state in ('HEAVY', 'DANGER') and sell_age >= relax_after:
                                if ask >= c.buy_avg_price + tick:
                                    self.logger.log('INFO', '[EXIT] TP relax to breakeven+1')
                                    protected_ask = max(ask, c.buy_avg_price + tick)
                                else:
                                    self.logger.log('INFO', '[EXIT] TP relax to breakeven')
                                    protected_ask = max(ask, c.buy_avg_price)
                            else:
                                self.logger.log('INFO', '[SELL] TP protected')
                                self.logger.log('INFO', '[SELL] reprice blocked below profitable exit')
                                pass
                        elif available_sell_qty > Decimal('0') and protected_ask != working_price and protected_ask > 0 and tick_move >= min_reprice_ticks and quote_age_ms >= min_quote_lifetime_ms:
                            if working_price >= min_exit and protected_ask < working_price:
                                self.logger.log('INFO', '[SELL] TP protected')
                                self._sell_top_state = 'TOP'
                                return
                            self._ui_model_set('cs_top_ask_status', 'UNDERCUT')
                            if self._sell_top_state == 'TOP':
                                self.logger.log('INFO', '[SELL] top lost')
                            self._sell_top_state = 'UNDERCUT'
                            self.logger.log('INFO', '[SELL] undercut')
                            if (time.time() - self._last_reprice_at) >= self._reprice_throttle_sec:
                                self._ui_model_set('cs_top_ask_status', 'REPRICING')
                                self.logger.log('INFO', f'[SELL] reposting best_ask old={working_price} new={protected_ask}')
                                try:
                                    self.orders.cancel(c.sell_order_id)
                                except Exception as e:
                                    self.logger.log('INFO', '[RUNTIME] cancel race ignored')
                                self._quote_birth.pop(c.sell_order_id, None)
                                c.sell_order_id = None
                                self._active_sell_order_id = None
                                self.logger.log('INFO', '[RUNTIME] repost continue')
                                self._last_reprice_at = time.time()
                        else:
                            self._ui_model_set('cs_top_ask_status', 'TOP')
                            if self._sell_top_state != 'TOP':
                                self.logger.log('INFO', '[SELL] top acquired')
                            self._sell_top_state = 'TOP'
    
            except Exception as e:
                self.logger.log('ERROR', 'sell branch failed:\n' + traceback.format_exc())

            self.refresh_orders(True)
        except Exception as e:
            self.logger.log('ERROR', f'[LIVE] non-fatal runtime exception: {e}')
            self.logger.log('INFO', '[RUNTIME] reconcile BUY')
            self.logger.log('INFO', '[RUNTIME] reconcile SELL')


    def _ui_model_set(self, key: str, value):
        self._ui_model[key] = str(value)

    def _inventory_metrics(self):
        bid = Decimal(str(self._last_market_snapshot.get('bid', 0) or 0))
        ask = Decimal(str(self._last_market_snapshot.get('ask', 0) or 0))
        mid = (bid + ask) / Decimal('2') if bid > 0 and ask > 0 else Decimal(str(self._last_market_snapshot.get('last', 0) or 0))
        euri_total = Decimal(str(self._balances.get('BASE_free', 0))) + Decimal(str(self._balances.get('BASE_locked', 0)))
        usdt_total = Decimal(str(self._balances.get('QUOTE_free', 0))) + Decimal(str(self._balances.get('QUOTE_locked', 0)))
        euri_value = euri_total * mid if mid > 0 else Decimal('0')
        portfolio = euri_value + usdt_total
        ratio = (euri_value / portfolio) if portfolio > 0 else Decimal(str(self.cfg.get('target_inventory_ratio', 0.5)))
        target = Decimal(str(self.cfg.get('target_inventory_ratio', 0.5)))
        soft = Decimal(str(self.cfg.get('inventory_soft_limit', 0.65)))
        hard = Decimal(str(self.cfg.get('inventory_hard_limit', 0.80)))
        drift = 'CENTERED'
        color = '#4caf50'
        base = self._pair_config.base_asset
        quote = self._pair_config.quote_asset
        if ratio >= hard or ratio <= (Decimal('1') - hard):
            drift = f'{base} HEAVY' if ratio >= target else f'{quote} HEAVY'
            color = '#f44336'
        elif ratio >= soft or ratio <= (Decimal('1') - soft):
            drift = f'{base} HEAVY' if ratio >= target else f'{quote} HEAVY'
            color = '#fbc02d'
        delta = ratio - target
        boost = min(abs(delta) / Decimal('0.30'), Decimal('1')) * Decimal('0.30')
        buy_mult = Decimal('1') + (boost if delta > 0 else -boost)
        sell_mult = Decimal('1') + (-boost if delta > 0 else boost)
        return {'portfolio':portfolio,'base_value':euri_value,'quote_value':usdt_total,'ratio':ratio,'drift':drift,'color':color,'buy_mult':max(Decimal('0.50'), buy_mult),'sell_mult':max(Decimal('0.50'), sell_mult)}

    def _compute_spread_ticks(self, bid: Decimal, ask: Decimal) -> Decimal:
        tick = Decimal(str(self._exchange_filters.get('tickSize', '0.0001') or '0.0001'))
        if bid <= 0 or ask <= bid or tick <= 0:
            return Decimal('0')
        return (ask - bid) / tick

    def _inventory_risk_state(self, ratio: Decimal) -> tuple[str, str, str]:
        target = Decimal(str(self.cfg.get('target_inventory_ratio', 0.5)))
        soft = Decimal(str(self.cfg.get('inventory_soft_limit', 0.65)))
        hard = Decimal(str(self.cfg.get('inventory_hard_limit', 0.80)))
        if ratio > hard:
            return 'EXIT_ONLY', 'DANGER', 'RISK INVENTORY DANGER'
        if ratio > soft:
            return 'HARVEST', 'HEAVY', 'RISK INVENTORY HEAVY'
        if ratio > target:
            return 'HARVEST', 'OK', 'RISK OK'
        return 'HARVEST', 'OK', 'RISK OK'

    def _tick_status(self):
        if not isValid(self):
            return
        try:
            self._update_status_strip()
            self._update_runtime_stats_panel()
            self._apply_ui_model_to_widgets()
        except RuntimeError as exc:
            # Qt can fire one last timer tick while widgets are being torn down.
            # Stop the periodic callback to avoid noisy "C++ object already deleted" traces.
            if 'already deleted' in str(exc):
                if hasattr(self, '_status_timer') and self._status_timer:
                    self._status_timer.stop()
                return
            raise
    def _update_status_strip(self):
        spread=(self._spread_metrics.state.readiness.value if self._spread_metrics else 'NOT_READY')
        stale_timeout_ms = int(self.cfg.get('market_stale_ms', 3000) or 3000)
        market_age_ms = int((time.time() - self._last_market_ts) * 1000) if self._last_market_ts > 0 else 10**9
        stale = market_age_ms > stale_timeout_ms
        if stale and self.ws.status.state == 'OK' and self._last_market_source == 'WS':
            self.logger.log('INFO', '[WS] stale')
            self.logger.log('INFO', '[WS] reconnecting')
            self.ws.mark_error('market stale')
        if stale:
            self._data_mode = 'REST' if self._last_market_source == 'REST' else 'STALE'
            data_status = 'DATA STALE'
        else:
            self._data_mode = 'WS' if self._last_market_source == 'WS' else 'REST'
            data_status = 'DATA WS OK' if self._data_mode == 'WS' else 'DATA REST OK'
        engine_state = self._cycle.state.value
        harvest_running = bool(self._live_running)
        if self._data_mode != self._last_data_mode:
            self.logger.log('INFO', '[DATA] source=WS' if self._data_mode == 'WS' else '[DATA] source=REST')
            self._last_data_mode = self._data_mode
        risk_blocked = bool(self._balances.get('risk_blocked', False))
        risk_enabled = bool(self.cfg.get('risk_guard_enabled'))
        inv = self._inventory_metrics()
        inv_mode, inv_risk, inv_strip = self._inventory_risk_state(inv['ratio'])
        risk_label = 'BLOCKED' if (risk_enabled and risk_blocked) else inv_risk
        self._status_badges['CONNECTED'].setText(f"CONNECTED {'YES' if self._private_ok else 'NO'}")
        spread_ticks = str(int(self._compute_spread_ticks(Decimal(str(self._last_market_snapshot.get('bid', 0) or 0)), Decimal(str(self._last_market_snapshot.get('ask', 0) or 0))))) if self._spread_metrics else '-' 
        self._status_badges['SPREAD'].setText(f"SPREAD {spread} ticks={spread_ticks}")
        self._status_badges['DATA'].setText(data_status)
        self._status_badges['LIVE'].setText('LIVE ✅' if harvest_running else 'LIVE ❌')
        self._status_badges['CONNECTED'].setText(f"CONNECTED {'✅' if self._private_ok else '❌'}")
        self._status_badges['DATA'].setText(f"DATA {'✅' if not stale else '❌'}")
        self._status_badges['FILTERS'].setText(f"FILTERS {'✅' if bool(self.get_symbol_filters()) else '❌'}")
        bal_ok = Decimal(str(self._balances.get('QUOTE_free',0))) > 0
        self._status_badges['BALANCE'].setText(f"BALANCE {'✅' if bal_ok else '❌'}")
        market_ok = self._last_market_ts > 0 and not stale
        self._status_badges['MARKET'].setText(f"MARKET {'✅' if market_ok else '❌'}")
        fill_ok = self._safe_label_text(self.fo_possible, 'NO') == 'YES'
        self._status_badges['FILL'].setText(f"FILL {'✅' if fill_ok else '❌'}")
        self._status_badges['CYCLE'].setText(f"CYCLE {self._cycle.state.value}")
        self._status_badges['ORDER'].setText(f"ORDER {'✅' if len(self._last_open_orders)>0 else '❌'}")
        self._status_badges['RISK'].setText(f"RISK {risk_label}")
        self._set_label_text(self._status_balance_euri, f"{self._pair_config.base_asset} {self._fmt_bal('BASE_free')} / locked {self._fmt_bal('BASE_locked')}")
        self._set_label_text(self._status_balance_usdt, f"{self._pair_config.quote_asset} {self._fmt_bal('QUOTE_free')} / locked {self._fmt_bal('QUOTE_locked')}")
        self._log_throttled('balance_status_updated', f"[BALANCE] updated base={self._pair_config.base_asset} free={self._balances.get('BASE_free', 0)} locked={self._balances.get('BASE_locked', 0)} quote={self._pair_config.quote_asset} free={self._balances.get('QUOTE_free', 0)} locked={self._balances.get('QUOTE_locked', 0)}", 10.0)

    def _update_runtime_stats_panel(self):
        inv=self._inventory_metrics(); self.cs_inv_portfolio.setText(f"{inv['portfolio']:.2f}"); self.cs_inv_base_value.setText(f"{inv['base_value']:.2f}"); self.cs_inv_quote_value.setText(f"{inv['quote_value']:.2f}"); self.cs_inv_ratio.setText(f"{self._pair_config.base_asset} {inv['ratio']*100:.0f}% / {self._pair_config.quote_asset} {(Decimal('1')-inv['ratio'])*100:.0f}%"); self.cs_inv_drift.setText(inv['drift'])
        sig=(f"{inv['ratio']*100:.0f}",inv['drift'])
        if sig!=self._last_inventory_log_signature:
            self.logger.log('INFO', f"[INV] ratio {self._pair_config.base_asset}={inv['ratio']*100:.0f}% {self._pair_config.quote_asset}={(Decimal('1')-inv['ratio'])*100:.0f}%")
            self.logger.log('INFO', f"[INV] {inv['drift'].lower()}")
            self._last_inventory_log_signature=sig
        enabled=self._private_ok; self.cancel_all_btn.setEnabled(enabled); self.cancel_selected_btn.setEnabled(enabled and self._selected_order_id is not None)
        self._update_runtime_stats_from_ledger(); self._safe_label_set(self.ts_runtime, f"{int(time.time()-self._session_started_at)}s"); self._safe_label_set(self.cs_data_source, self._data_mode); self._safe_label_set(self.cs_open_orders, str(len(self._last_open_orders))); inv=self._inventory_metrics(); mode,risk,_=self._inventory_risk_state(inv['ratio']); self._safe_label_set(self.cs_reason, f"mode={mode} risk={risk} ratio={inv['ratio']*100:.1f}% exit_wait={int(max(0,time.time()-self._sell_started_at)) if self._active_sell_order_id else 0}s")
        self.start_harvest_btn.setEnabled(True); self.stop_harvest_btn.setEnabled(False); self._update_harvest_button()
        self._paint_status()

    def _apply_ui_model_to_widgets(self):
        mapping = {
            'cs_buy_status': self.cs_buy_status,
            'cs_sell_status': self.cs_sell_status,
            'cs_top_bid_status': self.cs_top_bid_status,
            'cs_top_ask_status': self.cs_top_ask_status,
            'cs_avail_sell_qty': self.cs_avail_sell_qty,
            'cs_pending_sell_qty': self.cs_pending_sell_qty,
            'cs_avail_buy_usdt': self.cs_avail_buy_usdt,
            'cs_inv_exposure': self.cs_inv_exposure,
        }
        for key, value in list(self._ui_model.items()):
            label = mapping.get(key)
            if label is None:
                continue
            if not self._safe_label_set(label, value, key=key):
                self._ui_model.pop(key, None)

    def _safe_label_set(self, label: QLabel | None, text, key: str | None = None):
        try:
            if label is not None and isValid(label):
                label.setText(str(text))
                return True
        except RuntimeError:
            pass
        if key:
            now = time.time()
            until = self._stale_label_warn_until.get(key, 0.0)
            if now >= until:
                self.logger.log('WARNING', f'[GUI] stale label ignored key={key}')
                self._stale_label_warn_until[key] = now + 30.0
        return False


    def _set_label_text(self, label: QLabel | None, value: str):
        return self._safe_label_set(label, value)
    def _safe_label_text(self, label: QLabel | None, fallback: str = '-') -> str:
        if label is None or not isValid(label):
            return fallback
        try:
            return label.text()
        except RuntimeError as e:
            self.logger.log('ERROR', f'stale QLabel skipped: {e}')
            return fallback

    def _set_label_color(self, label: QLabel, color: str):
        if label is None or not isValid(label):
            return
        try:
            label.setStyleSheet(f'color: {color}; font-weight: 600;')
        except RuntimeError:
            return
    def _paint_status(self):
        self._set_label_color(self._status_badges['CONNECTED'], '#4caf50' if self._private_ok else '#f44336')
        spread_state = self._spread_metrics.state.readiness.value if self._spread_metrics else 'NOT_READY'
        self._set_label_color(self._status_badges['SPREAD'], '#4caf50' if spread_state == 'READY' else ('#fbc02d' if spread_state == 'WATCH' else '#f44336'))
        data_state = self._safe_label_text(self._status_badges.get('DATA'), 'DATA STALE')
        self._set_label_color(self._status_badges['DATA'], '#f44336' if data_state == 'DATA STALE' else ('#4caf50' if self._data_mode == 'WS' else '#fbc02d'))
        risk_ok, _ = self._risk_ok()
        self._set_label_color(self._status_badges['RISK'], '#4caf50' if risk_ok else '#f44336')
        self._set_label_color(self._status_badges['LIVE'], '#4caf50' if self._live_running else '#f44336')
        top_bid_status = self._safe_label_text(self.cs_top_bid_status, '-')
        self._set_label_color(self.cs_top_bid_status, {'TOP': '#4caf50', 'WORKING': '#fbc02d', 'REPRICING': '#ff9800', 'NO INVENTORY': '#9e9e9e', 'ERROR': '#f44336'}.get(top_bid_status, '#e6edf3'))
        top_ask_status = self._safe_label_text(self.cs_top_ask_status, '-')
        self._set_label_color(self.cs_top_ask_status, {'TOP': '#4caf50', 'WORKING': '#fbc02d', 'REPRICING': '#ff9800', 'NO INVENTORY': '#9e9e9e', 'ERROR': '#f44336'}.get(top_ask_status, '#e6edf3'))
        cycle_color = {'IDLE': '#9e9e9e', 'WAIT_READY': '#fbc02d', 'PLACE_BUY': '#42a5f5', 'BUY_WORKING': '#42a5f5', 'CANCEL_BUY': '#ff9800', 'BUY_FILLED': '#4caf50', 'PLACE_SELL': '#42a5f5', 'SELL_WORKING': '#42a5f5', 'CANCEL_SELL': '#ff9800', 'SELL_FILLED': '#4caf50', 'PROFIT_LOCKED': '#4caf50', 'EXIT_PENDING': '#ff9800', 'ERROR': '#f44336', 'STOPPED': '#9e9e9e'}.get(self._cycle.state.value, '#e6edf3')
        self._set_label_color(self.cs_state, cycle_color)
        self._set_label_color(self.ss_readiness, '#4caf50' if spread_state == 'READY' else ('#fbc02d' if spread_state == 'WATCH' else '#9e9e9e'))
        fill_possible_text = self._safe_label_text(self.fo_possible, 'NO')
        self._set_label_color(self.fo_possible, '#4caf50' if fill_possible_text == 'YES' else '#9e9e9e')
        inv=self._inventory_metrics(); self._set_label_color(self.cs_inv_drift, inv['color'])
    def _fmt_bal(self,k):
        if not self._private_ok and not self._balances: return '-'
        return f"{Decimal(str(self._balances.get(k,0))):.2f}"
    def _on_order_selected(self):
        row = self.table.currentRow()
        if row < 0:
            self._selected_order_id = None
            return
        if row < len(self._last_open_orders):
            order_id = self._last_open_orders[row].get('orderId')
            self._selected_order_id = int(order_id) if order_id else None
    def _market_bid(self): return f"{Decimal(str(self._last_market_snapshot.get('bid',0))):.8f}"
    def _market_ask(self): return f"{Decimal(str(self._last_market_snapshot.get('ask',0))):.8f}"
    def _balance_euri(self): return f"{Decimal(str(self._balances.get('BASE_free',0))):.8f}"
    def _sync_trade_settings_labels(self):
        self.cfg['harvest_mode'] = 'LIVE_TRADE'
        self.ts_symbol.setText(str(self.cfg.get('symbol','EURIUSDT'))); self.ts_mode.setText('LIVE TRADE'); self.ts_pair_profile.setText(self._pair_config.profile); self.ts_buy_exp.setText(str(self.cfg.get('max_buy_usdt_exposure',10))); self.ts_sell_exp.setText(str(self.cfg.get('max_sell_usdt_exposure',10))); self.ts_min.setText(str(self.cfg.get('min_spread_ticks',2))); self.ts_profit.setText(str(self.cfg.get('target_profit_ticks',1))); self.ts_stable.setText(str(self.cfg.get('min_stable_ms',3000))); self.ts_partial.setText('YES' if self.cfg.get('allow_partial_fills',True) else 'NO'); self.ts_min_partial.setText(str(self.cfg.get('min_partial_fill_euri',0))); self.ts_reprice.setText('YES' if self.cfg.get('reprice_on_move',True) else 'NO'); self.ts_collapse.setText('YES' if self.cfg.get('cancel_on_spread_collapse',True) else 'NO'); self.ts_risk.setText('ON' if self.cfg.get('risk_guard_enabled',False) else 'OFF')
        if self.pair_selector.currentText() != self.cfg.get('symbol'):
            self.pair_selector.blockSignals(True); self.pair_selector.setCurrentText(self.cfg.get('symbol')); self.pair_selector.blockSignals(False)
        self._sync_cycle_state_labels()

    def _sync_cycle_state_labels(self):
        c = self._cycle
        buy_remaining=max(Decimal('0'), c.buy_requested_qty-c.buy_filled_qty); sell_remaining=max(Decimal('0'), c.sell_requested_qty-c.sell_filled_qty)
        self.cs_state.setText(c.state.value); self.cs_target.setText(str(c.target_qty)); self.cs_bought.setText(str(c.buy_filled_qty)); self.cs_sold.setText(str(c.sell_filled_qty)); self.cs_open.setText(str(c.open_position_qty)); self.cs_avg_buy.setText(str(c.buy_avg_price)); self.cs_avg_sell.setText(str(c.sell_avg_price)); self.cs_pnl.setText(str(c.realized_pnl)); self.cs_order.setText(str(c.sell_order_id or c.buy_order_id or '-')); self.cs_reason.setText(c.reason or '-'); self.cs_buy_working.setText(str(self._orders_by_id.get(c.buy_order_id, {}).get('price', '-'))); self.cs_sell_working.setText(str(self._orders_by_id.get(c.sell_order_id, {}).get('price', '-'))); self.cs_buy_remaining.setText(str(buy_remaining)); self.cs_sell_remaining.setText(str(sell_remaining)); self.cs_cycle_age.setText(f"{int((time.time()-self._cycle_started_at)*1000)} ms"); self.cs_last_fill.setText(self._last_fill_time); self.cs_buy_order_id.setText(str(self._active_buy_order_id or '-')); self.cs_sell_order_id.setText(str(self._active_sell_order_id or '-')); self.cs_buy_age.setText(str(max(0, int((time.time()-self._buy_started_at)*1000))) if c.buy_order_id else '-'); self.cs_sell_age.setText(str(max(0, int((time.time()-self._sell_started_at)*1000))) if c.sell_order_id else '-')
    def _get_exchange_info(self): return self.client.get_exchange_info(self.cfg['symbol'])
    def _load_exchange_filters(self):
        try:
            filters = extract_symbol_filters(self._get_exchange_info())
            required = ('tickSize', 'stepSize', 'minQty', 'maxQty', 'minNotional')
            if any(filters.get(k, '0') in ('0', '', 'None', 'none', 'null') for k in required):
                self._exchange_filters = {}
                self.logger.log('RISK', '[RISK] blocked: exchange filters missing')
                return False
            self._exchange_filters = filters
            self.logger.log('INFO', f"[FILTERS] loaded symbol={self.cfg['symbol']} tickSize={filters['tickSize']} stepSize={filters['stepSize']} minQty={filters['minQty']} minNotional={filters['minNotional']}")
            self.market.set_tick_size(Decimal(str(filters['tickSize'])))
            return True
        except Exception as e:
            self._exchange_filters = {}
            self.logger.log('ERROR', f'[FILTERS] load failed reason={e}')
            self.logger.log('RISK', '[RISK] blocked: exchange filters missing')
            return False
    def _require_exchange_filters(self): return bool(self._exchange_filters) or self._load_exchange_filters()
    def get_symbol_filters(self):
        if not self._require_exchange_filters():
            self.logger.log('RISK', '[RISK] blocked: exchange filters missing')
            return None
        required = ('tickSize', 'stepSize', 'minQty', 'maxQty', 'minNotional')
        filters = {k: self._exchange_filters.get(k) for k in required}
        if any(filters.get(k) in (None, '', '0', 'None', 'none', 'null') for k in required):
            self.logger.log('RISK', '[RISK] blocked: exchange filters missing')
            return None
        return filters
    def _current_filters(self) -> tuple[Decimal, Decimal, dict]:
        filters = self.get_symbol_filters()
        if not filters:
            raise RuntimeError('exchange filters unavailable')
        step = Decimal(str(filters.get('stepSize', '0.0001') or '0.0001'))
        tick = Decimal(str(filters.get('tickSize', '0.0001') or '0.0001'))
        return step, tick, filters

    def place(self, side, price, qty):
        if not self._private_ok and not self.cfg.get('api_key'): self.logger.log('ERROR','[ORDER] rejected reason=private api unavailable'); return
        try:
            info = self.get_symbol_filters()
            if not info: return
            tick = Decimal(str(info.get('tickSize')))
            step = Decimal(str(info.get('stepSize')))
            api_price = format_decimal_for_tick(Decimal(str(price)), tick)
            api_qty = format_decimal_for_step(Decimal(str(qty)), step)
            ok,msg=validate_order(api_price, api_qty, tick_size=info['tickSize'], step_size=info['stepSize'], min_qty=info['minQty'], min_notional=info['minNotional'])
            if not ok: self.logger.log('ERROR', f'[ORDER] rejected reason={msg}'); return
            self.logger.log('INFO', f'[ORDER] {side} LIMIT sent price={api_price} qty={api_qty}')
            resp=self.orders.place_limit(side,api_qty,api_price); self.logger.log('INFO', f"[ORDER] accepted id={resp.get('orderId')}")
            self.refresh_orders(True)
        except Exception as e:
            self.logger.log('ERROR', f'[ORDER] rejected reason={e}')
    def cancel_selected(self):
        try:
            if not self._selected_order_id: self.logger.log('RISK','[RISK] blocked: no order selected'); return
            try: self.orders.cancel(self._selected_order_id); self.logger.log('INFO',f'cancelled id={self._selected_order_id}'); self.refresh_orders(True)
            except Exception as e: self.logger.log('ERROR',f'cancel selected failed: {e}')
        except Exception as e:
            self.logger.log('ERROR', f'[ERROR] GUI action failed action=CANCEL_SELECTED error={e}')
    def cancel_all(self):
        try:
            try: self.orders.cancel_all(); self.logger.log('INFO','cancel all requested'); self.refresh_orders(True)
            except Exception as e: self.logger.log('ERROR',f'cancel all failed: {e}')
        except Exception as e:
            self.logger.log('ERROR', f'[ERROR] GUI action failed action=CANCEL_ALL error={e}')
    def start_polling(self):
        self.polling.set_private_enabled(True)
        self.polling.start()
        self.runtime.set_polling(True)
    def _all_data_text(self, group):
        if group == 'Account':
            return f"{self._pair_config.base_asset}_free={self._balances.get('BASE_free', '-')}\n{self._pair_config.base_asset}_locked={self._balances.get('BASE_locked', '-')}\n{self._pair_config.quote_asset}_free={self._balances.get('QUOTE_free', '-')}\n{self._pair_config.quote_asset}_locked={self._balances.get('QUOTE_locked', '-')}"
        if group == 'Market':
            return f"bid={self._last_market_snapshot.get('bid', '-')}\nask={self._last_market_snapshot.get('ask', '-')}\nlast={self._last_market_snapshot.get('last', '-')}\nspread_readiness={self._spread_metrics.state.readiness.value if self._spread_metrics else '-'}"
        if group == 'Runtime':
            inv=self._inventory_metrics()
            pressure=self._pair_config.base_asset if inv['ratio']>Decimal(str(self.cfg.get('target_inventory_ratio',0.5))) else self._pair_config.quote_asset
            ws_age_ms = int((time.time() - self._last_market_ts) * 1000) if self._last_market_ts > 0 else -1
            avg = Decimal('0')
            snap = self._trade_ledger.snapshot()
            cycles = int(snap.get('completed_cycles', 0) or 0)
            realized_pnl = Decimal(str(snap.get('realized_pnl', Decimal('0'))))
            if cycles > 0:
                avg = realized_pnl / Decimal(cycles)
            return f"pair_profile={self._pair_config.profile}\nbase_asset={self._pair_config.base_asset}\nquote_asset={self._pair_config.quote_asset}\ncycle_state={self._cycle.state.value}\nactive_buy_id={self._active_buy_order_id}\nactive_sell_id={self._active_sell_order_id}\nlive_running={self._live_running}\nprivate_ok={self._private_ok}\nportfolio_quote={inv['portfolio']:.2f}\nbase_value={inv['base_value']:.2f}\nquote_value={inv['quote_value']:.2f}\ninventory_ratio_{self._pair_config.base_asset.lower()}={inv['ratio']*100:.2f}%\ninventory_ratio_{self._pair_config.quote_asset.lower()}={(Decimal('1')-inv['ratio'])*100:.2f}%\ndynamic_buy_exposure_mult={inv['buy_mult']:.2f}\ndynamic_sell_exposure_mult={inv['sell_mult']:.2f}\ninventory_pressure={pressure}\nadaptive_multiplier_delta={abs(inv['buy_mult']-Decimal('1')):.2f}\ntrades_total={snap['total_fills']}\ncompleted_cycles={snap['completed_cycles']}\nrealized_pnl={snap['realized_pnl']:.8f}\navg_profit={avg:.8f}\nspread_captured_ticks={snap['spread_captured_ticks_total']:.2f}\nfees={snap['fees']:.8f}\ninventory_sells={int(snap['inventory_sell_qty'] > 0)}\nws_connected={self.ws.status.state == 'OK'}\nws_last_tick_age_ms={ws_age_ms}\nws_tick_count={self.ws.status.tick_count}\nws_reconnects={self.ws.status.reconnects}\nlast_ws_error={self.ws.status.last_error}"
        if group == 'Orders':
            return '\n'.join([f"id={o.get('orderId')} side={o.get('side')} price={o.get('price')} qty={o.get('origQty')} exec={o.get('executedQty')} status={o.get('status')}" for o in self._last_open_orders]) or 'No open orders'
        if group == 'Execution':
            return f"reprice_throttle_sec={self._reprice_throttle_sec}\norder_visibility_grace_sec={self._order_visibility_grace_sec}\norders_live_interval={self._orders_live_interval_sec}\nbalance_live_interval={self._balance_live_interval_sec}"
        if group == 'Filters':
            f = self._exchange_filters
            return f"symbol={self.cfg.get('symbol','EURIUSDT')}\ntickSize={f.get('tickSize','-')}\nstepSize={f.get('stepSize','-')}\nminQty={f.get('minQty','-')}\nmaxQty={f.get('maxQty','-')}\nminNotional={f.get('minNotional','-')}"
        return group

def run():
    app=QApplication(sys.argv); w=MainWindow(); w.show(); sys.exit(app.exec())
