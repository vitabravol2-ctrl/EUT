from __future__ import annotations

import sys
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView, QSizePolicy)

from app.core.account_service import AccountService
from app.core.binance_client import BinanceClient, normalize_binance_error
from app.core.config import load_config, save_config
from app.core.filters import validate_order
from app.core.logger import AppLogger
from app.core.market_service import MarketService
from app.core.order_service import OrderService
from app.core.polling_manager import PollingManager
from app.core.runtime_state import RuntimeState
from app.core.runtime_fsm import RuntimeFSM
from app.core.formatting import format_age_ms
from app.core.spread_detector import SpreadDetector
from app.core.order_manager import OrderManager
from app.core.fill_tracker import FillTracker
from app.core.risk_guard import RiskGuard
from app.gui.settings_dialog import SettingsDialog
from app.gui.panels.log_panel import LogPanel
from app.gui.ui_constants import BUTTON_H, BUTTON_MIN_W, AUTH_FAILED_MSG



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('EUT v0.2.3 — DPI/Layout Lock + Connection Gate Fix')
        self.setMinimumSize(1280, 720)
        self.resize(1500, 900)
        self.logger = AppLogger(max_records=500)
        self.cfg = load_config()
        self.runtime = RuntimeState()
        self.fsm = RuntimeFSM()
        self.spread_detector = SpreadDetector()
        self.fill_tracker = FillTracker()
        self.risk_guard = RiskGuard()
        self._auth_error_logged = False
        self._last_market_log = None
        self._init_services()
        self._build_ui()
        self.polling = PollingManager(self.refresh_market, self.refresh_orders, self.refresh_balances, self.cfg['poll_interval_ms'], self.cfg['poll_interval_ms']*2, self.cfg['poll_interval_ms']*3, self)
        self._set_private_polling(False, '[AUTH] Account not connected, private polling paused')
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_timer.start(250)

    def _btn(self, text, fn):
        b = QPushButton(text)
        b.setMinimumHeight(BUTTON_H)
        b.setMaximumHeight(BUTTON_H + 2)
        b.setMinimumWidth(BUTTON_MIN_W)
        b.clicked.connect(fn)
        return b

    def _init_services(self):
        self.client = BinanceClient(self.cfg['api_key'], self.cfg['api_secret'], self.cfg['testnet'])
        self.market = MarketService(self.client, self.cfg['symbol'])
        self.account = AccountService(self.client)
        self.orders = OrderService(self.client, self.cfg['symbol'])
        self.order_manager = OrderManager(self.orders)

    def _build_ui(self):
        self.setStyleSheet('QWidget{background:#111317;color:#dfe7ef;font-size:12px;}QGroupBox{border:1px solid #2a2f38;border-radius:8px;margin-top:8px;padding:8px;}QPushButton{background:#242a33;padding:6px 10px;border-radius:6px;}QLineEdit,QComboBox,QTableWidget{background:#0d1117;border:1px solid #2a2f38;}QHeaderView::section{background:#1a1f27;color:#dfe7ef;padding:4px;border:1px solid #2a2f38;}')
        root = QWidget(); self.setCentralWidget(root); main = QVBoxLayout(root)
        main.addWidget(self._top_bar())
        splitter_v = QSplitter(Qt.Vertical)
        splitter_h = QSplitter(Qt.Horizontal)
        left = QWidget(); left.setMinimumWidth(360); lv = QVBoxLayout(left); lv.addWidget(self._market_panel()); lv.addWidget(self._spread_panel()); lv.addWidget(self._balance_panel()); lv.addStretch(1)
        center = QWidget(); cv = QVBoxLayout(center); cv.addWidget(self._orders_panel())
        right = QWidget(); right.setMinimumWidth(320); rv = QVBoxLayout(right); rv.addWidget(self._manual_panel()); rv.addWidget(self._order_activity_panel()); rv.addWidget(self._fsm_panel()); rv.addStretch(1)
        splitter_h.addWidget(left); splitter_h.addWidget(center); splitter_h.addWidget(right)
        splitter_h.setStretchFactor(0, 1); splitter_h.setStretchFactor(1, 2); splitter_h.setStretchFactor(2, 1)
        splitter_v.addWidget(splitter_h)
        splitter_v.addWidget(self._log_panel())
        splitter_v.setSizes([680, 170])
        main.addWidget(splitter_v)

    def _top_bar(self):
        g = QGroupBox('Runtime Status'); l = QGridLayout(g); self.s = {}
        keys = ['PUBLIC REST', 'ACCOUNT', 'POLLING', 'PRIVATE', 'TRADING', 'READONLY', 'SPREAD', 'RISK', 'LATENCY']
        for i, k in enumerate(keys):
            l.addWidget(QLabel(f'{k}:'), i // 5, (i % 5)*2)
            val = QLabel('-'); val.setMinimumWidth(90); self.s[k] = val; l.addWidget(val, i // 5, (i % 5)*2 + 1)
        self.settings_btn = self._btn('Settings', self.open_settings)
        l.addWidget(self.settings_btn, 2, 9)
        return g

    # panels omitted unchanged patterns
    def _market_panel(self):
        g = QGroupBox('Market'); f = QFormLayout(g); self.m = {}
        for k in ['Last','Bid','Ask','MID','Spread','Spread ticks','REST age']:
            w = QLabel('-'); w.setMinimumWidth(110); self.m[k] = w; f.addRow(k, w)
        row = QHBoxLayout()
        for t, fn in [('Refresh', self.refresh_market), ('Start Polling', self.start_polling), ('Stop Polling', self.stop_polling)]: row.addWidget(self._btn(t, fn))
        f.addRow(row)
        return g

    def _spread_panel(self):
        g=QGroupBox('Spread Status'); f=QFormLayout(g); self.sp={}
        for k in ['Spread','Ticks','Lifetime','Stable']:
            w=QLabel('-'); w.setMinimumWidth(100); self.sp[k]=w; f.addRow(k,w)
        return g

    def _balance_panel(self):
        g=QGroupBox('Balances'); f=QFormLayout(g); self.b={}
        for k in ['USDT Free','USDT Locked','EURI Free','EURI Locked','Estimated Total USDT']:
            w=QLabel('-'); w.setMinimumWidth(110); self.b[k]=w; f.addRow(k,w)
        self.balance_refresh_btn = self._btn('Refresh Balances', self.refresh_balances); f.addRow(self.balance_refresh_btn)
        return g

    def _manual_panel(self):
        g=QGroupBox('Manual Trading'); f=QFormLayout(g)
        self.side=QComboBox(); self.side.addItems(['BUY','SELL']); self.price=QLineEdit(); self.qty=QLineEdit(); self.total=QLabel('0')
        self.qty.textChanged.connect(self._update_total); self.price.textChanged.connect(self._update_total)
        f.addRow('Side', self.side); f.addRow('Price', self.price); f.addRow('Qty', self.qty); f.addRow('Total', self.total)
        row = QHBoxLayout(); self.buy_btn=self._btn('Place BUY', lambda: self.place('BUY')); self.sell_btn=self._btn('Place SELL', lambda: self.place('SELL')); row.addWidget(self.buy_btn); row.addWidget(self.sell_btn); f.addRow(row)
        return g

    def _order_activity_panel(self):
        g=QGroupBox('Order Activity'); f=QFormLayout(g); self.oa={}
        for k in ['Active order','Alive time','Queue age','Reprices count']:
            self.oa[k]=QLabel('-'); f.addRow(k,self.oa[k])
        return g

    def _orders_panel(self):
        g=QGroupBox('Open Orders'); v=QVBoxLayout(g); self.table=QTableWidget(0,8)
        self.table.setHorizontalHeaderLabels(['Order ID','Side','Price','Qty','Filled','Filled %','Status','Age'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self.table)
        bar = QHBoxLayout()
        for t, fn in [('Refresh', self.refresh_orders), ('Cancel Selected', self.cancel_selected), ('Cancel All', self.cancel_all)]: bar.addWidget(self._btn(t, fn))
        v.addLayout(bar)
        return g

    def _log_panel(self):
        g=QGroupBox('Logs'); v=QVBoxLayout(g); self.log_panel=LogPanel(500); self.log_panel.setMinimumHeight(140); self.log_panel.setMaximumHeight(180); self.log_panel.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont)); v.addWidget(self.log_panel)
        clear_btn = self._btn('Clear Logs', self.log_panel.clear); v.addWidget(clear_btn)
        self.logger.subscribe(self.log_panel.append_record)
        return g

    def _has_valid_keys(self): return bool(self.cfg.get('api_key','').strip()) and bool(self.cfg.get('api_secret','').strip())
    def _trading_allowed(self):
        return self.runtime.account_auth_state == 'CONNECTED' and not self.cfg.get('read_only', True) and self.cfg.get('trading_enabled') and self._has_valid_keys()
    def _set_private_polling(self, enabled: bool, reason: str = ''):
        self.polling.set_private_enabled(enabled)
        self.runtime.private_polling_state = 'RUNNING' if enabled else 'PAUSED'
        if reason: self.logger.log('AUTH', reason)

    def _handle_auth_failure(self, e):
        if self.runtime.account_auth_state != 'AUTH_ERROR':
            self.runtime.set_account_auth('AUTH_ERROR')
        self._set_private_polling(False)
        if not self._auth_error_logged:
            self.logger.log('AUTH', AUTH_FAILED_MSG)
            self._auth_error_logged = True

    def _apply_settings(self, values: dict): self.cfg.update(values); save_config(self.cfg); self._init_services()
    def open_settings(self): SettingsDialog(self.cfg, self._apply_settings, self._test_connection, self).show()

    def _test_connection(self, values: dict):
        try:
            self._apply_settings(values)
            self.account.balances(); self.runtime.set_account_auth('CONNECTED'); self._auth_error_logged = False
            self.refresh_balances(); self.refresh_orders(); self._set_private_polling(True); self.logger.log('INFO', 'Binance connected')
            return True, 'Connection OK'
        except Exception as e:
            self.runtime.set_account_auth('AUTH_ERROR')
            self._set_private_polling(False)
            self._handle_auth_failure(e)
            return False, normalize_binance_error(e)

    def refresh_market(self):
        try:
            t0=time.time(); s=self.market.snapshot(); self.runtime.mark_rest_update(); self.runtime.last_latency_ms=(time.time()-t0)*1000
        except Exception as e:
            self.runtime.mark_error(str(e)); self.logger.log('ERROR', f'market: {e}'); return
        mid=(s['bid']+s['ask'])/2 if s['ask'] and s['bid'] else 0
        self.m['Last'].setText(f"{s['last']:.4f}"); self.m['Bid'].setText(f"{s['bid']:.4f}"); self.m['Ask'].setText(f"{s['ask']:.4f}"); self.m['MID'].setText(f"{mid:.4f}")
        self.m['Spread'].setText(f"{s['spread']:.4f}"); self.m['Spread ticks'].setText(str(s['spread_ticks'])); self.m['REST age'].setText('0 ms')

    def refresh_balances(self):
        if self.runtime.account_auth_state != 'CONNECTED': return
        try: self.account.balances(); self.runtime.mark_balances_update()
        except Exception as e: self._handle_auth_failure(e)

    def refresh_orders(self):
        if self.runtime.account_auth_state != 'CONNECTED': return
        try: data=self.orders.open_orders(); self.runtime.mark_orders_update(); self.table.setRowCount(len(data))
        except Exception as e: self._handle_auth_failure(e); return
        now_ms = int(time.time() * 1000)
        for r,o in enumerate(data):
            filled=((float(o.get('executedQty',0))/max(float(o.get('origQty',0) or 1),1e-9))*100)
            age = format_age_ms(max(0, now_ms - int(o.get('time', now_ms))))
            vals=[o.get('orderId'),o.get('side'),o.get('price'),o.get('origQty'),o.get('executedQty'),f'{filled:.1f}%',o.get('status'),age]
            for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))

    def _tick_status(self):
        self.runtime.update_stale(3000)
        self.s['PUBLIC REST'].setText(self.runtime.public_rest_state); self.s['ACCOUNT'].setText(self.runtime.account_auth_state); self.s['POLLING'].setText(self.runtime.polling_state)
        self.s['PRIVATE'].setText(self.runtime.private_polling_state); self.s['TRADING'].setText('ENABLED' if self._trading_allowed() else 'DISABLED'); self.s['READONLY'].setText('ON' if self.cfg.get('read_only', True) else 'OFF')
        self.s['SPREAD'].setText(self.sp.get('Stable', QLabel('-')).text()); self.s['RISK'].setText('OK'); self.s['LATENCY'].setText(f"{int(self.runtime.last_latency_ms)} ms")
        self.buy_btn.setEnabled(self._trading_allowed()); self.sell_btn.setEnabled(self._trading_allowed())

    def _fsm_panel(self): g=QGroupBox('Runtime FSM'); f=QFormLayout(g); self.fsm_value = QLabel('-'); f.addRow('State', self.fsm_value); return g
    def place(self, side):
        if not self._trading_allowed(): self.logger.log('ERROR','Trading disabled/account not connected/read-only mode'); return
        ok,msg = validate_order(self.price.text(), self.qty.text(), tick_size='0.0001', step_size='0.1', min_qty='0.1', min_notional='5')
        if not ok: self.logger.log('ERROR', msg); return
        if QMessageBox.question(self, 'Confirm', f'Place {side} LIMIT?') != QMessageBox.Yes: return
        self.logger.log('ORDER', f'{side} LIMIT sent {self.orders.place_limit(side, self.qty.text(), self.price.text())}')

    def cancel_selected(self):
        row = self.table.currentRow()
        if row < 0 or self.runtime.account_auth_state != 'CONNECTED':
            return
        order_id = int(self.table.item(row, 0).text())
        self.orders.cancel(order_id)
        self.logger.log('ORDER', f'cancel order {order_id}')
        self.refresh_orders()

    def cancel_all(self):
        if self.runtime.account_auth_state != 'CONNECTED':
            return
        self.orders.cancel_all()
        self.logger.log('ORDER', 'cancel all orders')
        self.refresh_orders()
    def _update_total(self):
        try: self.total.setText(f"{float(self.price.text() or 0)*float(self.qty.text() or 0):.4f}")
        except Exception: self.total.setText('0')
    def start_polling(self):
        if self.polling.start(): self.runtime.set_polling(True); self.logger.log('INFO','Polling started')
    def stop_polling(self): self.polling.stop(); self.runtime.set_polling(False); self.logger.log('INFO','Polling stopped')

def run():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    w = MainWindow(); w.show(); sys.exit(app.exec())
