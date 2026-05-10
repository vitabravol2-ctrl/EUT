from decimal import Decimal

import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow
from app.core.spread_stability_engine import ReadinessState


class _Orders:
    def __init__(self):
        self.placed = []
        self._status = {}

    def set_status(self, order_id, payload):
        self._status[int(order_id)] = payload

    def order_status(self, order_id):
        return self._status.get(int(order_id), {'status': 'NEW', 'executedQty': '0', 'cummulativeQuoteQty': '0', 'price': '1.1000'})

    def place_limit_maker(self, side, qty, price):
        oid = len(self.placed) + 1
        self.placed.append((side, Decimal(str(qty)), Decimal(str(price)), oid))
        return {'orderId': oid}

    def cancel(self, order_id):
        return {'status': 'CANCELED'}


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def _w():
    w = MainWindow()
    w._live_running = True
    w._private_ok = True
    w._balances = {'USDT_free': '1000', 'EURI_free': '0'}
    w._last_market_snapshot = {'bid': '1.1000', 'ask': '1.1002'}
    w._spread_metrics = type('M', (), {'state': type('S', (), {'readiness': ReadinessState.READY})()})()
    w._fill_observation = type('F', (), {'fill_possible': True})()
    w._exchange_filters = {'tickSize': '0.0001', 'stepSize': '0.01', 'minQty': '0.01', 'minNotional': '5'}
    w._require_exchange_filters = lambda: True
    w.refresh_orders = lambda force=False: None
    w.orders = _Orders()
    return w


def test_no_sell_after_closed_position(qapp):
    w = _w()
    w._cycle.open_position_qty = Decimal('0')
    w._trade_ledger.open_position_qty = Decimal('0')
    w._run_live_cycle()
    assert all(side != 'SELL' for side, *_ in w.orders.placed)


def test_sell_qty_only_from_ledger_open_position(qapp):
    w = _w()
    w._cycle.open_position_qty = Decimal('3.5')
    w._cycle.buy_filled_qty = Decimal('3.5')
    w._cycle.buy_avg_price = Decimal('1.1000')
    w._trade_ledger.open_position_qty = Decimal('1.234')
    w._trade_ledger.avg_open_buy = Decimal('1.1000')
    w._run_live_cycle()
    sell = next((o for o in w.orders.placed if o[0] == 'SELL'), None)
    assert sell is not None
    assert sell[1] == Decimal('1.23')


def test_old_inventory_ignored_when_cleanup_disabled(qapp):
    w = _w()
    w.cfg['enable_inventory_cleanup'] = False
    w._balances['BASE_free'] = '5'
    w._trade_ledger.open_position_qty = Decimal('0')
    w._run_live_cycle()
    assert all(side != 'SELL' for side, *_ in w.orders.placed)


def test_sell_filled_returns_immediately_no_second_sell(qapp):
    w = _w()
    w._cycle.open_position_qty = Decimal('1.00')
    w._cycle.buy_filled_qty = Decimal('1.00')
    w._cycle.buy_avg_price = Decimal('1.1000')
    w._trade_ledger.open_position_qty = Decimal('1.00')
    w._run_live_cycle()
    sell_id = w._cycle.sell_order_id
    assert sell_id is not None
    w.orders.set_status(sell_id, {'status': 'FILLED', 'executedQty': '1.00', 'cummulativeQuoteQty': '1.1002', 'price': '1.1002'})
    w._last_open_orders = []
    w._run_live_cycle()
    sell_count = len([o for o in w.orders.placed if o[0] == 'SELL'])
    assert sell_count == 1


def test_closed_then_next_action_is_buy(qapp):
    w = _w()
    w._finalize_closed_position('SELL_FILLED', sell_order_id=7)
    w._run_live_cycle()
    assert any(side == 'BUY' for side, *_ in w.orders.placed)
    assert all(side != 'SELL' for side, *_ in w.orders.placed)
