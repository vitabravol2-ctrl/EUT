from app.core.harvest_readiness import HarvestReadinessEngine, HarvestReadinessState


def _ctx():
    return {
        'market_snapshot': {'spread_ticks': 2, 'spread_lifetime_ms': 3500, 'best_unchanged': True},
        'execution_metrics': {'latency_ms': 320, 'queue_quality': 'GOOD', 'spread_stability': 'STABLE'},
        'filters': {'PRICE_FILTER': {'tickSize': '0.01'}, 'LOT_SIZE': {'stepSize': '0.1'}},
        'balances': {'account_connected': True, 'trading_enabled': True, 'read_only': False, 'risk_blocked': False},
        'open_orders': [],
    }


def test_ready_when_all_good():
    e = HarvestReadinessEngine()
    c = _ctx()
    r = e.analyze(**c)
    assert r.state == HarvestReadinessState.READY


def test_watch_when_lifetime_short():
    e = HarvestReadinessEngine()
    c = _ctx(); c['market_snapshot']['spread_lifetime_ms'] = 1200
    r = e.analyze(**c)
    assert r.state == HarvestReadinessState.WATCH


def test_not_ready_when_spread_missing():
    e = HarvestReadinessEngine()
    c = _ctx(); c['market_snapshot']['spread_ticks'] = 0
    r = e.analyze(**c)
    assert r.state == HarvestReadinessState.NOT_READY


def test_not_ready_when_latency_too_high():
    e = HarvestReadinessEngine()
    c = _ctx(); c['execution_metrics']['latency_ms'] = 2500
    r = e.analyze(**c)
    assert r.state == HarvestReadinessState.NOT_READY


def test_blocked_states():
    e = HarvestReadinessEngine()
    c = _ctx(); c['balances']['trading_enabled'] = False
    assert e.analyze(**c).state == HarvestReadinessState.BLOCKED
    c = _ctx(); c['balances']['read_only'] = True
    assert e.analyze(**c).state == HarvestReadinessState.BLOCKED
    c = _ctx(); c['balances']['risk_blocked'] = True
    assert e.analyze(**c).state == HarvestReadinessState.BLOCKED


def test_score_increases_with_spread_and_lifetime():
    e = HarvestReadinessEngine()
    c1 = _ctx(); c1['market_snapshot']['spread_ticks'] = 1; c1['market_snapshot']['spread_lifetime_ms'] = 3000
    c2 = _ctx(); c2['market_snapshot']['spread_ticks'] = 3; c2['market_snapshot']['spread_lifetime_ms'] = 6000
    assert e.analyze(**c2).score > e.analyze(**c1).score
