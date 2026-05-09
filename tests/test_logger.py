import time

from app.core.logger import AppLogger


def test_logger_dedupe_window():
    logger = AppLogger(dedupe_seconds=10)
    seen = []
    logger.subscribe(lambda rec: seen.append(rec.message))
    logger.log('MARKET', 'same')
    logger.log('MARKET', 'same')
    assert seen == ['same']


def test_logger_after_window_logs_again():
    logger = AppLogger(dedupe_seconds=0.01)
    seen = []
    logger.subscribe(lambda rec: seen.append(rec.message))
    logger.log('ERROR', 'boom')
    time.sleep(0.02)
    logger.log('ERROR', 'boom')
    assert len(seen) == 2
