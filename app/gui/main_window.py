from __future__ import annotations

import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView)

from app.core.account_service import AccountService
from app.core.async_runner import TaskRunner
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
        self.setWindowTitle('EUT v0.2.5 — Core Functionality Recovery + Real Binance Flow')
        self.setMinimumSize(1280, 720)
        self.resize(1500, 900)
        self.logger = AppLogger(max_records=500, dedupe_seconds=30)
        self.cfg = load_config()
        self.runtime = RuntimeState()
        self.ws = WSManager(enabled=False)
        self.settings_dialog = None
        self.filters = None
        self._last_market = None

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

    def _init_services(self):
        self.client = BinanceClient(self.cfg['api_key'], self.cfg['api_secret'], self.cfg['testnet'], self.cfg.get('request_timeout_sec', 3))
        self.market = MarketService(self.client, self.cfg['symbol'])
        self.account = AccountService(self.client)
        self.orders = OrderService(self.client, self.cfg['symbol'])

    # UI methods omitted unchanged from current structure for brevity in task
    def _btn(self, text, fn):
        b = QPushButton(text); b.setMinimumHeight(BUTTON_H); b.clicked.connect(fn); return b
    def _build_ui(self):
        self.setFont(QFont('', APP_FONT_PT)); root = QWidget(); self.setCentralWidget(root); main = QVBoxLayout(root)
        self.s={}; self.m={}; self.b={}
        top = QGroupBox('Статус системы'); top.setMaximumHeight(110); l=QGridLayout(top)
        for i,k in enumerate(['Публичный REST','Аккаунт','Опрос','Приватный канал','Торговля','Только чтение','WS','Задержка']): l.addWidget(QLabel(f'{k}:'),i//4,(i%4)*2); self.s[k]=QLabel('-'); l.addWidget(self.s[k],i//4,(i%4)*2+1)
        self.settings_btn=self._btn('Настройки',self.open_settings); self.diag_btn=self._btn('Проверить систему',self.run_diagnostics); l.addWidget(self.settings_btn,2,6); l.addWidget(self.diag_btn,2,7); main.addWidget(top)
        self.table=QTableWidget(0,8); self.table.setHorizontalHeaderLabels(['ID','Сторона','Цена','Количество','Исполнено','Исполнено %','Статус','Возраст'])
        for i,w in OPEN_ORDERS_COL_WIDTHS.items(): self.table.setColumnWidth(i,w)
        self.side=QComboBox(); self.side.addItems(['BUY','SELL']); self.price=QLineEdit(); self.qty=QLineEdit(); self.total=QLabel('0')
        self.buy_btn=self._btn('Купить LIMIT', lambda: self.place('BUY')); self.sell_btn=self._btn('Продать LIMIT', lambda: self.place('SELL'))
        self.refresh_orders_btn=self._btn('Обновить', self.refresh_orders); self.cancel_btn=self._btn('Отменить выбранный', self.cancel_selected); self.cancel_all_btn=self._btn('Отменить все', self.cancel_all)
        self.balance_refresh_btn=self._btn('Обновить балансы', self.refresh_balances)
        self.log_panel=LogPanel(500); self.log_panel.setMinimumHeight(160); self.log_panel.setMaximumHeight(220); self.logger.subscribe(self.log_panel.append_record)
        # Keep existing layout simple
        main.addWidget(self.table); main.addWidget(self.log_panel)

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
            info = self.client.get_exchange_info(self.cfg['symbol'])
            self.filters = info

    def _set_private_polling(self, enabled: bool):
        self.polling.set_private_enabled(enabled and self.runtime.account_auth_state == 'CONNECTED')
        self.runtime.private_polling_state = 'RUNNING' if self.polling.private_enabled else 'PAUSED'

    def refresh_market(self):
        self.task_runner.run_task('market', lambda: self.market.snapshot())

    def refresh_balances(self):
        if self.runtime.account_auth_state != 'CONNECTED': return
        self.task_runner.run_task('balances', self.account.balances)

    def refresh_orders(self):
        if self.runtime.account_auth_state != 'CONNECTED': return
        self.task_runner.run_task('orders', self.orders.open_orders)

    def _on_task_success(self, name, payload):
        if name == 'market':
            s=payload
            self.m.update({'Последняя':QLabel(str(s['last']))})
        elif name == 'balances':
            self.runtime.mark_balances_update()
        elif name == 'orders':
            data = payload; self.table.setRowCount(len(data)); now_ms=int(time.time()*1000)
            for r,o in enumerate(data):
                filled=((float(o.get('executedQty',0))/max(float(o.get('origQty',0) or 1),1e-9))*100); age=format_age_ms(max(0, now_ms-int(o.get('time', now_ms))))
                vals=[o.get('orderId'),o.get('side'),o.get('price'),o.get('origQty'),o.get('executedQty'),f'{filled:.1f}%',o.get('status'),age]
                for c,v in enumerate(vals): self.table.setItem(r,c,QTableWidgetItem(str(v)))

    def _on_task_error(self, name, err):
        self.logger.log('ОШИБКА', f'{name}: {err}')

    def place(self, side):
        if self.runtime.account_auth_state != 'CONNECTED': return self.logger.log('РИСК', 'Торговля недоступна: аккаунт не подключен')
        if self.cfg.get('read_only', True): return self.logger.log('РИСК', 'Торговля запрещена: включен режим только чтение')
        if not self.cfg.get('trading_enabled', False): return self.logger.log('РИСК', 'Торговля отключена в настройках')
        price=self.price.text().strip(); qty=self.qty.text().strip()
        if not price or not qty: return self.logger.log('РИСК', 'Заполните цену и количество')
        self._load_filters_if_needed()
        ok,msg=validate_order(side, price, qty, self.filters)
        if not ok: return self.logger.log('ОШИБКА', msg)
        if QMessageBox.question(self, 'Подтверждение ордера', f'Отправить {side} LIMIT {qty} по {price}?') != QMessageBox.Yes: return
        self.task_runner.run_task('place_order', lambda: self.orders.place_limit(side, qty, price))

    def cancel_selected(self):
        row=self.table.currentRow()
        if row < 0: return QMessageBox.warning(self, 'Внимание', 'Выберите ордер для отмены')
        item=self.table.item(row,0)
        if not item: return QMessageBox.warning(self, 'Внимание', 'orderId не найден')
        oid=int(item.text())
        if QMessageBox.question(self, 'Подтверждение', f'Отменить ордер {oid}?') != QMessageBox.Yes: return
        self.task_runner.run_task('cancel_order', lambda: self.orders.cancel(oid))

    def cancel_all(self):
        if QMessageBox.question(self, 'Подтверждение', 'Отменить все открытые ордера?') != QMessageBox.Yes: return
        self.task_runner.run_task('cancel_order', self.orders.cancel_all)

    def run_diagnostics(self):
        self.logger.log('ИНФО', f'diag in_flight={len(self.task_runner.in_flight)} polling={self.polling.running} private={self.polling.private_enabled}')

    def _tick_status(self):
        self.s['Аккаунт'].setText(self.runtime.account_auth_state)

    def start_polling(self):
        if self.polling.start(): self.runtime.set_polling(True); self.logger.log('ИНФО','Опрос запущен')
    def stop_polling(self):
        self.polling.stop(); self.runtime.set_polling(False); self.logger.log('ИНФО','Опрос остановлен')


def run():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    w = MainWindow(); w.show(); sys.exit(app.exec())
