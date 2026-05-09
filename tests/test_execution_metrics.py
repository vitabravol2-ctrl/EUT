from app.core.execution_metrics import SpreadStabilityAnalyzer, QueueQualityEstimator, format_latency_ms, diff_order_transitions


def test_spread_lifetime_classification():
    a = SpreadStabilityAnalyzer()
    assert a.classify(2, 6000) == 'VERY_STABLE'
    assert a.classify(3, 3200) == 'STABLE'
    assert a.classify(2, 200) == 'UNSTABLE'


def test_queue_quality_classifier():
    q = QueueQualityEstimator()
    assert q.classify('STABLE', True, 100) == 'GOOD'
    assert q.classify('BAD', False, 900) == 'POOR'
    assert q.classify('UNSTABLE', True, 200) == 'MEDIUM'


def test_latency_formatting():
    assert format_latency_ms(142.9) == '142 ms'


def test_order_watcher_transitions():
    events = diff_order_transitions({1, 2}, {2, 3})
    labels = [(e.order_id, e.transition) for e in events]
    assert (3, 'NEW') in labels
    assert (1, 'DISAPPEARED') in labels
