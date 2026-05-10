from app.core.pair_profiles import get_pair_config, split_symbol_assets


def test_split_symbol_assets_dynamic():
    assert split_symbol_assets('EURIUSDT') == ('EURI', 'USDT')
    assert split_symbol_assets('BTCU') == ('BTC', 'U')


def test_get_pair_config_btcu_quote_asset_u():
    cfg = get_pair_config('BTCU')
    assert cfg.base_asset == 'BTC'
    assert cfg.quote_asset == 'U'


def test_get_pair_config_fallback_dynamic_symbol():
    cfg = get_pair_config('ABCUSDC')
    assert cfg.base_asset == 'ABC'
    assert cfg.quote_asset == 'USDC'
