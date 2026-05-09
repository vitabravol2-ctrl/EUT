from __future__ import annotations


def format_age_ms(age_ms: int) -> str:
    sec = int(age_ms / 1000)
    return f'{sec//60:02d}:{sec%60:02d}'
