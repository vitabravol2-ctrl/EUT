from __future__ import annotations

import sys
from decimal import Decimal
import time

from PySide6.QtCore import Qt, QTimer
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
from app.core.ws_manager import WSManager
from app.core.reconcile import safe_status, should_clear_active_order
from app.gui.panels.log_panel import LogPanel
from app.gui.settings_dialog import SettingsDialog
from app.gui.ui_constants import *

DARK_STYLESHEET = "QWidget { background: #0b0f14; color: #e6edf3; }"

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
        self._fill_observer=FillObserver(int(self.cfg.get('min_spread_ticks',2)), int(self.cfg.get('min_stable_ms',3000)))
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
        self._inventory_state='UNKNOWN'; self._inventory_color='#9e9e9e'; self._last_inventory_log_signature=None
        self._orders_live_last_refresh=0.0; self._balance_live_last_refresh=0.0; self._orders_live_interval_sec=1.5; self._balance_live_interval_sec=7.0
        self._orders_gui_last_sync=0.0; self._orders_gui_interval_sec=2.5
        self._sell_capacity_signature=None; self._buy_top_state='UNKNOWN'; self._sell_top_state='UNKNOWN'
        self._quote_birth: dict[int, float] = {}
        self._data_mode = 'REST'
        self._last_data_mode = None
        self._last_market_ts = 0.0
        self._session_started_at = time.time()
        self._trade_lots: list[dict] = []
        self._trade_stats = {'total': 0, 'buy_fills': 0, 'sell_fills': 0, 'cycles': 0, 'wins': 0, 'realized_pnl': Decimal('0'), 'ticks': Decimal('0'), 'fees': Decimal('0'), 'inventory_sells_count': 0, 'inventory_sells_qty': Decimal('0'), 'inventory_sells_quote': Decimal('0')}
        self._init_services(); self._build_ui(); self._sync_trade_settings_labels()
        self.task_runner=TaskRunner(4,self); self.task_runner.signals.success.connect(self._on_task_success); self.task_runner.signals.error.connect(self._on_task_error); self.task_runner.signals.finished.connect(self.task_runner.finish)
        self.polling=PollingManager(self.refresh_market,self.refresh_orders,self.refresh_balances,300,500,3000,self)
        self._status_timer=QTimer(self); self._status_timer.timeout.connect(self._tick_status); self._status_timer.start(300); QTimer.singleShot(50,self._startup_connect_flow)
    def _init_services(self):
        self.client=BinanceClient(self.cfg['api_key'],self.cfg['api_secret'],self.cfg['testnet'],self.cfg.get('request_timeout_sec',3)); self.market=MarketService(self.client,self.cfg['symbol']); self.account=AccountService(self.client, self._pair_config.base_asset, self._pair_config.quote_asset); self.orders=OrderService(self.client,self.cfg['symbol'])
    def _build_ui(self):
        root=QWidget(); self.setCentralWidget(root); main=QVBoxLayout(root); top=QGroupBox('Status Strip'); l=QHBoxLayout(top)
        for k in ['CONNECTED','SPREAD','DATA','HARVEST','ORDERS','RISK']:
            b=QLabel(f'{k} -'); self._status_badges[k]=b; l.addWidget(b)
        self._status_balance_euri=QLabel('BASE - / locked -'); l.addWidget(self._status_balance_euri)
        self._status_balance_usdt=QLabel('QUOTE - / locked -'); l.addWidget(self._status_balance_usdt)
        main.addWidget(top)
        split=QSplitter(Qt.Horizontal)
        left=QGroupBox('Trade / Harvest Settings'); fl=QFormLayout(left); self.ts_symbol=QLabel(); self.ts_mode=QLabel('LIVE TRADE'); self.ts_pair_profile=QLabel('-'); self.ts_buy_exp=QLabel(); self.ts_sell_exp=QLabel(); self.ts_min=QLabel(); self.ts_profit=QLabel(); self.ts_stable=QLabel(); self.ts_partial=QLabel(); self.ts_min_partial=QLabel(); self.ts_reprice=QLabel(); self.ts_collapse=QLabel(); self.ts_cycle_age=QLabel(); self.ts_risk=QLabel()
        self.pair_selector = QComboBox(); self.pair_selector.addItems(list_pairs()); self.pair_selector.currentTextChanged.connect(self._on_pair_selected)
        for n,w in [('PAIR',self.pair_selector),('Mode',self.ts_mode),('Symbol',self.ts_symbol),('Pair profile',self.ts_pair_profile),('Max BUY exposure USDT',self.ts_buy_exp),('Max SELL exposure USDT',self.ts_sell_exp),('Min spread ticks',self.ts_min),('Target profit ticks',self.ts_profit),('Min stable ms',self.ts_stable),('Allow partial fills',self.ts_partial),('Min partial fill EURI',self.ts_min_partial),('Reprice on bid/ask move',self.ts_reprice),('Cancel on spread collapse',self.ts_collapse),('Risk guard',self.ts_risk)]: fl.addRow(n,w)
        fl.addRow(self._btn('START HARVEST', self.start_harvest)); fl.addRow(self._btn('STOP HARVEST', self.stop_harvest)); fl.addRow(self._btn('Edit Settings', self.open_trade_settings))
        cycle=QGroupBox('Runtime State'); cf=QFormLayout(cycle); self.cs_state=QLabel(); self.cs_target=QLabel(); self.cs_bought=QLabel(); self.cs_sold=QLabel(); self.cs_open=QLabel(); self.cs_avg_buy=QLabel(); self.cs_avg_sell=QLabel(); self.cs_pnl=QLabel(); self.cs_order=QLabel(); self.cs_reason=QLabel(); self.cs_buy_working=QLabel(); self.cs_sell_working=QLabel(); self.cs_buy_remaining=QLabel(); self.cs_sell_remaining=QLabel(); self.cs_cycle_age=QLabel(); self.cs_last_fill=QLabel('-'); self.cs_buy_order_id=QLabel('-'); self.cs_sell_order_id=QLabel('-'); self.cs_buy_status=QLabel('-'); self.cs_sell_status=QLabel('-'); self.cs_top_bid_status=QLabel('-'); self.cs_top_ask_status=QLabel('-'); self.cs_buy_age=QLabel('-'); self.cs_sell_age=QLabel('-'); self.cs_avail_sell_qty=QLabel('-'); self.cs_pending_sell_qty=QLabel('-'); self.cs_avail_buy_usdt=QLabel('-'); self.cs_inv_exposure=QLabel('-'); self.ss_readiness=QLabel('NOT_READY')
        self.cs_inv_portfolio=QLabel('-'); self.cs_inv_base_value=QLabel('-'); self.cs_inv_quote_value=QLabel('-'); self.cs_inv_ratio=QLabel('-'); self.cs_inv_drift=QLabel('-')
        self.cs_trades=QLabel('0'); self.cs_winrate=QLabel('0.0%')
        for n,w in [('ENGINE',self.cs_state),('BUY STATE',self.cs_buy_status),('SELL STATE',self.cs_sell_status),('BUY TOP',self.cs_top_bid_status),('SELL TOP',self.cs_top_ask_status),(f"{self._pair_config.base_asset} Value",self.cs_inv_base_value),(f"{self._pair_config.quote_asset} Value",self.cs_inv_quote_value),(f"Inventory Ratio {self._pair_config.base_asset} / {self._pair_config.quote_asset}",self.cs_inv_ratio),('Inventory Drift',self.cs_inv_drift),('PnL',self.cs_pnl),('Trades',self.cs_trades),('Winrate',self.cs_winrate),('LAST FILL',self.cs_last_fill)]: cf.addRow(n,w)
        stats_box=QGroupBox('Trade Stats'); sf=QFormLayout(stats_box)
        self.ts_total=QLabel('0'); self.ts_buy_fills=QLabel('0'); self.ts_sell_fills=QLabel('0'); self.ts_cycles=QLabel('0'); self.ts_winrate=QLabel('0.0%'); self.ts_realized=QLabel('0.00000000'); self.ts_avg=QLabel('0.00000000'); self.ts_ticks=QLabel('0.00'); self.ts_fees=QLabel('0.00000000'); self.ts_runtime=QLabel('0s')
        self.ts_inventory_sells=QLabel('0'); self.ts_inventory_qty=QLabel('0.00000000'); self.ts_inventory_quote=QLabel('0.00000000')
        for n,w in [('Trades total',self.ts_total),('BUY fills',self.ts_buy_fills),('SELL fills',self.ts_sell_fills),('Completed cycles',self.ts_cycles),('Inventory sells count',self.ts_inventory_sells),('Inventory sells qty',self.ts_inventory_qty),('Inventory sells quote',self.ts_inventory_quote),('Winrate %',self.ts_winrate),('Realized PnL',self.ts_realized),('Avg profit / trade',self.ts_avg),('Spread captured ticks',self.ts_ticks),('Fees',self.ts_fees),('Session runtime',self.ts_runtime)]: sf.addRow(n,w)
        center=QGroupBox('Open Orders'); cl=QVBoxLayout(center); self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['side','price','qty','filled','remain','age','top-status']); self.table.itemSelectionChanged.connect(self._on_order_selected); self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); cl.addWidget(self.table); self.no_orders=QLabel('No open orders'); cl.addWidget(self.no_orders)
        spread_box=QGroupBox('Spread Stability'); sl=QFormLayout(spread_box)
        self.ss_ticks=QLabel('-'); self.ss_lifetime=QLabel('-'); self.ss_bid=QLabel('-'); self.ss_ask=QLabel('-'); self.ss_ratio=QLabel('-'); self.ss_collapse=QLabel('0')
        for n,w in [('Spread ticks',self.ss_ticks),('Spread lifetime',self.ss_lifetime),('Bid stable',self.ss_bid),('Ask stable',self.ss_ask),('Stable ratio',self.ss_ratio),('Collapse count',self.ss_collapse),('Readiness',self.ss_readiness)]: sl.addRow(n,w)
        self.fo_bid=QLabel('-'); self.fo_ask=QLabel('-'); self.fo_window=QLabel('-'); self.fo_activity=QLabel('-'); self.fo_possible=QLabel('NO')
        for n,w in [('Fill: bid lifetime',self.fo_bid),('Fill: ask lifetime',self.fo_ask),('Fill: window',self.fo_window),('Fill: market activity',self.fo_activity),('Fill: possible',self.fo_possible)]: sl.addRow(n,w)
        right=QGroupBox('Actions'); rl=QVBoxLayout(right)
        for t,f in [('Manual Order',self.open_manual_order),('Cancel Selected',self.cancel_selected),('Cancel All',self.cancel_all),('All Data',self.open_all_data),('Settings',self.open_settings)]: rl.addWidget(self._btn(t,f))
        left_buttons = left.findChildren(QPushButton)
        self.start_harvest_btn=left_buttons[0]; self.stop_harvest_btn=left_buttons[1]; self.cancel_selected_btn=right.findChildren(QPushButton)[1]; self.cancel_all_btn=right.findChildren(QPushButton)[2]
        split.addWidget(left); split.addWidget(cycle); split.addWidget(center); split.addWidget(stats_box); split.addWidget(right); split.setStretchFactor(2, 3); main.addWidget(split)
        logs=QGroupBox('Logs'); ll=QVBoxLayout(logs); self.log_panel=LogPanel(500); self.logger.subscribe(self.log_panel.append_record); ll.addWidget(self.log_panel); main.addWidget(logs)
    def closeEvent(self, event):
        self._live_running = False
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
        self.logger.log('INFO', '[WS] connecting')
        self.ws.connect()
        self._load_exchange_filters(); self.refresh_market(True); self.refresh_balances(True); self.refresh_orders(True); self.start_polling()
    def open_settings(self): self.settings_dialog=SettingsDialog(self.cfg,self.apply_settings,self.test_connection,self); self.settings_dialog.show()
    def open_trade_settings(self): self.trade_settings_dialog=TradeSettingsDialog(self.cfg,self.apply_trade_settings,self); self.trade_settings_dialog.show()
    def open_manual_order(self): self.manual_order_dialog=ManualOrderDialog(self,self); self.manual_order_dialog.show()
    def open_all_data(self): self.all_data_dialog=AllDataDialog(self,self); self.all_data_dialog.show()
    def apply_settings(self,v): self.cfg.update(v); save_config(self.cfg)
    def apply_trade_settings(self,v): self.cfg.update(v); save_config(self.cfg); self._sync_trade_settings_labels(); self._fill_observer=FillObserver(int(self.cfg.get('min_spread_ticks',2)), int(self.cfg.get('min_stable_ms',3000)))
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
        self.market.set_symbol(symbol); self.orders.set_symbol(symbol); self.account.set_assets(self._pair_config.base_asset, self._pair_config.quote_asset)
        max_reprice_per_sec = float(self.cfg.get('max_reprice_per_sec', 0) or 0)
        self._reprice_throttle_sec = (1.0 / max_reprice_per_sec) if max_reprice_per_sec > 0 else self._pair_config.top_check_interval_sec
        self._orders_live_interval_sec = self._pair_config.quote_refresh_interval_sec
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
            self._last_market_snapshot=dict(payload)
            self._last_market_ts = time.time()
            if self.ws.status.state != 'OK':
                self.ws.mark_ok()
                self.logger.log('INFO', '[WS] subscribed')
                self.logger.log('INFO', '[WS] first tick')
            else:
                self.logger.log('INFO', '[WS] heartbeat ok')
            metrics=self._spread_engine.observe(Decimal(str(payload.get('bid',0))), Decimal(str(payload.get('ask',0))), float(payload.get('latency_ms',0)))
            self._spread_metrics=metrics
            self._set_label_text(self.ss_ticks, f"raw={metrics.snapshot.spread:.8f} | ticks={metrics.snapshot.spread_ticks:.2f}")
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
                self.logger.log('INFO', '[FILL] POSSIBLE' if self._fill_observation.fill_possible else '[FILL] NOT_POSSIBLE')
                self._last_fill_possible = self._fill_observation.fill_possible
            if slow_market != self._last_slow_market:
                self.logger.log('INFO', f"[FILL] slow_market={'YES' if slow_market else 'NO'}")
                self._last_slow_market = slow_market
            if metrics.state.readiness != self._last_spread_readiness:
                self.logger.log('INFO', f"[SPREAD] {metrics.state.readiness.value} spread={metrics.snapshot.spread_ticks:.2f} lifetime={metrics.state.spread_lifetime_ms}ms")
                self._last_spread_readiness=metrics.state.readiness
            if self._cycle.state == CycleState.IDLE:
                old, new = self._cycle.transition(CycleState.WAIT_READY, 'boot')
                self.logger.log('FSM', f'{old.value} -> {new.value} reason=boot')
            if metrics.state.spread_collapse_count > 0 and metrics.state.readiness == ReadinessState.NOT_READY:
                self.logger.log('INFO', '[SPREAD] COLLAPSE')
        elif name=='balances': self._balances=payload; self._private_ok=True
        elif name=='orders': self._sync_open_orders(payload)
    def _on_task_error(self,name,err):
        self.logger.log('ERROR', f'{name}: {err}');
        if name in ('orders','balances'): self._private_ok=False
    def _sync_open_orders(self, payload):
        prev_count = len(self._last_open_orders)
        self._last_open_orders = payload; self._private_ok = True
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
            top_status = 'TOP' if ((side == 'BUY' and self.cs_top_bid_status.text() == 'TOP') or (side == 'SELL' and self.cs_top_ask_status.text() == 'TOP')) else ('WATCH' if str(o.get('status', '')).upper() in ('NEW', 'PARTIALLY_FILLED') else 'IDLE')
            vals=[side,f"{Decimal(str(o.get('price', '0') or '0')):.8f}",f"{orig:.8f}",f"{exe:.8f}",f"{rem:.8f}",age_ms,top_status]
            for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))

    def _on_buy_fill(self, qty: Decimal, price: Decimal):
        self._trade_stats['total'] += 1
        self._trade_stats['buy_fills'] += 1
        self._trade_lots.append({'qty': qty, 'price': price, 'time': time.time()})

    def _on_sell_fill(self, qty: Decimal, price: Decimal):
        self._trade_stats['total'] += 1
        self._trade_stats['sell_fills'] += 1
        taker_fee_rate = Decimal(str(self.cfg.get('fee_rate', self._pair_config.taker_fee_rate) or self._pair_config.taker_fee_rate))
        remaining = qty
        matched_qty = Decimal('0')
        buy_notional = Decimal('0')
        while remaining > 0 and self._trade_lots:
            lot = self._trade_lots[0]
            take = min(remaining, lot['qty'])
            matched_qty += take
            buy_notional += take * lot['price']
            lot['qty'] -= take
            remaining -= take
            if lot['qty'] <= 0:
                self._trade_lots.pop(0)
        if matched_qty <= 0:
            self._trade_stats['inventory_sells_count'] += 1
            self._trade_stats['inventory_sells_qty'] += qty
            self._trade_stats['inventory_sells_quote'] += qty * price
            self.logger.log('INFO', f'[INV_SELL] qty={qty:.8f} quote={(qty*price):.8f}')
            return
        if remaining > 0:
            self._trade_stats['inventory_sells_count'] += 1
            self._trade_stats['inventory_sells_qty'] += remaining
            self._trade_stats['inventory_sells_quote'] += remaining * price
            self.logger.log('INFO', f'[TRADE] matched qty={matched_qty:.8f}')
            self.logger.log('INFO', f'[INV_SELL] qty={remaining:.8f} quote={(remaining*price):.8f}')
        avg_buy = buy_notional / matched_qty
        gross = matched_qty * (price - avg_buy)
        buy_fee_quote = (matched_qty * avg_buy) * taker_fee_rate
        sell_fee_quote = (matched_qty * price) * taker_fee_rate
        fees = buy_fee_quote + sell_fee_quote
        realized = gross - fees
        tick = Decimal(str(self._exchange_filters.get('tickSize', '0.0001') or '0.0001'))
        ticks = ((price - avg_buy) / tick) if tick > 0 else Decimal('0')
        self._trade_stats['cycles'] += 1
        self._trade_stats['fees'] += fees
        self._trade_stats['realized_pnl'] += realized
        self._trade_stats['ticks'] += ticks
        if realized > 0:
            self._trade_stats['wins'] += 1
        self.logger.log('INFO', f'[PNL] gross={gross:.8f} fees={fees:.8f} realized={realized:.8f} total={self._trade_stats["realized_pnl"]:.8f}')
        self.logger.log('INFO', f'[TRADE] completed qty={matched_qty:.8f} buy={avg_buy:.8f} sell={price:.8f} ticks={ticks:.2f}')

    def _risk_ok(self) -> tuple[bool, str]:
        if not self.cfg.get('trading_enabled', False):
            return False, 'trading disabled'
        if not self._private_ok:
            return False, 'trading not connected'
        if not self._balances:
            return False, 'balances not loaded'
        if self.cfg.get('risk_guard_enabled', False):
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

    def start_harvest(self):
        if self._cycle.state == CycleState.ERROR:
            self._cycle = HarvestCycle()
            old, new = self._cycle.transition(CycleState.WAIT_READY, 'start reset from error')
            self._live_running = True
            self.logger.log('FSM', f'{CycleState.ERROR.value} -> {CycleState.RESET.value} reason=start reset')
            self.logger.log('INFO', '[LIVE] runtime started')
            self.logger.log('FSM', f'{old.value} -> {new.value} reason=start requested')
            return
        if not self._live_confirmed:
            answer = QMessageBox.question(self, 'LIVE Confirmation', 'Start LIVE harvest with real Binance orders?\nSmall test mode only.')
            if answer != QMessageBox.Yes:
                return
            self._live_confirmed = True
        self._live_running = True
        self._cycle_started_at = time.time()
        old, new = self._cycle.transition(CycleState.WAIT_READY, 'start requested')
        self.logger.log('INFO', '[LIVE] runtime started')
        self.logger.log('FSM', f'{old.value} -> {new.value} reason=start requested')

    def stop_harvest(self):
        self._live_running = False
        self.logger.log('INFO', '[LIVE] stopped')
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

    def _run_live_cycle(self):
        c = self._cycle
        if not self._live_running:
            return
        try:
            self._cleanup_duplicate_side_orders()
            if c.state != CycleState.WAIT_READY:
                old, new = c.transition(CycleState.WAIT_READY, 'continuous runtime')
                self.logger.log('FSM', f'{old.value} -> {new.value} reason=continuous runtime')
            ok, reason = self._risk_ok()
            if not ok:
                now = time.time()
                if now - self._last_wait_log_at >= 7:
                    self.logger.log('INFO', f'[LIVE] waiting: {reason}')
                    self._last_wait_log_at = now
                return
            bid = Decimal(str(self._last_market_snapshot.get('bid', '0')))
            ask = Decimal(str(self._last_market_snapshot.get('ask', '0')))
            if bid <= 0 or ask <= 0 or ask <= bid:
                return
            filters = self.get_symbol_filters()
            if not filters:
                return
            tick = Decimal(str(filters.get('tickSize', '0.0001')))
            step = Decimal(str(filters.get('stepSize', '0.0001')))
            min_spread_ticks = Decimal(str(self.cfg.get('min_spread_ticks', 2)))
            spread_ticks = (ask - bid) / tick if tick > 0 else Decimal('0')
            if spread_ticks < min_spread_ticks:
                return
            max_long = Decimal(str(self.cfg.get('max_long_inventory_euri', 500)))
            max_short = Decimal(str(self.cfg.get('max_short_inventory_euri', -500)))
            net_inv = c.net_inventory_euri
            self._log_throttled('runtime_dual_active', '[RUNTIME] dual-sided active', 45.0)

            open_order_ids = {int(o.get('orderId')) for o in self._last_open_orders if o.get('orderId')}

            buy_grace_active = c.buy_order_id and time.time() < self._pending_buy_grace_until
            sell_grace_active = c.sell_order_id and time.time() < self._pending_sell_grace_until

            # BUY engine (independent)
            inv = self._inventory_metrics()
            available_buy_usdt = Decimal(str(self._balances.get('QUOTE_free', 0)))
            buy_quote = Decimal(str(self.cfg.get('max_buy_usdt_exposure', 10))) * inv['buy_mult']
            min_buy_free = Decimal(str(self.cfg.get('min_buy_free_usdt', 5.0)))
            if net_inv < max_long and available_buy_usdt >= max(min_buy_free, buy_quote):
                buy_status = None
                if c.buy_order_id:
                    try:
                        st = self.orders.order_status(c.buy_order_id)
                        buy_status = safe_status(st)
                        self.cs_buy_status.setText(str(buy_status))
                        exec_qty = Decimal(str(st.get('executedQty', '0')))
                        delta = exec_qty - c.buy_filled_qty
                        if delta > 0:
                            c.apply_buy_fill(delta, Decimal(str(st.get('price') or bid)))
                            self.logger.log('INFO', f'[BUY] fill qty={delta}')
                            self._on_buy_fill(delta, Decimal(str(st.get('price') or bid)))
                            self._refresh_balances_live('buy_fill')
                            self._refresh_orders_live('buy_fill')
                            self.logger.log('INFO', '[SELL] increase quote qty=inventory refresh')
                            self.logger.log('INFO', f'[INVENTORY] net={c.net_inventory_euri}')
                    except Exception as e:
                        self.logger.log('INFO', f'[RUNTIME] reconcile BUY status fetch failed -> {e}')
                        buy_status = None
                if c.buy_order_id and c.buy_order_id in open_order_ids:
                    if self._pending_buy_order == c.buy_order_id:
                        self._pending_buy_order = None
                        self._pending_buy_grace_until = 0.0
                if c.buy_order_id and c.buy_order_id not in open_order_ids and buy_grace_active:
                    pass
                elif c.buy_order_id and c.buy_order_id not in open_order_ids:
                    self.logger.log('INFO', '[BUY] lost, reconciling')
                if should_clear_active_order(c.buy_order_id, buy_status, open_order_ids) and not buy_grace_active:
                    c.buy_order_id = None
                    self._active_buy_order_id = None
                    self._pending_buy_order = None
                    self._pending_buy_grace_until = 0.0
                if not c.buy_order_id and not buy_grace_active and not self._pending_buy_order:
                    qty_n = floor_to_step(buy_quote / bid, step) if bid > 0 else Decimal('0')
                    if qty_n > 0:
                        price = floor_to_tick(bid, tick)
                        resp = self.orders.place_limit_maker('BUY', format_decimal_for_step(qty_n, step), format_decimal_for_tick(price, tick))
                        c.buy_order_id = int(resp.get('orderId'))
                        c.buy_requested_qty = qty_n
                        c.target_qty = qty_n
                        self._active_buy_order_id = c.buy_order_id
                        self._pending_buy_order = c.buy_order_id
                        self._pending_buy_grace_until = time.time() + self._order_visibility_grace_sec
                        self._buy_started_at = time.time()
                        self._quote_birth[c.buy_order_id] = time.time()
                        self.cs_top_bid_status.setText('WORKING')
                else:
                    ob = self._orders_by_id.get(c.buy_order_id, {})
                    working_price = Decimal(str(ob.get('price') or bid))
                    min_reprice_ticks = Decimal(str(self.cfg.get('minimum_buy_reprice_ticks', self.cfg.get('minimum_reprice_ticks', 1))))
                    tick_move = abs(bid - working_price) / tick if tick > 0 else Decimal('0')
                    quote_age_ms = int((time.time() - self._quote_birth.get(c.buy_order_id, 0.0)) * 1000) if c.buy_order_id else 0
                    min_quote_lifetime_ms = int(self.cfg.get('minimum_quote_lifetime_ms', 0) or 0)
                    if bid == working_price:
                        self.cs_top_bid_status.setText('TOP')
                        self.logger.log('INFO', '[BUY] already top')
                    elif tick_move < min_reprice_ticks or quote_age_ms < min_quote_lifetime_ms:
                        self.logger.log('INFO', '[BUY] reprice skipped noise')
                    elif bid != working_price and tick_move >= min_reprice_ticks and quote_age_ms >= min_quote_lifetime_ms:
                        self.cs_top_bid_status.setText('OUTBID')
                        self.logger.log('INFO', '[BUY] outbid')
                        if (time.time() - self._last_reprice_at) >= self._reprice_throttle_sec:
                            self.cs_top_bid_status.setText('REPRICING')
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
                        self.cs_top_bid_status.setText('TOP')
                        if self._buy_top_state != 'TOP':
                            self.logger.log('INFO', '[BUY] top acquired')
                        self._buy_top_state = 'TOP'

            # SELL maintain (exchange-balance driven only)
            exchange_free_euri = Decimal(str(self._balances.get('BASE_free', 0)))
            pending_sell_qty = Decimal('0')
            if c.sell_order_id:
                so = self._orders_by_id.get(c.sell_order_id, {})
                pending_sell_qty = floor_to_step(max(Decimal('0'), Decimal(str(so.get('origQty') or '0')) - Decimal(str(so.get('executedQty') or '0'))), step)
            available_for_sell = floor_to_step(max(Decimal('0'), exchange_free_euri), step)
            available_sell_qty = floor_to_step(max(Decimal('0'), exchange_free_euri), step)
            self.cs_avail_sell_qty.setText(str(available_sell_qty))
            self.cs_pending_sell_qty.setText(str(pending_sell_qty))
            self.cs_avail_buy_usdt.setText(f"{available_buy_usdt:.2f}")
            self.cs_inv_exposure.setText('-')
            min_qty = Decimal(str(filters.get('minQty', '0') or '0'))
            min_sell_free = min_qty if min_qty > 0 else Decimal(str(self.cfg.get('min_sell_free_euri', 1.0)))
            if available_sell_qty <= Decimal('0') and not c.sell_order_id:
                self.cs_top_ask_status.setText('NO BTC TO SELL')
                self.logger.log('INFO', '[SELL] disabled no exchange inventory')
            elif net_inv > max_short and exchange_free_euri >= min_sell_free:
                if not c.sell_order_id and c.buy_filled_qty > 0:
                    self.logger.log('INFO', f'[SELL] inventory detected qty={exchange_free_euri}')
                sell_status = None
                if c.sell_order_id:
                    try:
                        st = self.orders.order_status(c.sell_order_id)
                        sell_status = safe_status(st)
                        self.cs_sell_status.setText(str(sell_status))
                        exec_qty = Decimal(str(st.get('executedQty', '0')))
                        delta = exec_qty - c.sell_filled_qty
                        if delta > 0:
                            c.apply_sell_fill(delta, Decimal(str(st.get('price') or ask)))
                            self.logger.log('INFO', f'[SELL] fill qty={delta}')
                            self._on_sell_fill(delta, Decimal(str(st.get('price') or ask)))
                            self.logger.log('INFO', f'[INVENTORY] net={c.net_inventory_euri}')
                            self._refresh_balances_live('sell_fill')
                            self._refresh_orders_live('sell_fill')
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
                self._refresh_balances_live('pre_sell_compute')
                self._refresh_orders_live('pre_sell_compute')
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
                        self.logger.log('INFO', '[SELL] TP unchanged')
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
                        self._refresh_balances_live('sell_resize_cancel', force=True)
                        self._refresh_orders_live('sell_resize_cancel', force=True)
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
                            self._refresh_balances_live('sell_resize_cancel', force=True)
                            self._refresh_orders_live('sell_resize_cancel', force=True)
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
                        price = floor_to_tick(max(ask, min_exit), tick)
                        self.logger.log('INFO', f'[SELL] placing TP qty={sell_qty} ask={price}')
                        try:
                            resp = self.orders.place_limit_maker('SELL', format_decimal_for_step(sell_qty, step), format_decimal_for_tick(price, tick))
                        except Exception as e:
                            if 'insufficient' in str(e).lower() and 'balance' in str(e).lower():
                                self._refresh_balances_live('sell_balance_error', force=True)
                                self._refresh_orders_live('sell_balance_error', force=True)
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
                        self.cs_top_ask_status.setText('WORKING')
                        self.logger.log('INFO', '[SELL] TP active')
                        self._refresh_orders_live('sell_place', force=True)
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
                        self.logger.log('INFO', '[SELL] TP protected')
                        self.logger.log('INFO', '[SELL] reprice blocked below profitable exit')
                        self.logger.log('INFO', '[SELL] keep profitable TP')
                    elif available_sell_qty > Decimal('0') and protected_ask != working_price and protected_ask > 0 and tick_move >= min_reprice_ticks and quote_age_ms >= min_quote_lifetime_ms:
                        self.cs_top_ask_status.setText('UNDERCUT')
                        if self._sell_top_state == 'TOP':
                            self.logger.log('INFO', '[SELL] top lost')
                        self._sell_top_state = 'UNDERCUT'
                        self.logger.log('INFO', '[SELL] undercut')
                        if (time.time() - self._last_reprice_at) >= self._reprice_throttle_sec:
                            self.cs_top_ask_status.setText('REPRICING')
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
                        self.cs_top_ask_status.setText('TOP')
                        if self._sell_top_state != 'TOP':
                            self.logger.log('INFO', '[SELL] top acquired')
                        self._sell_top_state = 'TOP'

            self.refresh_orders(True)
        except Exception as e:
            self.logger.log('ERROR', f'[LIVE] non-fatal runtime exception: {e}')
            self.logger.log('INFO', '[RUNTIME] reconcile BUY')
            self.logger.log('INFO', '[RUNTIME] reconcile SELL')

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

    def _tick_status(self):
        if not isValid(self):
            return
        self._status_badges['CONNECTED'].setText(f"CONNECTED {'YES' if self._private_ok else 'NO'}")
        spread=(self._spread_metrics.state.readiness.value if self._spread_metrics else 'NOT_READY'); self._status_badges['SPREAD'].setText(f'SPREAD {spread}')
        stale_timeout_ms = int(self.cfg.get('market_stale_ms', 3000) or 3000)
        market_age_ms = int((time.time() - self._last_market_ts) * 1000) if self._last_market_ts > 0 else 10**9
        if market_age_ms > stale_timeout_ms:
            if self.ws.status.state == 'OK':
                self.logger.log('INFO', '[WS] stale')
                self.logger.log('INFO', '[WS] reconnecting')
            self.ws.mark_error('market stale')
        self._data_mode = 'WS' if self.ws.status.state == 'OK' else 'REST'
        stale = market_age_ms > stale_timeout_ms
        data_status = 'DATA STALE' if stale else ('DATA WS OK' if self._data_mode == 'WS' else 'DATA REST OK')
        self._status_badges['DATA'].setText(data_status)
        if self._data_mode != self._last_data_mode:
            self.logger.log('INFO', '[DATA] source=WS' if self._data_mode == 'WS' else '[DATA] source=REST')
            self._last_data_mode = self._data_mode
        self._status_badges['HARVEST'].setText('HARVEST ACTIVE' if self._live_running else 'HARVEST IDLE')
        self._status_badges['ORDERS'].setText(f'ORDERS {len(self._last_open_orders)}'); self._status_badges['RISK'].setText(f"RISK {'BLOCKED' if self.cfg.get('risk_guard_enabled') else 'OK'}")
        self._status_balance_euri.setText(f"{self._pair_config.base_asset} {self._fmt_bal('BASE_free')} / locked {self._fmt_bal('BASE_locked')}")
        self._status_balance_usdt.setText(f"{self._pair_config.quote_asset} {self._fmt_bal('QUOTE_free')} / locked {self._fmt_bal('QUOTE_locked')}")
        inv=self._inventory_metrics(); self.cs_inv_portfolio.setText(f"{inv['portfolio']:.2f}"); self.cs_inv_base_value.setText(f"{inv['base_value']:.2f}"); self.cs_inv_quote_value.setText(f"{inv['quote_value']:.2f}"); self.cs_inv_ratio.setText(f"{self._pair_config.base_asset} {inv['ratio']*100:.0f}% / {self._pair_config.quote_asset} {(Decimal('1')-inv['ratio'])*100:.0f}%"); self.cs_inv_drift.setText(inv['drift'])
        sig=(f"{inv['ratio']*100:.0f}",inv['drift'])
        if sig!=self._last_inventory_log_signature:
            self.logger.log('INFO', f"[INV] ratio {self._pair_config.base_asset}={inv['ratio']*100:.0f}% {self._pair_config.quote_asset}={(Decimal('1')-inv['ratio'])*100:.0f}%")
            self.logger.log('INFO', f"[INV] {inv['drift'].lower()}")
            self._last_inventory_log_signature=sig
        enabled=self._private_ok; self.cancel_all_btn.setEnabled(enabled); self.cancel_selected_btn.setEnabled(enabled and self._selected_order_id is not None)
        cycles = max(1, self._trade_stats['cycles'])
        winrate = (Decimal(self._trade_stats['wins']) / Decimal(cycles) * Decimal('100')) if self._trade_stats['cycles'] > 0 else Decimal('0')
        avg = (self._trade_stats['realized_pnl'] / Decimal(cycles)) if self._trade_stats['cycles'] > 0 else Decimal('0')
        self.ts_total.setText(str(self._trade_stats['total'])); self.ts_buy_fills.setText(str(self._trade_stats['buy_fills'])); self.ts_sell_fills.setText(str(self._trade_stats['sell_fills'])); self.ts_cycles.setText(str(self._trade_stats['cycles'])); self.ts_inventory_sells.setText(str(self._trade_stats['inventory_sells_count'])); self.ts_inventory_qty.setText(f"{self._trade_stats['inventory_sells_qty']:.8f}"); self.ts_inventory_quote.setText(f"{self._trade_stats['inventory_sells_quote']:.8f}"); self.ts_winrate.setText(f"{winrate:.2f}%"); self.ts_realized.setText(f"{self._trade_stats['realized_pnl']:.8f}"); self.ts_avg.setText(f"{avg:.8f}"); self.ts_ticks.setText(f"{self._trade_stats['ticks']:.2f}"); self.ts_fees.setText(f"{self._trade_stats['fees']:.8f}"); self.ts_runtime.setText(f"{int(time.time()-self._session_started_at)}s")
        self.cs_trades.setText(str(self._trade_stats['total'])); self.cs_winrate.setText(f"{winrate:.2f}%"); self.cs_pnl.setText(f"{self._trade_stats['realized_pnl']:.8f}")
        self.start_harvest_btn.setEnabled(True); self.stop_harvest_btn.setEnabled(True)
        self._paint_status()
        self._run_live_cycle()
    def _set_label_text(self, label: QLabel | None, value: str):
        if label is None or not isValid(label):
            return
        label.setText(value)

    def _set_label_color(self, label: QLabel, color: str):
        if label is None or not isValid(label):
            return
        label.setStyleSheet(f'color: {color}; font-weight: 600;')
    def _paint_status(self):
        self._set_label_color(self._status_badges['CONNECTED'], '#4caf50' if self._private_ok else '#f44336')
        spread_state = self._spread_metrics.state.readiness.value if self._spread_metrics else 'NOT_READY'
        self._set_label_color(self._status_badges['SPREAD'], '#4caf50' if spread_state == 'READY' else ('#fbc02d' if spread_state == 'WATCH' else '#9e9e9e'))
        data_state = self._status_badges['DATA'].text()
        self._set_label_color(self._status_badges['DATA'], '#f44336' if data_state == 'DATA STALE' else ('#4caf50' if self._data_mode == 'WS' else '#fbc02d'))
        risk_ok, _ = self._risk_ok()
        self._set_label_color(self._status_badges['RISK'], '#4caf50' if risk_ok else '#f44336')
        self._set_label_color(self._status_badges['HARVEST'], '#4caf50' if self._private_ok else '#fbc02d')
        cycle_color = {'IDLE': '#9e9e9e', 'WAIT_READY': '#fbc02d', 'PLACE_BUY': '#42a5f5', 'BUY_WORKING': '#42a5f5', 'CANCEL_BUY': '#ff9800', 'BUY_FILLED': '#4caf50', 'PLACE_SELL': '#42a5f5', 'SELL_WORKING': '#42a5f5', 'CANCEL_SELL': '#ff9800', 'SELL_FILLED': '#4caf50', 'PROFIT_LOCKED': '#4caf50', 'EXIT_PENDING': '#ff9800', 'ERROR': '#f44336', 'STOPPED': '#9e9e9e'}.get(self._cycle.state.value, '#e6edf3')
        self._set_label_color(self.cs_state, cycle_color)
        self._set_label_color(self.ss_readiness, '#4caf50' if spread_state == 'READY' else ('#fbc02d' if spread_state == 'WATCH' else '#9e9e9e'))
        fill_possible_text = self.fo_possible.text() if self.fo_possible is not None and isValid(self.fo_possible) else 'NO'
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
        if not self._selected_order_id: self.logger.log('ERROR','cancel selected: no order selected'); return
        try: self.orders.cancel(self._selected_order_id); self.logger.log('INFO',f'cancelled id={self._selected_order_id}'); self.refresh_orders(True)
        except Exception as e: self.logger.log('ERROR',f'cancel selected failed: {e}')
    def cancel_all(self):
        try: self.orders.cancel_all(); self.logger.log('INFO','cancel all requested'); self.refresh_orders(True)
        except Exception as e: self.logger.log('ERROR',f'cancel all failed: {e}')
    def start_polling(self): self.polling.start(); self.runtime.set_polling(True)
    def _all_data_text(self, group):
        if group == 'Account':
            return f"{self._pair_config.base_asset}_free={self._balances.get('BASE_free', '-')}\n{self._pair_config.base_asset}_locked={self._balances.get('BASE_locked', '-')}\n{self._pair_config.quote_asset}_free={self._balances.get('QUOTE_free', '-')}\n{self._pair_config.quote_asset}_locked={self._balances.get('QUOTE_locked', '-')}"
        if group == 'Market':
            return f"bid={self._last_market_snapshot.get('bid', '-')}\nask={self._last_market_snapshot.get('ask', '-')}\nlast={self._last_market_snapshot.get('last', '-')}\nspread_readiness={self._spread_metrics.state.readiness.value if self._spread_metrics else '-'}"
        if group == 'Runtime':
            inv=self._inventory_metrics()
            pressure=self._pair_config.base_asset if inv['ratio']>Decimal(str(self.cfg.get('target_inventory_ratio',0.5))) else self._pair_config.quote_asset
            ws_age_ms = int((time.time() - self._last_market_ts) * 1000) if self._last_market_ts > 0 else -1
            return f"pair_profile={self._pair_config.profile}\nbase_asset={self._pair_config.base_asset}\nquote_asset={self._pair_config.quote_asset}\ncycle_state={self._cycle.state.value}\nactive_buy_id={self._active_buy_order_id}\nactive_sell_id={self._active_sell_order_id}\nlive_running={self._live_running}\nprivate_ok={self._private_ok}\nportfolio_quote={inv['portfolio']:.2f}\ninventory_ratio_{self._pair_config.base_asset.lower()}={inv['ratio']*100:.2f}%\ninventory_ratio_{self._pair_config.quote_asset.lower()}={(Decimal('1')-inv['ratio'])*100:.2f}%\ndynamic_buy_exposure_mult={inv['buy_mult']:.2f}\ndynamic_sell_exposure_mult={inv['sell_mult']:.2f}\ninventory_pressure={pressure}\nadaptive_multiplier_delta={abs(inv['buy_mult']-Decimal('1')):.2f}\ntrades_total={self._trade_stats['total']}\ncompleted_cycles={self._trade_stats['cycles']}\nrealized_pnl={self._trade_stats['realized_pnl']:.8f}\nws_connected={self.ws.status.state == 'OK'}\nws_last_tick_age_ms={ws_age_ms}\nws_tick_count={self.ws.status.tick_count}\nws_reconnects={self.ws.status.reconnects}\nlast_ws_error={self.ws.status.last_error}"
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
