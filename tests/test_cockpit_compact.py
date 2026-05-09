import pytest

QtWidgets = pytest.importorskip('PySide6.QtWidgets', reason='PySide6 GUI deps are unavailable in this environment')
QApplication = QtWidgets.QApplication

from app.gui.main_window import MainWindow, ManualOrderDialog, AllDataDialog, TradeSettingsDialog


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def test_status_strip_only_critical_pills(qapp):
    w = MainWindow()
    assert set(w._status_badges.keys()) == {'SYSTEM', 'TRADING', 'SPREAD', 'HARVEST', 'ORDERS', 'RISK'}


def test_main_screen_hides_market_and_balance_details(qapp):
    w = MainWindow()
    text = '\n'.join(lbl.text() for lbl in w.findChildren(QtWidgets.QLabel))
    assert 'LAST' not in text and 'BID' not in text and 'ASK' not in text
    assert 'free /' not in text and 'locked' not in text


def test_dialogs_exist(qapp):
    w = MainWindow()
    w.open_manual_order(); w.open_all_data(); w.open_trade_settings()
    assert isinstance(w.manual_order_dialog, ManualOrderDialog)
    assert isinstance(w.all_data_dialog, AllDataDialog)
    assert isinstance(w.trade_settings_dialog, TradeSettingsDialog)


def test_open_orders_toolbar_removed_and_dark_table(qapp):
    w = MainWindow()
    buttons = [b.text() for b in w.findChildren(QtWidgets.QPushButton)]
    assert 'Refresh' not in buttons
    assert '#141b24' in w.styleSheet()


def test_manual_order_actions_still_callable(qapp):
    w = MainWindow()
    d = ManualOrderDialog(w)
    d.main.place('BUY')
    d.main.place('SELL')
    d.main.cancel_selected()
    d.main.cancel_all()


def test_all_data_groups_exist(qapp):
    w = MainWindow()
    d = AllDataDialog(w)
    groups = [g.title() for g in d.findChildren(QtWidgets.QGroupBox)]
    assert groups == ['Account', 'Market', 'Harvest', 'Execution', 'Runtime', 'Filters']
