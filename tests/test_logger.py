from app.core.logger import AppLogger


def test_logger_antispam_duplicate_suppression():
    logger = AppLogger()
    seen = []
    logger.subscribe(lambda rec: seen.append(rec.message))
    for _ in range(9):
        logger.log('MARKET', 'same')
    assert len(seen) == 1
    logger.log('MARKET', 'same')
    assert len(seen) == 2
    assert '(x10)' in seen[-1]
