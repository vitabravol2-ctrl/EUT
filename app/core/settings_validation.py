from __future__ import annotations


def validate_settings(values: dict) -> tuple[bool, list[str]]:
    messages: list[str] = []
    ok = True
    if not values.get('api_key', '').strip():
        ok = False
        messages.append('API key is empty.')
    if not values.get('api_secret', '').strip():
        ok = False
        messages.append('API secret is empty.')
    if values.get('trading_enabled') and values.get('read_only'):
        messages.append('Warning: Trading Enabled conflicts with Read Only ON.')
    mode = 'testnet' if values.get('testnet') else 'mainnet'
    messages.append(f'Mode: {mode}.')
    return ok, messages
