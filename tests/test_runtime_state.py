import time
from app.core.runtime_state import RuntimeState


def test_runtime_state_stale_detection():
    r = RuntimeState()
    r.mark_rest_update()
    r.update_stale(1000)
    assert r.rest_status == 'OK'
    r.last_rest_update_ts = time.time() - 2
    r.update_stale(500)
    assert r.rest_status == 'STALE'


def test_runtime_cycles_per_sec_positive():
    r = RuntimeState()
    r._cycle_stamps = [time.time() - 1, time.time()]
    assert r.rest_cycles_per_sec() > 0
