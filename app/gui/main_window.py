from __future__ import annotations

import sys
from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView

from app.core.account_service import AccountService
from app.core.async_runner import TaskRunner
from app.core.binance_client import BinanceAPIError, BinanceClient
from app.core.config import load_config, save_config
from app.core.execution_metrics import QueueQualityEstimator, SpreadStabilityAnalyzer
from app.core.filters import validate_order_from_exchange_info
from app.core.harvest_readiness import HarvestReadinessEngine
from app.core.logger import AppLogger
from app.core.market_service import MarketService
from app.core.order_service import OrderService
from app.core.polling_manager import PollingManager
from app.core.spread_stability_engine import ReadinessState, SpreadStabilityEngine
from app.core.runtime_state import RuntimeState
from app.core.ws_manager import WSManager
from app.gui.panels.log_panel import LogPanel
from app.gui.settings_dialog import SettingsDialog
from app.gui.ui_constants import *

DARK_STYLESHEET = "QWidget { background: #0b0f14; color: #e6edf3; }"

class TradeSettingsDialog(QDialog):
    def __init__(self, cfg: dict, on_save, parent=None):
        super().__init__(parent); self._on_save = on_save; self.setWindowTitle('Trade / Harvest Settings')
        l = QFormLayout(self)
        self.symbol = QLineEdit(str(cfg.get('symbol', 'EURIUSDT')))
        self.mode = QLabel('MANUAL')
        self.side = QComboBox(); self.side.addItems(['BUY', 'SELL']); self.side.setCurrentText(str(cfg.get('manual_side', 'BUY')))
        self.order_quote = QLineEdit(str(cfg.get('order_quote_usdt', 10)))
        self.qty = QLineEdit(str(cfg.get('manual_qty', '0')))
        self.price = QLineEdit(str(cfg.get('manual_price', '0')))
        self.min_spread_ticks = QLineEdit(str(cfg.get('min_spread_ticks', 2))); self.stable_ms = QLineEdit(str(cfg.get('stable_ms', 3000)))
        self.max_order_age = QLineEdit(str(cfg.get('max_order_age_sec', 30))); self.max_active_orders = QLineEdit(str(cfg.get('max_active_orders', 1)))
        self.risk_guard = QCheckBox('Enabled'); self.risk_guard.setChecked(bool(cfg.get('risk_guard_enabled', False)))
        for n,w in [('Symbol',self.symbol),('Mode',self.mode),('Side',self.side),('Order quote USDT',self.order_quote),('Qty EURI',self.qty),('Price',self.price),('Min spread ticks',self.min_spread_ticks),('Stable ms',self.stable_ms),('Max order age sec',self.max_order_age),('Max active orders',self.max_active_orders),('Risk guard enabled',self.risk_guard)]: l.addRow(n,w)
        row=QHBoxLayout(); row.addWidget(QPushButton('Save', clicked=self._save)); row.addWidget(QPushButton('Close', clicked=self.reject)); l.addRow(row)
    def _save(self):
        self._on_save({'symbol': self.symbol.text().strip() or 'EURIUSDT', 'manual_side': self.side.currentText(), 'order_quote_usdt': float(self.order_quote.text() or 10), 'manual_qty': self.qty.text().strip(), 'manual_price': self.price.text().strip(), 'min_spread_ticks': int(self.min_spread_ticks.text() or 2), 'stable_ms': int(self.stable_ms.text() or 3000), 'max_order_age_sec': int(self.max_order_age.text() or 30), 'max_active_orders': int(self.max_active_orders.text() or 1), 'risk_guard_enabled': self.risk_guard.isChecked()}); self.accept()

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
        super().__init__(parent); self.setWindowTitle('All Data'); l=QVBoxLayout(self)
        for g in ['Account','Market','Harvest','Execution','Runtime','Filters']:
            box=QGroupBox(g); bl=QVBoxLayout(box); bl.addWidget(QLabel(main._all_data_text(g))); l.addWidget(box)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('EUT v0.3.6 — Cockpit Repair'); self.setMinimumSize(1200,700); self.setStyleSheet(DARK_STYLESHEET); self.setFont(QFont('', APP_FONT_PT))
        self.logger=AppLogger(max_records=500,dedupe_seconds=30); self.cfg=load_config(); self.runtime=RuntimeState(); self.ws=WSManager(enabled=False)
        self._last_market_snapshot={}; self._last_open_orders=[]; self._balances={}; self._status_badges={}; self._orders_by_id={}; self._selected_order_id=None
        self._spread_analyzer=SpreadStabilityAnalyzer(); self._queue_estimator=QueueQualityEstimator(); self._harvest_engine=HarvestReadinessEngine(); self._private_ok=False
        self._spread_engine=SpreadStabilityEngine(Decimal('0.0001'), int(self.cfg.get('min_spread_ticks',2)), int(self.cfg.get('stable_ms',3000)))
        self._spread_metrics=None; self._last_spread_readiness=None
        self._init_services(); self._build_ui(); self._sync_trade_settings_labels()
        self.task_runner=TaskRunner(4,self); self.task_runner.signals.success.connect(self._on_task_success); self.task_runner.signals.error.connect(self._on_task_error); self.task_runner.signals.finished.connect(self.task_runner.finish)
        self.polling=PollingManager(self.refresh_market,self.refresh_orders,self.refresh_balances,300,3000,3000,self)
        self._status_timer=QTimer(self); self._status_timer.timeout.connect(self._tick_status); self._status_timer.start(300); QTimer.singleShot(50,self._startup_connect_flow)
    def _init_services(self):
        self.client=BinanceClient(self.cfg['api_key'],self.cfg['api_secret'],self.cfg['testnet'],self.cfg.get('request_timeout_sec',3)); self.market=MarketService(self.client,self.cfg['symbol']); self.account=AccountService(self.client); self.orders=OrderService(self.client,self.cfg['symbol'])
    def _build_ui(self):
        root=QWidget(); self.setCentralWidget(root); main=QVBoxLayout(root); top=QGroupBox('Status Strip'); l=QHBoxLayout(top)
        for k in ['SYSTEM','TRADING','EURI','USDT','SPREAD','HARVEST','ORDERS','RISK']:
            b=QLabel(f'{k} -'); self._status_badges[k]=b; l.addWidget(b)
        main.addWidget(top)
        split=QSplitter(Qt.Horizontal)
        left=QGroupBox('Trade / Harvest Settings'); fl=QFormLayout(left); self.ts_symbol=QLabel(); self.ts_mode=QLabel('MANUAL'); self.ts_side=QLabel(); self.ts_quote=QLabel(); self.ts_qty=QLabel(); self.ts_price=QLabel(); self.ts_min=QLabel(); self.ts_stable=QLabel(); self.ts_age=QLabel(); self.ts_active=QLabel(); self.ts_risk=QLabel()
        for n,w in [('Symbol',self.ts_symbol),('Mode',self.ts_mode),('Side',self.ts_side),('Order quote USDT',self.ts_quote),('Qty EURI',self.ts_qty),('Price',self.ts_price),('Min spread ticks',self.ts_min),('Stable ms',self.ts_stable),('Max order age sec',self.ts_age),('Max active orders',self.ts_active),('Risk guard',self.ts_risk)]: fl.addRow(n,w)
        fl.addRow(self._btn('Edit Settings', self.open_trade_settings))
        center=QGroupBox('Open Orders'); cl=QVBoxLayout(center); self.table=QTableWidget(0,8); self.table.setHorizontalHeaderLabels(['ID','Side','Price','Qty','Filled','%','Status','Age']); self.table.itemSelectionChanged.connect(self._on_order_selected); self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive); cl.addWidget(self.table); self.no_orders=QLabel('No open orders'); cl.addWidget(self.no_orders)
        spread_box=QGroupBox('Spread Stability'); sl=QFormLayout(spread_box)
        self.ss_ticks=QLabel('-'); self.ss_lifetime=QLabel('-'); self.ss_bid=QLabel('-'); self.ss_ask=QLabel('-'); self.ss_ratio=QLabel('-'); self.ss_collapse=QLabel('0'); self.ss_readiness=QLabel('NOT_READY')
        for n,w in [('Spread ticks',self.ss_ticks),('Spread lifetime',self.ss_lifetime),('Bid stable',self.ss_bid),('Ask stable',self.ss_ask),('Stable ratio',self.ss_ratio),('Collapse count',self.ss_collapse),('Readiness',self.ss_readiness)]: sl.addRow(n,w)
        right=QGroupBox('Actions'); rl=QVBoxLayout(right)
        for t,f in [('Manual Order',self.open_manual_order),('Cancel Selected',self.cancel_selected),('Cancel All',self.cancel_all),('All Data',self.open_all_data),('Settings',self.open_settings)]: rl.addWidget(self._btn(t,f))
        self.cancel_selected_btn=right.findChildren(QPushButton)[1]; self.cancel_all_btn=right.findChildren(QPushButton)[2]
        split.addWidget(left); split.addWidget(center); split.addWidget(spread_box); split.addWidget(right); main.addWidget(split)
        logs=QGroupBox('Logs'); ll=QVBoxLayout(logs); self.log_panel=LogPanel(500); self.logger.subscribe(self.log_panel.append_record); ll.addWidget(self.log_panel); main.addWidget(logs)
    def _btn(self,t,f): b=QPushButton(t); b.clicked.connect(f); return b
    def _startup_connect_flow(self): self.refresh_market(True); self.refresh_balances(True); self.refresh_orders(True); self.start_polling()
    def open_settings(self): self.settings_dialog=SettingsDialog(self.cfg,self.apply_settings,self.test_connection,self); self.settings_dialog.show()
    def open_trade_settings(self): self.trade_settings_dialog=TradeSettingsDialog(self.cfg,self.apply_trade_settings,self); self.trade_settings_dialog.show()
    def open_manual_order(self): self.manual_order_dialog=ManualOrderDialog(self,self); self.manual_order_dialog.show()
    def open_all_data(self): self.all_data_dialog=AllDataDialog(self,self); self.all_data_dialog.show()
    def apply_settings(self,v): self.cfg.update(v); save_config(self.cfg)
    def apply_trade_settings(self,v): self.cfg.update(v); save_config(self.cfg); self._sync_trade_settings_labels()
    def test_connection(self,v): return True,'ok'
    def refresh_market(self,force=False): self.task_runner.run_task('market', lambda: self.market.snapshot())
    def refresh_balances(self,force=False): self.task_runner.run_task('balances', lambda: self.account.balances(Decimal(str(self._last_market_snapshot.get('last',0) or 0))))
    def refresh_orders(self,force=False): self.task_runner.run_task('orders', self.orders.open_orders)
    def _on_task_success(self,name,payload):
        if name=='market':
            self._last_market_snapshot=dict(payload)
            metrics=self._spread_engine.observe(Decimal(str(payload.get('bid',0))), Decimal(str(payload.get('ask',0))), float(payload.get('latency_ms',0)))
            self._spread_metrics=metrics
            self.ss_ticks.setText(f"{metrics.snapshot.spread_ticks:.2f}")
            self.ss_lifetime.setText(f"{metrics.state.spread_lifetime_ms}ms")
            self.ss_bid.setText(f"{metrics.state.best_bid_unchanged_ms}ms")
            self.ss_ask.setText(f"{metrics.state.best_ask_unchanged_ms}ms")
            self.ss_ratio.setText(f"{metrics.state.stable_spread_ratio*100:.0f}%")
            self.ss_collapse.setText(str(metrics.state.spread_collapse_count))
            self.ss_readiness.setText(metrics.state.readiness.value)
            if metrics.state.readiness != self._last_spread_readiness:
                self.logger.log('INFO', f"[SPREAD] {metrics.state.readiness.value} spread={metrics.snapshot.spread_ticks:.2f} lifetime={metrics.state.spread_lifetime_ms}ms")
                self._last_spread_readiness=metrics.state.readiness
            if metrics.state.spread_collapse_count > 0 and metrics.state.readiness == ReadinessState.NOT_READY:
                self.logger.log('INFO', '[SPREAD] COLLAPSE')
        elif name=='balances': self._balances=payload; self._private_ok=True
        elif name=='orders': self._last_open_orders=payload; self._private_ok=True; self._render_orders(payload); self.logger.log('INFO', f"[ORDERS] refreshed count={len(payload)}")
    def _on_task_error(self,name,err):
        self.logger.log('ERROR', f'{name}: {err}');
        if name in ('orders','balances'): self._private_ok=False
    def _render_orders(self,payload):
        self._orders_by_id={int(o.get('orderId')):o for o in payload if o.get('orderId')}; self.table.setRowCount(len(payload)); self.no_orders.setVisible(len(payload)==0)
        for r,o in enumerate(payload):
            vals=[o.get('orderId'),o.get('side'),o.get('price'),o.get('origQty'),o.get('executedQty'),'0%',o.get('status'),'-']
            for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))
    def _tick_status(self):
        self._status_badges['SYSTEM'].setText('SYSTEM OK'); self._status_badges['TRADING'].setText(f"TRADING {'ON' if self.cfg.get('trading_enabled',False) else 'OFF'}")
        self._status_badges['EURI'].setText(f"EURI {self._fmt_bal('EURI_free')} / locked {self._fmt_bal('EURI_locked')}")
        self._status_badges['USDT'].setText(f"USDT {self._fmt_bal('USDT_free')} / locked {self._fmt_bal('USDT_locked')}")
        spread=(self._spread_metrics.state.readiness.value if self._spread_metrics else 'NOT_READY'); self._status_badges['SPREAD'].setText(f'SPREAD {spread}')
        self._status_badges['HARVEST'].setText('HARVEST READY' if self._private_ok else 'HARVEST NOT_READY')
        self._status_badges['ORDERS'].setText(f'ORDERS {len(self._last_open_orders)}'); self._status_badges['RISK'].setText(f"RISK {'BLOCKED' if self.cfg.get('risk_guard_enabled') else 'OK'}")
        enabled=self._private_ok; self.cancel_all_btn.setEnabled(enabled); self.cancel_selected_btn.setEnabled(enabled and self._selected_order_id is not None)
    def _fmt_bal(self,k):
        if not self._private_ok and not self._balances: return '-'
        return f"{Decimal(str(self._balances.get(k,0))):.2f}"
    def _on_order_selected(self):
        it=self.table.item(self.table.currentRow(),0); self._selected_order_id=int(it.text()) if it else None
    def _market_bid(self): return f"{Decimal(str(self._last_market_snapshot.get('bid',0))):.8f}"
    def _market_ask(self): return f"{Decimal(str(self._last_market_snapshot.get('ask',0))):.8f}"
    def _balance_euri(self): return f"{Decimal(str(self._balances.get('EURI_free',0))):.8f}"
    def _sync_trade_settings_labels(self):
        self.ts_symbol.setText(str(self.cfg.get('symbol','EURIUSDT'))); self.ts_side.setText(str(self.cfg.get('manual_side','BUY'))); self.ts_quote.setText(str(self.cfg.get('order_quote_usdt',10))); self.ts_qty.setText(str(self.cfg.get('manual_qty','0'))); self.ts_price.setText(str(self.cfg.get('manual_price','0'))); self.ts_min.setText(str(self.cfg.get('min_spread_ticks',2))); self.ts_stable.setText(str(self.cfg.get('stable_ms',3000))); self.ts_age.setText(str(self.cfg.get('max_order_age_sec',30))); self.ts_active.setText(str(self.cfg.get('max_active_orders',1))); self.ts_risk.setText('ON' if self.cfg.get('risk_guard_enabled',False) else 'OFF')
    def _get_exchange_info(self): return self.client.get_exchange_info(self.cfg['symbol'])
    def place(self, side, price, qty):
        if not self._private_ok and not self.cfg.get('api_key'): self.logger.log('ERROR','[ORDER] rejected reason=private api unavailable'); return
        try:
            ok,msg=validate_order_from_exchange_info(price,qty,self._get_exchange_info())
            if not ok: self.logger.log('ERROR', f'[ORDER] rejected reason={msg}'); return
            self.logger.log('INFO', f'[ORDER] {side} LIMIT sent price={price} qty={qty}')
            resp=self.orders.place_limit(side,qty,price); self.logger.log('INFO', f"[ORDER] accepted id={resp.get('orderId')}")
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
    def _all_data_text(self, group): return group

def run():
    app=QApplication(sys.argv); w=MainWindow(); w.show(); sys.exit(app.exec())
