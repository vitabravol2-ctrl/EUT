from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests


class BinanceClient:
    def __init__(self, api_key: str = '', api_secret: str = '', testnet: bool = False) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = 'https://testnet.binance.vision' if testnet else 'https://api.binance.com'

    def _headers(self) -> dict:
        return {'X-MBX-APIKEY': self.api_key}

    def _sign(self, params: dict) -> dict:
        params = dict(params)
        params['timestamp'] = int(time.time() * 1000)
        query = urlencode(params)
        params['signature'] = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return params

    def get_exchange_info(self, symbol: str) -> dict:
        return requests.get(f'{self.base_url}/api/v3/exchangeInfo', params={'symbol': symbol}, timeout=10).json()

    def get_book_ticker(self, symbol: str) -> dict:
        return requests.get(f'{self.base_url}/api/v3/ticker/bookTicker', params={'symbol': symbol}, timeout=10).json()

    def get_ticker(self, symbol: str) -> dict:
        return requests.get(f'{self.base_url}/api/v3/ticker/price', params={'symbol': symbol}, timeout=10).json()

    def get_account(self) -> dict:
        params = self._sign({})
        return requests.get(f'{self.base_url}/api/v3/account', params=params, headers=self._headers(), timeout=10).json()

    def get_open_orders(self, symbol: str) -> list:
        params = self._sign({'symbol': symbol})
        return requests.get(f'{self.base_url}/api/v3/openOrders', params=params, headers=self._headers(), timeout=10).json()

    def create_limit_order(self, symbol: str, side: str, quantity: str, price: str) -> dict:
        params = self._sign({'symbol': symbol, 'side': side, 'type': 'LIMIT', 'timeInForce': 'GTC', 'quantity': quantity, 'price': price})
        return requests.post(f'{self.base_url}/api/v3/order', params=params, headers=self._headers(), timeout=10).json()

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        params = self._sign({'symbol': symbol, 'orderId': order_id})
        return requests.delete(f'{self.base_url}/api/v3/order', params=params, headers=self._headers(), timeout=10).json()

    def cancel_all_orders(self, symbol: str) -> list:
        params = self._sign({'symbol': symbol})
        return requests.delete(f'{self.base_url}/api/v3/openOrders', params=params, headers=self._headers(), timeout=10).json()
