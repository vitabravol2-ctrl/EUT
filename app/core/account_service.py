from __future__ import annotations

from decimal import Decimal


class AccountService:
    def __init__(self, client) -> None:
        self.client = client

    def balances(self, last_price: Decimal = Decimal('0')) -> dict:
        data = self.client.get_account()
        balances = {x['asset']: x for x in data.get('balances', []) if isinstance(x, dict)}
        euri = balances.get('EURI', {'free': '0', 'locked': '0'})
        usdt = balances.get('USDT', {'free': '0', 'locked': '0'})
        euri_free = Decimal(str(euri.get('free', 0) or 0))
        euri_locked = Decimal(str(euri.get('locked', 0) or 0))
        usdt_free = Decimal(str(usdt.get('free', 0) or 0))
        usdt_locked = Decimal(str(usdt.get('locked', 0) or 0))
        euri_total = euri_free + euri_locked
        usdt_total = usdt_free + usdt_locked
        equity_usdt = usdt_total + (euri_total * Decimal(str(last_price or 0)))
        return {
            'EURI_free': euri_free,
            'EURI_locked': euri_locked,
            'USDT_free': usdt_free,
            'USDT_locked': usdt_locked,
            'equity_usdt': equity_usdt,
        }
