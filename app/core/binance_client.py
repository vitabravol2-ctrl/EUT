from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests


class BinanceAPIError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def normalize_binance_error(exc: Exception) -> str:
    if isinstance(exc, requests.Timeout):
        return 'Binance network timeout: check Internet connection.'
    if isinstance(exc, requests.ConnectionError):
        return 'Binance network error: check Internet connection.'
    if isinstance(exc, BinanceAPIError):
        if exc.code == -1021:
            return 'Binance timestamp out of sync (-1021): sync system clock and retry.'
        if exc.code == -2015 or exc.status_code == 401:
            return 'Binance auth failed: check API key, IP whitelist, spot permissions, testnet/mainnet mode.'
        return str(exc)
    return f'Unexpected Binance error: {exc}'


class BinanceClient:
    def __init__(self, api_key: str = '', api_secret: str = '', testnet: bool = False, request_timeout_sec: float = 3.0) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = 'https://testnet.binance.vision' if testnet else 'https://api.binance.com'
        self.recv_window = 5000
        self.request_timeout_sec = request_timeout_sec
        self.private_timeout_sec = min(5.0, max(3.0, request_timeout_sec + 2.0))

    def _headers(self) -> dict:
        return {'X-MBX-APIKEY': self.api_key}

    def _sign(self, params: dict) -> dict:
        params = dict(params)
        params['timestamp'] = int(time.time() * 1000)
        params['recvWindow'] = self.recv_window
        query = urlencode(params)
        params['signature'] = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return params

    def _request(self, method: str, path: str, *, params: dict | None = None, signed: bool = False, retries: int = 1):
        call_params = self._sign(params or {}) if signed else (params or {})
        headers = self._headers() if signed else None
        url = f'{self.base_url}{path}'
        last_error = None
        for _ in range(retries + 1):
            try:
                timeout = self.private_timeout_sec if signed else self.request_timeout_sec
                response = requests.request(method, url, params=call_params, headers=headers, timeout=timeout)
                data = response.json()
                if response.status_code >= 400:
                    raise BinanceAPIError(f"HTTP {response.status_code}: {data.get('msg', data)}", code=data.get('code'), status_code=response.status_code)
                if isinstance(data, dict) and data.get('code', 0) not in (0, None):
                    raise BinanceAPIError(f"Binance error {data.get('code')}: {data.get('msg')}", code=data.get('code'))
                return data
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = BinanceAPIError(normalize_binance_error(exc))
            except ValueError as exc:
                last_error = BinanceAPIError(f'Invalid response: {exc}')
            except BinanceAPIError as exc:
                last_error = exc
                break
        raise last_error or BinanceAPIError('Unknown request error')

    def get_exchange_info(self, symbol: str) -> dict:
        return self._request('GET', '/api/v3/exchangeInfo', params={'symbol': symbol})

    def get_book_ticker(self, symbol: str) -> dict:
        return self._request('GET', '/api/v3/ticker/bookTicker', params={'symbol': symbol}, retries=2)

    def get_ticker(self, symbol: str) -> dict:
        return self._request('GET', '/api/v3/ticker/price', params={'symbol': symbol}, retries=2)

    def get_account(self) -> dict:
        return self._request('GET', '/api/v3/account', signed=True)

    def get_open_orders(self, symbol: str) -> list:
        return self._request('GET', '/api/v3/openOrders', params={'symbol': symbol}, signed=True)

    def create_limit_order(self, symbol: str, side: str, quantity: str, price: str) -> dict:
        return self._request('POST', '/api/v3/order', params={'symbol': symbol, 'side': side, 'type': 'LIMIT', 'timeInForce': 'GTC', 'quantity': quantity, 'price': price}, signed=True)

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        return self._request('DELETE', '/api/v3/order', params={'symbol': symbol, 'orderId': order_id}, signed=True)

    def cancel_all_orders(self, symbol: str) -> list:
        return self._request('DELETE', '/api/v3/openOrders', params={'symbol': symbol}, signed=True)
