from __future__ import annotations


class AccountService:
    def __init__(self, client) -> None:
        self.client = client

    def balances(self) -> dict:
        data = self.client.get_account()
        balances = {x['asset']: x for x in data.get('balances', []) if isinstance(x, dict)}
        euri = balances.get('EURI', {'free': '0', 'locked': '0'})
        usdt = balances.get('USDT', {'free': '0', 'locked': '0'})
        return {
            'EURI_free': float(euri.get('free', 0) or 0),
            'EURI_locked': float(euri.get('locked', 0) or 0),
            'USDT_free': float(usdt.get('free', 0) or 0),
            'USDT_locked': float(usdt.get('locked', 0) or 0),
        }
