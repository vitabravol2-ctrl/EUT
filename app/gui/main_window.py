from __future__ import annotations

import sys
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget, QHeaderView)

from app.core.account_service import AccountService
from app.core.binance_client import BinanceClient
from app.core.config import load_config, save_config
from app.core.filters import validate_order
from app.core.logger import AppLogger
from app.core.market_service import MarketService
from app.core.order_service import OrderService
from app.core.polling_manager import PollingManager
from app.core.runtime_state import RuntimeState
from app.core.runtime_fsm import FsmState, RuntimeFSM
from app.core.spread_detector import SpreadDetector
from app.core.order_manager import OrderManager
from app.core.fill_tracker import FillTracker
from app.core.risk_guard import RiskGuard

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('EUT v0.2.0 — Deterministic Spread Harvester')
        self.logger = AppLogger()
        self.cfg = load_config()
        self.runtime = RuntimeState()
        self.fsm = RuntimeFSM()
        self.spread_detector = SpreadDetector()
        self.fill_tracker = FillTracker()
        self.risk_guard = RiskGuard()
        self._init_services()
        self._build_ui()
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_timer.start(250)
        self.polling = PollingManager(self.refresh_market, self.refresh_orders, self.refresh_balances, self.cfg['poll_interval_ms'], self.cfg['poll_interval_ms']*2, self.cfg['poll_interval_ms']*3, self)

    def _init_services(self):
        self.client = BinanceClient(self.cfg['api_key'], self.cfg['api_secret'], self.cfg['testnet'])
        self.market = MarketService(self.client, self.cfg['symbol'])
        self.account = AccountService(self.client)
        self.orders = OrderService(self.client, self.cfg['symbol'])
        self.order_manager = OrderManager(self.orders)

    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root); main = QVBoxLayout(root)
        self.setStyleSheet('QWidget{background:#111317;color:#dfe7ef;font-size:12px;}QGroupBox{border:1px solid #2a2f38;border-radius:8px;margin-top:8px;padding:8px;}QPushButton{background:#242a33;padding:4px 8px;border-radius:6px;}QLineEdit,QComboBox,QTextEdit,QTableWidget{background:#0d1117;border:1px solid #2a2f38;}')
        main.addWidget(self._top_bar())
        split_v = QSplitter(Qt.Vertical)
        split_h = QSplitter(Qt.Horizontal)
        left = QWidget(); lv = QVBoxLayout(left); lv.addWidget(self._market_panel()); lv.addWidget(self._spread_panel()); lv.addWidget(self._fsm_panel()); lv.addWidget(self._balance_panel()); lv.addWidget(self._quick_stats_panel())
        split_h.addWidget(left); split_h.addWidget(self._manual_panel()); split_h.addWidget(self._orders_panel()); split_h.addWidget(self._order_activity_panel())
        split_h.setStretchFactor(0,2); split_h.setStretchFactor(1,2); split_h.setStretchFactor(2,3)
        split_v.addWidget(split_h); split_v.addWidget(self._log_panel()); split_v.setStretchFactor(0,4); split_v.setStretchFactor(1,1)
        main.addWidget(split_v)

    def _top_bar(self):
        g = QGroupBox('Runtime Status'); l = QGridLayout(g); self.s={}
        for i, k in enumerate(['FSM state','REST status','Polling','Spread status','Connection','Latency','REST age','Trading','Orders age','Risk Guard']):
            l.addWidget(QLabel(k), i//6, (i%6)*2); v = QLabel('-'); self.s[k]=v; l.addWidget(v, i//6, (i%6)*2+1)
        self.s['Risk Guard'].setText('OK')
        return g
    def _market_panel(self):
        g=QGroupBox('Market'); f=QFormLayout(g); self.m={}
        for k in ['Last','Bid','Ask','MID','Spread','Spread ticks']:
            w=QLabel('-'); self.m[k]=w; f.addRow(k,w)
        for t,fn in [('Refresh',self.refresh_market),('Start',self.start_polling),('Stop',self.stop_polling)]:
            b=QPushButton(t); b.clicked.connect(fn); f.addRow(b)
        return g

    def _spread_panel(self):
        g=QGroupBox('Spread Status'); f=QFormLayout(g); self.sp={}
        for k in ['spread','spread ticks','spread lifetime','stable']:
            self.sp[k]=QLabel('-'); f.addRow(k,self.sp[k])
        return g

    def _fsm_panel(self):
        g=QGroupBox('Runtime FSM'); f=QFormLayout(g); self.fsm_w={}
        for k in ['current state','current cycle','last transition','last error']:
            self.fsm_w[k]=QLabel('-'); f.addRow(k,self.fsm_w[k])
        return g

    def _order_activity_panel(self):
        g=QGroupBox('Order Activity'); f=QFormLayout(g); self.oa={}
        for k in ['active order','alive time','queue age','reprices count']:
            self.oa[k]=QLabel('-'); f.addRow(k,self.oa[k])
        return g

    def _balance_panel(self):
        g=QGroupBox('Balances'); f=QFormLayout(g); self.b={}
        for k in ['USDT Free','USDT Locked','EURI Free','EURI Locked','Estimated Total USDT']:
            self.b[k]=QLabel('-'); f.addRow(k,self.b[k])
        return g
    def _quick_stats_panel(self):
        g=QGroupBox('Quick Stats'); f=QFormLayout(g); self.q={}
        for k in ['Current spread','Spread ticks','Bid pressure','Ask pressure','REST cycles/sec','Orders count']:
            self.q[k]=QLabel('-'); f.addRow(k,self.q[k])
        return g
    def _manual_panel(self):
        g=QGroupBox('Manual Trading Panel'); f=QFormLayout(g)
        self.side=QComboBox(); self.side.addItems(['BUY','SELL']); self.price=QLineEdit(); self.qty=QLineEdit(); self.total=QLabel('0')
        self.read_only=QCheckBox('Read Only'); self.read_only.setChecked(self.cfg.get('read_only',True)); self.trading_enabled=QCheckBox('Trading Enabled')
        self.qty.textChanged.connect(self._update_total); self.price.textChanged.connect(self._update_total)
        self.poll_ms=QLineEdit(str(self.cfg['poll_interval_ms']))
        f.addRow('Side',self.side); f.addRow('Price',self.price); f.addRow('Qty',self.qty); f.addRow('Total',self.total); f.addRow('Polling ms',self.poll_ms); f.addRow(self.read_only,self.trading_enabled)
        for t,s in [('Place BUY','BUY'),('Place SELL','SELL')]:
            b=QPushButton(t); b.clicked.connect(lambda _, x=s: self.place(x)); f.addRow(b)
        sv=QPushButton('Save Config'); sv.clicked.connect(self.save_keys); f.addRow(sv)
        return g
    def _orders_panel(self):
        g=QGroupBox('Open Orders'); v=QVBoxLayout(g); self.table=QTableWidget(0,8)
        self.table.setHorizontalHeaderLabels(['Order ID','Side','Price','Qty','Filled','Filled %','Status','Time'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive); self.table.setSortingEnabled(True)
        v.addWidget(self.table)
        return g
    def _log_panel(self):
        g=QGroupBox('Logs'); v=QVBoxLayout(g); self.logs=QTextEdit(); self.logs.setReadOnly(True); v.addWidget(self.logs)
        self.logger.subscribe(self._append_log); return g
    def _append_log(self, rec):
        colors={'INFO':'#8ab4f8','MARKET':'#6ee7b7','ORDER':'#fbbf24','ERROR':'#f87171','SYSTEM':'#c4b5fd'}
        cursor=self.logs.textCursor(); auto=self.logs.verticalScrollBar().value()==self.logs.verticalScrollBar().maximum()
        self.logs.append(f"<span style='color:{colors.get(rec.level,'#e5e5e5')}'>[{rec.ts}] [{rec.level}] {rec.message}</span>")
        if auto: self.logs.verticalScrollBar().setValue(self.logs.verticalScrollBar().maximum())

    def save_keys(self):
        self.cfg.update({'read_only':self.read_only.isChecked(),'trading_enabled':self.trading_enabled.isChecked(),'poll_interval_ms':int(self.poll_ms.text() or '1000')})
        save_config(self.cfg); self.polling.set_intervals(self.cfg['poll_interval_ms'], self.cfg['poll_interval_ms']*2, self.cfg['poll_interval_ms']*3)

    def refresh_market(self):
        try:
            t0=time.time(); s=self.market.snapshot(); self.runtime.mark_rest_update(); self.runtime.last_latency_ms=(time.time()-t0)*1000
            mid=(s['bid']+s['ask'])/2 if s['ask'] and s['bid'] else 0
            self.m['Last'].setText(f"{s['last']:.4f}"); self.m['Bid'].setText(f"{s['bid']:.4f}"); self.m['Ask'].setText(f"{s['ask']:.4f}"); self.m['MID'].setText(f"{mid:.4f}")
            self.m['Spread'].setText(f"{s['spread']:.4f}"); self.m['Spread ticks'].setText(str(s['spread_ticks']))
            spread_status = self.spread_detector.evaluate(s['bid'], s['ask'])
            self.sp['spread'].setText(f"{spread_status.spread:.4f}"); self.sp['spread ticks'].setText(str(spread_status.spread_ticks)); self.sp['spread lifetime'].setText(f"{spread_status.lifetime_ms} ms"); self.sp['stable'].setText('stable' if spread_status.is_stable else 'unstable')
            self.q['Current spread'].setText(f"{s['spread']:.4f}"); self.q['Spread ticks'].setText(str(s['spread_ticks'])); self.q['REST cycles/sec'].setText(str(self.runtime.rest_cycles_per_sec()))
            self.s['Spread status'].setText('STABLE' if spread_status.is_stable else 'UNSTABLE')
            self._run_fsm(spread_status)
        except Exception as e:
            self.runtime.mark_error(str(e)); self.logger.log('ERROR', f'market: {e}')
    def refresh_balances(self):
        try:
            b=self.account.balances(); self.runtime.mark_balances_update()
            self.b['USDT Free'].setText(str(b['USDT_free'])); self.b['USDT Locked'].setText(str(b['USDT_locked'])); self.b['EURI Free'].setText(str(b['EURI_free'])); self.b['EURI Locked'].setText(str(b['EURI_locked'])); self.b['Estimated Total USDT'].setText(str(b['USDT_free']+b['USDT_locked']))
        except Exception as e: self.logger.log('ERROR',f'balances: {e}')
    def refresh_orders(self):
        try:
            data=self.orders.open_orders(); self.runtime.mark_orders_update(); self.table.setRowCount(len(data)); self.q['Orders count'].setText(str(len(data)))
            for r,o in enumerate(data):
                filled=((float(o.get('executedQty',0))/max(float(o.get('origQty',0) or 1),1e-9))*100)
                vals=[o.get('orderId'),o.get('side'),o.get('price'),o.get('origQty'),o.get('executedQty'),f'{filled:.1f}%',o.get('status'),time.strftime('%H:%M:%S', time.localtime((o.get('time',0))/1000))]
                for c,v in enumerate(vals):
                    it=QTableWidgetItem(str(v)); self.table.setItem(r,c,it)
                if str(o.get('side'))=='BUY':
                    for c in range(8): self.table.item(r,c).setBackground(QColor('#0f2a1f'))
                else:
                    for c in range(8): self.table.item(r,c).setBackground(QColor('#2a1616'))
        except Exception as e: self.logger.log('ERROR',f'orders: {e}')
    def _tick_status(self):
        self.runtime.update_stale(3000)
        self.s['Connection'].setText(self.runtime.connection_state); self.s['FSM state'].setText(self.fsm.state.value); self.s['Polling'].setText(self.runtime.polling_state)
        self.s['Latency'].setText(f"{int(self.runtime.last_latency_ms)} ms"); self.s['REST age'].setText(f"{self.runtime.age_ms(self.runtime.last_rest_update_ts)} ms")
        self.s['Trading'].setText('ENABLED' if self.trading_enabled.isChecked() else 'DISABLED'); self.s['REST status'].setText(self.runtime.rest_status); self.s['Orders age'].setText(f"{self.runtime.age_ms(self.runtime.last_orders_update_ts)} ms")
        self.fsm_w['current state'].setText(self.fsm.state.value); self.fsm_w['current cycle'].setText(str(self.fsm.cycle)); self.fsm_w['last transition'].setText(self.fsm.last_transition); self.fsm_w['last error'].setText(self.fsm.last_error)
        active_id = self.order_manager.active_order.get('orderId') if self.order_manager.active_order else '-'
        self.oa['active order'].setText(str(active_id)); self.oa['alive time'].setText(f"{self.order_manager.alive_time_ms()} ms"); self.oa['queue age'].setText(f"{self.order_manager.alive_time_ms()} ms"); self.oa['reprices count'].setText(str(self.order_manager.reprices_count))
    def place(self, side):
        if not self.trading_enabled.isChecked() or self.read_only.isChecked(): self.logger.log('ERROR','Trading disabled/read-only mode'); return
        ok,msg = validate_order(self.price.text(), self.qty.text(), tick_size='0.0001', step_size='0.1', min_qty='0.1', min_notional='5')
        if not ok: self.logger.log('ERROR', msg); return
        if QMessageBox.question(self, 'Confirm', f'Place {side} LIMIT?') != QMessageBox.Yes: return
        self.logger.log('ORDER', f'{side} LIMIT sent {self.orders.place_limit(side, self.qty.text(), self.price.text())}')
    def _update_total(self):
        try: self.total.setText(f"{float(self.price.text() or 0)*float(self.qty.text() or 0):.4f}")
        except Exception: self.total.setText('0')
    def start_polling(self):
        if self.polling.start(): self.runtime.set_polling(True); self.logger.log('SYSTEM','Polling started')
    def stop_polling(self):
        self.polling.stop(); self.runtime.set_polling(False); self.logger.log('SYSTEM','Polling stopped')

def run():
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec())
