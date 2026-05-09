from __future__ import annotations

import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget)

from app.core.account_service import AccountService
from app.core.binance_client import BinanceClient
from app.core.config import load_config, save_config
from app.core.filters import validate_order
from app.core.logger import AppLogger
from app.core.market_service import MarketService
from app.core.order_service import OrderService


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('EUT v0.1.0 — REST Manual Trading Cockpit')
        self.resize(1400, 900)
        self.logger = AppLogger()
        self.cfg = load_config()
        self.client = BinanceClient(self.cfg['api_key'], self.cfg['api_secret'], self.cfg['testnet'])
        self.market = MarketService(self.client, self.cfg['symbol'])
        self.account = AccountService(self.client)
        self.orders = OrderService(self.client, self.cfg['symbol'])
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_market)
        self._build_ui()

    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        main = QVBoxLayout(root)
        self.setStyleSheet('QWidget{background:#181a20;color:#e5e5e5;} QGroupBox{border:1px solid #333;border-radius:8px;margin-top:8px;padding:8px;} QPushButton{background:#2b3139;padding:6px;border-radius:6px;} QLineEdit,QComboBox,QTextEdit,QTableWidget{background:#101217;border:1px solid #2c2f36;}')

        conn = self._connection_panel(); main.addWidget(conn)
        split_h = QSplitter(Qt.Horizontal)
        left = QWidget(); lv = QVBoxLayout(left)
        lv.addWidget(self._market_panel()); lv.addWidget(self._balance_panel()); lv.addWidget(self._manual_panel())
        right = self._orders_panel()
        split_h.addWidget(left); split_h.addWidget(right); split_h.setStretchFactor(0, 2); split_h.setStretchFactor(1, 3)
        main.addWidget(split_h, 1)
        main.addWidget(self._log_panel(), 1)

    def _connection_panel(self):
        g = QGroupBox('Connection'); l = QGridLayout(g)
        self.api_key = QLineEdit(self.cfg['api_key']); self.api_secret = QLineEdit(self.cfg['api_secret']); self.api_secret.setEchoMode(QLineEdit.Password)
        self.testnet = QCheckBox('Testnet'); self.testnet.setChecked(self.cfg['testnet'])
        self.read_only = QCheckBox('Read Only Mode'); self.read_only.setChecked(self.cfg.get('read_only', True))
        self.trading_enabled = QCheckBox('Trading Enabled'); self.trading_enabled.setChecked(False)
        self.status = QLabel('DISCONNECTED')
        bsave = QPushButton('Save Keys'); bsave.clicked.connect(self.save_keys)
        btest = QPushButton('Test Connection'); btest.clicked.connect(self.test_conn)
        l.addWidget(QLabel('API Key'),0,0); l.addWidget(self.api_key,0,1); l.addWidget(QLabel('API Secret'),0,2); l.addWidget(self.api_secret,0,3)
        l.addWidget(self.testnet,1,0); l.addWidget(self.read_only,1,1); l.addWidget(self.trading_enabled,1,2); l.addWidget(self.status,1,3)
        l.addWidget(bsave,2,2); l.addWidget(btest,2,3)
        return g

    def _market_panel(self):
        g = QGroupBox('Market EURIUSDT'); f = QFormLayout(g); self.m = {}
        for k in ['Last Price','Best Bid','Bid Qty','Best Ask','Ask Qty','Spread','Spread Ticks','REST Update Age']:
            lb = QLabel('-'); self.m[k]=lb; f.addRow(k, lb)
        row = QHBoxLayout();
        for txt, fn in [('Refresh Market', self.refresh_market), ('Start Polling', self.start_polling), ('Stop Polling', self.stop_polling)]:
            b = QPushButton(txt); b.clicked.connect(fn); row.addWidget(b)
        f.addRow(row); return g

    def _balance_panel(self):
        g=QGroupBox('Balances'); f=QFormLayout(g); self.b={}
        for k in ['USDT Free','USDT Locked','EURI Free','EURI Locked','Estimated Total USDT']:
            lb=QLabel('-'); self.b[k]=lb; f.addRow(k,lb)
        btn=QPushButton('Refresh Balances'); btn.clicked.connect(self.refresh_balances); f.addRow(btn); return g

    def _manual_panel(self):
        g=QGroupBox('Manual LIMIT Order'); f=QFormLayout(g)
        self.side = QComboBox(); self.side.addItems(['BUY','SELL'])
        self.price = QLineEdit(); self.qty = QLineEdit(); self.total = QLabel('0')
        self.qty.textChanged.connect(self._update_total); self.price.textChanged.connect(self._update_total)
        f.addRow('Side', self.side); f.addRow('Order Type', QLabel('LIMIT ONLY')); f.addRow('Time In Force', QLabel('GTC')); f.addRow('Price', self.price); f.addRow('Quantity', self.qty); f.addRow('Total USDT', self.total)
        row=QHBoxLayout()
        for txt, side in [('Place BUY','BUY'),('Place SELL','SELL')]:
            b=QPushButton(txt); b.clicked.connect(lambda _, s=side:self.place(s)); row.addWidget(b)
        c1=QPushButton('Cancel Selected'); c1.clicked.connect(self.cancel_selected)
        c2=QPushButton('Cancel All EURIUSDT'); c2.clicked.connect(self.cancel_all)
        f.addRow(row); f.addRow(c1,c2); return g

    def _orders_panel(self):
        g=QGroupBox('Open Orders'); v=QVBoxLayout(g)
        self.table = QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['Order ID','Side','Price','Qty','Filled','Status','Time'])
        v.addWidget(self.table)
        row=QHBoxLayout()
        for txt, fn in [('Refresh Orders', self.refresh_orders), ('Cancel Selected', self.cancel_selected), ('Cancel All', self.cancel_all)]:
            b=QPushButton(txt); b.clicked.connect(fn); row.addWidget(b)
        v.addLayout(row); return g

    def _log_panel(self):
        g=QGroupBox('Logs'); v=QVBoxLayout(g); self.logs=QTextEdit(); self.logs.setReadOnly(True); v.addWidget(self.logs)
        self.logger.subscribe(lambda rec:self.logs.append(f"[{rec.ts}] [{rec.level}] {rec.message}"))
        return g

    def save_keys(self):
        self.cfg.update({'api_key': self.api_key.text().strip(),'api_secret': self.api_secret.text().strip(),'testnet': self.testnet.isChecked(),'read_only': self.read_only.isChecked(),'trading_enabled': self.trading_enabled.isChecked()})
        save_config(self.cfg); self.logger.log('INFO','Config saved')

    def test_conn(self):
        try:
            self.client = BinanceClient(self.api_key.text().strip(), self.api_secret.text().strip(), self.testnet.isChecked())
            self.account = AccountService(self.client); self.market = MarketService(self.client, 'EURIUSDT'); self.orders = OrderService(self.client, 'EURIUSDT')
            _ = self.client.get_exchange_info('EURIUSDT')
            self.status.setText('CONNECTED'); self.logger.log('INFO','Connected')
        except Exception as e:
            self.status.setText('DISCONNECTED'); self.logger.log('ERROR',f'Connection failed: {e}')

    def refresh_market(self):
        try:
            s=self.market.snapshot();
            vals=[s['last'],s['bid'],s['bid_qty'],s['ask'],s['ask_qty'],s['spread'],s['spread_ticks'],'0 ms']
            for k,v in zip(self.m.keys(),vals): self.m[k].setText(str(v))
            self.logger.log('MARKET',f"bid={s['bid']} ask={s['ask']} spread={s['spread']}")
        except Exception as e: self.logger.log('ERROR',f'market: {e}')

    def refresh_balances(self):
        try:
            b=self.account.balances();
            self.b['USDT Free'].setText(str(b['USDT_free'])); self.b['USDT Locked'].setText(str(b['USDT_locked']))
            self.b['EURI Free'].setText(str(b['EURI_free'])); self.b['EURI Locked'].setText(str(b['EURI_locked']))
            self.b['Estimated Total USDT'].setText(str(b['USDT_free']+b['USDT_locked']))
        except Exception as e: self.logger.log('ERROR',f'balances: {e}')

    def refresh_orders(self):
        try:
            data=self.orders.open_orders(); self.table.setRowCount(len(data))
            for r,o in enumerate(data):
                vals=[o.get('orderId'),o.get('side'),o.get('price'),o.get('origQty'),o.get('executedQty'),o.get('status'),str(o.get('time'))]
                for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))
        except Exception as e: self.logger.log('ERROR',f'orders: {e}')

    def place(self, side: str):
        if not self.trading_enabled.isChecked() or self.read_only.isChecked():
            self.logger.log('ERROR','Trading disabled/read-only mode'); return
        ok,msg = validate_order(self.price.text(), self.qty.text(), tick_size='0.0001', step_size='0.1', min_qty='0.1', min_notional='5')
        if not ok: self.logger.log('ERROR', msg); return
        if QMessageBox.question(self, 'Confirm', f'Place {side} LIMIT?') != QMessageBox.Yes: return
        resp=self.orders.place_limit(side, self.qty.text(), self.price.text()); self.logger.log('ORDER', f'{side} LIMIT sent {resp}')

    def cancel_selected(self):
        row=self.table.currentRow()
        if row < 0: return
        oid=int(self.table.item(row,0).text()); self.orders.cancel(oid); self.logger.log('ORDER',f'Cancelled {oid}')

    def cancel_all(self):
        self.orders.cancel_all(); self.logger.log('ORDER','Cancelled all EURIUSDT')

    def _update_total(self):
        try: self.total.setText(str(float(self.price.text() or 0) * float(self.qty.text() or 0)))
        except Exception: self.total.setText('0')

    def start_polling(self): self.timer.start(1000); self.logger.log('INFO','Polling started')
    def stop_polling(self): self.timer.stop(); self.logger.log('INFO','Polling stopped')


def run():
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec())
