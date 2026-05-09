BUTTON_H = 30
BUTTON_MIN_W = 120
INPUT_H = 28
TABLE_ROW_H = 28
TABLE_HEADER_H = 30
APP_FONT_PT = 10
VALUE_LABEL_MIN_W = 120

OPEN_ORDERS_COL_WIDTHS = {
    0: 140,  # ID
    1: 70,   # Side
    2: 90,   # Price
    3: 90,   # Qty
    4: 90,   # Filled
    5: 80,   # Filled %
    6: 100,  # Status
    7: 80,   # Age
}

RU_LABELS = {
    'Runtime Status': 'Статус системы',
    'PUBLIC REST': 'Публичный REST',
    'ACCOUNT': 'Аккаунт',
    'POLLING': 'Опрос',
    'PRIVATE': 'Приватный канал',
    'TRADING': 'Торговля',
    'READONLY': 'Только чтение',
    'LATENCY': 'Задержка',
    'Settings': 'Настройки',
}

AUTH_FAILED_MSG = '[AUTH] Ошибка авторизации Binance: проверьте API key, IP whitelist, Spot permissions и режим testnet/mainnet. Приватный опрос остановлен. Private polling paused.'
