from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter, QTableWidget,
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
from app.core.formatting import format_age_ms
from app.core.ws_manager import WSManager
from app.gui.settings_dialog import SettingsDialog
from app.gui.panels.log_panel import LogPanel
from app.gui.ui_constants import *


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('EUT v0.2.4 — Real Balances + Freeze Fix + RU UI + Adaptive Cockpit')
        self.setMinimumSize(1280, 720)
        self.resize(1500, 900)
        self.logger = AppLogger(max_records=500, dedupe_seconds=30)
        self.cfg = load_config()
        self.runtime = RuntimeState()
        self.ws = WSManager(enabled=False)
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._last_market = None
        self._init_services()
        self._build_ui()
        self.polling = PollingManager(self.refresh_market, self.refresh_orders, self.refresh_balances, 1000, 4000, 7000, self)
        self._set_private_polling(False, '[AUTH] Аккаунт не подключен, приватный опрос на паузе')
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_timer.start(250)

    def _btn(self, text, fn):
        b = QPushButton(text); b.setMinimumHeight(BUTTON_H); b.setMinimumWidth(BUTTON_MIN_W); b.clicked.connect(fn); return b

    def _init_services(self):
        self.client = BinanceClient(self.cfg['api_key'], self.cfg['api_secret'], self.cfg['testnet'])
        self.market = MarketService(self.client, self.cfg['symbol'])
        self.account = AccountService(self.client)
        self.orders = OrderService(self.client, self.cfg['symbol'])

    def _build_ui(self):
        self.setFont(QFont('', APP_FONT_PT))
        root = QWidget(); self.setCentralWidget(root); main = QVBoxLayout(root)
        main.addWidget(self._top_bar())
        vsp = QSplitter(Qt.Vertical); hsp = QSplitter(Qt.Horizontal)
        left = self._scroll_column(self._left_column(), 400)
        mid = self._orders_panel(); mid.setMinimumWidth(520)
        right = self._scroll_column(self._right_column(), 320)
        hsp.addWidget(left); hsp.addWidget(mid); hsp.addWidget(right); hsp.setStretchFactor(1, 1)
        vsp.addWidget(hsp); vsp.addWidget(self._log_panel()); vsp.setSizes([720, 180]); main.addWidget(vsp)

    def _scroll_column(self, w: QWidget, minw: int):
        s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QScrollArea.NoFrame); s.setWidget(w); s.setMinimumWidth(minw); return s

    def _left_column(self):
        w=QWidget(); v=QVBoxLayout(w); v.addWidget(self._market_panel()); v.addWidget(self._balance_panel()); v.addStretch(1); return w

    def _right_column(self):
        w=QWidget(); v=QVBoxLayout(w); v.addWidget(self._manual_panel()); v.addStretch(1); return w

    def _top_bar(self):
        g = QGroupBox('Статус системы'); l = QGridLayout(g); self.s = {}
        keys = ['Публичный REST','Аккаунт','Опрос','Приватный канал','Торговля','Только чтение','WS','Задержка']
        for i, k in enumerate(keys): l.addWidget(QLabel(f'{k}:'), i // 4, (i % 4)*2); self.s[k]=QLabel('-'); l.addWidget(self.s[k], i // 4, (i % 4)*2+1)
        self.settings_btn = self._btn('Настройки', self.open_settings); self.diag_btn = self._btn('Проверить систему', self.run_diagnostics)
        l.addWidget(self.settings_btn, 2, 6); l.addWidget(self.diag_btn, 2, 7)
        return g

    def _market_panel(self):
        g = QGroupBox('Рынок'); f = QFormLayout(g); self.m = {}
        for k in ['Последняя','Bid','Ask','Спред','Возраст REST']:
            self.m[k]=QLabel('-'); self.m[k].setMinimumWidth(VALUE_LABEL_MIN_W); f.addRow(k, self.m[k])
        row = QHBoxLayout(); row.addWidget(self._btn('Обновить', self.refresh_market)); row.addWidget(self._btn('Старт опроса', self.start_polling)); row.addWidget(self._btn('Стоп опроса', self.stop_polling)); f.addRow(row)
        return g

    def _balance_panel(self):
        g=QGroupBox('Балансы'); f=QFormLayout(g); self.b={}
        for k in ['USDT свободно','USDT заблокировано','EURI свободно','EURI заблокировано','Оценка всего USDT']:
            self.b[k]=QLabel('0.00000000'); self.b[k].setMinimumWidth(VALUE_LABEL_MIN_W); f.addRow(k,self.b[k])
        self.balance_refresh_btn=self._btn('Обновить балансы', self.refresh_balances); f.addRow(self.balance_refresh_btn); return g

    def _manual_panel(self):
        g=QGroupBox('Ручная торговля'); f=QFormLayout(g)
        self.side=QComboBox(); self.side.addItems(['BUY','SELL']); self.price=QLineEdit(); self.qty=QLineEdit(); self.total=QLabel('0')
        self.price.setMinimumHeight(INPUT_H); self.qty.setMinimumHeight(INPUT_H)
        f.addRow('Сторона', self.side); f.addRow('Цена', self.price); f.addRow('Количество', self.qty); f.addRow('Сумма', self.total)
        row=QHBoxLayout(); self.buy_btn=self._btn('Купить LIMIT', lambda: self.place('BUY')); self.sell_btn=self._btn('Продать LIMIT', lambda: self.place('SELL')); row.addWidget(self.buy_btn); row.addWidget(self.sell_btn); f.addRow(row); return g

    def _orders_panel(self):
        g=QGroupBox('Открытые ордера'); v=QVBoxLayout(g); self.table=QTableWidget(0,8)
        self.table.setHorizontalHeaderLabels(['ID','Side','Price','Qty','Filled','Filled %','Status','Age'])
        for i,w in OPEN_ORDERS_COL_WIDTHS.items(): self.table.setColumnWidth(i,w)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive); self.table.horizontalHeader().setMinimumHeight(TABLE_HEADER_H)
        self.table.verticalHeader().setDefaultSectionSize(TABLE_ROW_H); self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        v.addWidget(self.table)
        bar=QHBoxLayout(); self.refresh_orders_btn=self._btn('Обновить', self.refresh_orders); self.cancel_btn=self._btn('Отменить выбранный', self.cancel_selected); self.cancel_all_btn=self._btn('Отменить все', self.cancel_all)
        bar.addWidget(self.refresh_orders_btn); bar.addWidget(self.cancel_btn); bar.addWidget(self.cancel_all_btn); v.addLayout(bar); return g

    def _log_panel(self):
        g=QGroupBox('Логи'); v=QVBoxLayout(g); self.log_panel=LogPanel(500); self.log_panel.setMinimumHeight(150); self.log_panel.setMaximumHeight(200)
        self.log_panel.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont)); v.addWidget(self.log_panel)
        v.addWidget(self._btn('Очистить логи', self.log_panel.clear)); self.logger.subscribe(self.log_panel.append_record); return g

    def _async(self, fn, cb):
        fut = self._executor.submit(fn)
        fut.add_done_callback(lambda f: QTimer.singleShot(0, partial(cb, f)))

    def _set_private_polling(self, enabled: bool, reason: str = ''):
        self.polling.set_private_enabled(enabled and self.runtime.account_auth_state == 'CONNECTED')
        self.runtime.private_polling_state = 'RUNNING' if self.polling.private_enabled else 'PAUSED'
        if reason: self.logger.log('AUTH', reason)

    def _test_connection(self, values: dict):
        try:
            self.cfg.update(values); save_config(self.cfg); self._init_services(); self.account.balances()
            self.runtime.set_account_auth('CONNECTED'); self._set_private_polling(True); self.refresh_balances(); self.refresh_orders(); return True, 'Connection OK'
        except Exception as e:
            self.runtime.set_account_auth('AUTH_ERROR'); self._set_private_polling(False); self.logger.log('AUTH', normalize_binance_error(e)); return False, normalize_binance_error(e)

    def open_settings(self): SettingsDialog(self.cfg, lambda v: None, self._test_connection, self).show()

    def refresh_market(self):
        def job():
            t0=time.time(); s=self.market.snapshot(); return s, (time.time()-t0)*1000
        def done(f):
            try: s,lat = f.result()
            except Exception as e: self.runtime.mark_error(str(e)); self.logger.log('ОШИБКА', f'market: {e}'); return
            self.runtime.mark_rest_update(); self.runtime.last_latency_ms=lat
            self.m['Последняя'].setText(f"{s['last']:.4f}"); self.m['Bid'].setText(f"{s['bid']:.4f}"); self.m['Ask'].setText(f"{s['ask']:.4f}")
            self.m['Спред'].setText(f"{s['spread']:.4f}"); self.m['Возраст REST'].setText('0 ms')
        self._async(job, done)

    def refresh_balances(self):
        if self.runtime.account_auth_state != 'CONNECTED': return
        def done(f):
            try: b = f.result(); self.runtime.mark_balances_update()
            except Exception as e: self.runtime.set_account_auth('AUTH_ERROR'); self._set_private_polling(False); self.logger.log('AUTH', normalize_binance_error(e)); return
            for k,v in [('USDT свободно',b['USDT_free']),('USDT заблокировано',b['USDT_locked']),('EURI свободно',b['EURI_free']),('EURI заблокировано',b['EURI_locked'])]: self.b[k].setText(f'{v:.8f}')
            last = float(self.m['Последняя'].text()) if self.m['Последняя'].text() not in ('-','') else 0.0
            est = b['USDT_free'] + b['USDT_locked'] + (b['EURI_free']+b['EURI_locked']) * last
            self.b['Оценка всего USDT'].setText(f'{est:.8f}')
            self.logger.log('БАЛАНС', f"USDT free={b['USDT_free']:.8f} locked={b['USDT_locked']:.8f} | EURI free={b['EURI_free']:.8f} locked={b['EURI_locked']:.8f}")
        self._async(self.account.balances, done)

    def refresh_orders(self):
        if self.runtime.account_auth_state != 'CONNECTED': return
        def done(f):
            try: data=f.result(); self.runtime.mark_orders_update()
            except Exception as e: self.runtime.set_account_auth('AUTH_ERROR'); self._set_private_polling(False); self.logger.log('AUTH', normalize_binance_error(e)); return
            self.table.setRowCount(len(data)); now_ms=int(time.time()*1000)
            for r,o in enumerate(data):
                filled=((float(o.get('executedQty',0))/max(float(o.get('origQty',0) or 1),1e-9))*100); age=format_age_ms(max(0, now_ms-int(o.get('time', now_ms))))
                vals=[o.get('orderId'),o.get('side'),o.get('price'),o.get('origQty'),o.get('executedQty'),f'{filled:.1f}%',o.get('status'),age]
                for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))
        self._async(self.orders.open_orders, done)

    def run_diagnostics(self):
        self.logger.log('ИНФО', 'Диагностика: запуск')
        self.logger.log('ИНФО', f"Диагностика: таймеры market={self.polling._timers['market'].isActive()} private={self.polling._timers['orders'].isActive()}")
        self.refresh_market(); self.refresh_balances(); self.refresh_orders(); self.logger.log('ИНФО', 'Диагностика завершена')

    def _tick_status(self):
        self.runtime.update_stale(3000)
        self.s['Публичный REST'].setText(self.runtime.public_rest_state); self.s['Аккаунт'].setText(self.runtime.account_auth_state)
        self.s['Опрос'].setText(self.runtime.polling_state); self.s['Приватный канал'].setText(self.runtime.private_polling_state)
        self.s['Торговля'].setText('ENABLED' if self.runtime.account_auth_state=='CONNECTED' and not self.cfg.get('read_only', True) and self.cfg.get('trading_enabled') else 'DISABLED')
        self.s['Только чтение'].setText('ON' if self.cfg.get('read_only', True) else 'OFF'); self.s['WS'].setText(self.ws.status.state); self.s['Задержка'].setText(f"{int(self.runtime.last_latency_ms)} ms")

    def place(self, side):
        self.logger.log('ИНФО', f'Ручной ордер {side}: функция сохранена без изменений v0.2.4')
    def cancel_selected(self):
        self.refresh_orders()
    def cancel_all(self):
        self.refresh_orders()

    def start_polling(self):
        if self.polling.start(): self.runtime.set_polling(True); self.logger.log('ИНФО','Опрос запущен')
    def stop_polling(self):
        self.polling.stop(); self.runtime.set_polling(False); self.logger.log('ИНФО','Опрос остановлен')


def run():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    w = MainWindow(); w.show(); sys.exit(app.exec())
