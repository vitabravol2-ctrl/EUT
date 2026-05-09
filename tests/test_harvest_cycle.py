from decimal import Decimal

from app.core.harvest_cycle import CycleState, HarvestCycle


def test_buy_partial_and_sell_partial_accounting():
    c = HarvestCycle(target_qty=Decimal('10'))
    c.apply_buy_fill(Decimal('4'), Decimal('1.10'))

    assert c.buy_filled_qty == Decimal('4')
    assert c.open_position_qty == Decimal('4')
    assert c.buy_avg_price == Decimal('1.10')

    c.apply_sell_fill(Decimal('1.5'), Decimal('1.12'))
    assert c.closed_qty == Decimal('1.5')
    assert c.open_position_qty == Decimal('2.5')
    assert c.realized_pnl == Decimal('0.03')


def test_cycle_transition_updates_reason():
    c = HarvestCycle()
    old, new = c.transition(CycleState.WAIT_READY, 'boot')
    assert old == CycleState.IDLE
    assert new == CycleState.WAIT_READY
    assert c.reason == 'boot'


def test_cancel_buy_with_zero_fill_goes_wait_ready():
    c = HarvestCycle()
    c.buy_filled_qty = Decimal('0')
    assert c.next_state_after_buy_cancel() == CycleState.WAIT_READY


def test_cancel_buy_with_partial_fill_goes_place_sell():
    c = HarvestCycle()
    c.buy_filled_qty = Decimal('0.7')
    assert c.next_state_after_buy_cancel() == CycleState.PLACE_SELL


def test_place_sell_blocked_without_open_position():
    c = HarvestCycle()
    c.open_position_qty = Decimal('0')
    assert c.can_place_sell() is False


def test_profit_locked_reset_clears_cycle_accounting():
    c = HarvestCycle()
    c.buy_order_id = 101
    c.sell_order_id = 202
    c.target_qty = Decimal('9')
    c.buy_requested_qty = Decimal('9')
    c.buy_filled_qty = Decimal('4.2')
    c.sell_filled_qty = Decimal('4.2')
    c.open_position_qty = Decimal('0.4')
    c.closed_qty = Decimal('3.8')

    c.reset_cycle_accounting()

    assert c.buy_order_id is None
    assert c.sell_order_id is None
    assert c.target_qty == Decimal('0')
    assert c.buy_requested_qty == Decimal('0')
    assert c.open_position_qty == Decimal('0')
    assert c.closed_qty == Decimal('4.2')
    assert c.sell_filled_qty == Decimal('4.2')
