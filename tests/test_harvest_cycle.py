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
