from __future__ import annotations

from decimal import Decimal


class AccountService:
    def __init__(self, client, base_asset: str = 'EURI', quote_asset: str = 'USDT') -> None:
        self.client = client
        self.base_asset = base_asset
        self.quote_asset = quote_asset

    def set_assets(self, base_asset: str, quote_asset: str) -> None:
        self.base_asset = base_asset
        self.quote_asset = quote_asset

    def balances(self, last_price: Decimal = Decimal('0')) -> dict:
        data = self.client.get_account()
        balances = {x['asset']: x for x in data.get('balances', []) if isinstance(x, dict)}
        base = balances.get(self.base_asset, {'free': '0', 'locked': '0'})
        quote = balances.get(self.quote_asset, {'free': '0', 'locked': '0'})
        base_free = Decimal(str(base.get('free', 0) or 0))
        base_locked = Decimal(str(base.get('locked', 0) or 0))
        quote_free = Decimal(str(quote.get('free', 0) or 0))
        quote_locked = Decimal(str(quote.get('locked', 0) or 0))
        base_total = base_free + base_locked
        quote_total = quote_free + quote_locked
        equity_quote = quote_total + (base_total * Decimal(str(last_price or 0)))
        return {
            'base_asset': self.base_asset,
            'quote_asset': self.quote_asset,
            'BASE_free': base_free,
            'BASE_locked': base_locked,
            'QUOTE_free': quote_free,
            'QUOTE_locked': quote_locked,
            'equity_quote': equity_quote,
        }
