import pytest
from decimal import Decimal

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow
from app.core.spread_stability_engine import ReadinessState


class DummyOrders:
    def __init__(self):
        self.placed = []
        self.status = {}
    def place_limit_maker(self, side, qty, price):
        oid = len(self.placed) + 1
        self.placed.append((oid, side, qty, price))
        self.status[oid] = {'status': 'NEW', 'executedQty': '0', 'price': price}
        return {'orderId': oid}
    def cancel(self, _order_id):
        return {'status': 'CANCELED'}
    def order_status(self, order_id):
        return self.status.get(order_id, {'status': 'CANCELED', 'executedQty': '0', 'price': '0'})


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def make_window():
    w = MainWindow()
    w._live_running = True
    w._private_ok = True
    w._balances = {'QUOTE_free': '1000', 'BASE_free': '0', 'BASE_locked': '0', 'QUOTE_locked': '0'}
    w._last_market_snapshot = {'bid': '1.1000', 'ask': '1.1400'}
    w._spread_metrics = type('M', (), {'state': type('S', (), {'readiness': ReadinessState.READY})()})()
    w._fill_observation = type('F', (), {'fill_possible': True})()
    w._exchange_filters = {'tickSize': '0.0001', 'stepSize': '0.01', 'minQty': '0.01', 'minNotional': '5'}
    w.orders = DummyOrders()
    w.refresh_orders = lambda force=False: None
    return w


def test_no_duplicate_buy_orders(qapp):
    w = make_window()
    w._run_live_cycle()
    w._run_live_cycle()
    buy_orders = [x for x in w.orders.placed if x[1] == 'BUY']
    assert len(buy_orders) == 1


def test_no_duplicate_sell_orders(qapp):
    w = make_window()
    w._cycle.open_position_qty = Decimal('2')
    w._cycle.buy_avg_price = Decimal('1.0')
    w._balances['BASE_free'] = '2'
    w._run_live_cycle()
    w._run_live_cycle()
    sell_orders = [x for x in w.orders.placed if x[1] == 'SELL']
    assert len(sell_orders) == 1


def test_sl_requires_confirmation(qapp):
    w = make_window()
    w.cfg['sl_confirm_ms'] = 3000
    w.cfg['stop_loss_ticks'] = 10
    w._cycle.open_position_qty = Decimal('1')
    w._cycle.buy_avg_price = Decimal('1.2000')
    w._balances['BASE_free'] = '1'
    w._last_market_snapshot = {'bid': '1.1000', 'ask': '1.1005'}
    w._run_live_cycle()
    assert w._exit_reason != 'SL_EXIT'
