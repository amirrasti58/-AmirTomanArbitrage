"""
============================================================
ARBITRAGE BOT
Wallex + BitPin + Ramzinex + Phinix + Exir + Sarrafex

USDT / TOMAN

Features:
- Real Order Book
- Ask/Bid based calculation
- Multi-level order book simulation
- Buy fee + Sell fee
- Maker/Taker configurable per exchange
- 50,000,000 Toman simulated trade
- 1.5% minimum profit alert
- Telegram alerts
- Route cooldown
- Continuous monitoring
- GitHub Actions compatible
- Monitoring ONLY
- NO REAL TRADES
============================================================
"""

import os
import time
from datetime import datetime

import requests


# ============================================================
# SETTINGS
# ============================================================

REQUEST_TIMEOUT = 15

ORDERBOOK_LEVELS = 20

TRADE_AMOUNT_TOMAN = 50_000_000

MIN_PROFIT_PERCENT = float(
    os.environ.get("MIN_SPREAD_PERCENT", "1.5")
)

CHECK_INTERVAL_SECONDS = int(
    os.environ.get("CHECK_INTERVAL_SECONDS", "10")
)

ALERT_COOLDOWN_SECONDS = int(
    os.environ.get("ALERT_COOLDOWN_SECONDS", "60")
)

MAX_RUNTIME_SECONDS = int(
    os.environ.get("MAX_RUNTIME_SECONDS", "20700")
)

ORDER_TYPE = os.environ.get(
    "ORDER_TYPE",
    "taker"
).lower()


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# EXCHANGE FEES
# ============================================================
#
# Values are decimal percentages.
#
# Example:
# 0.0030 = 0.30%
#
# Every exchange can be overridden independently
# using GitHub Actions environment variables.
# ============================================================

EXCHANGE_FEES = {

    "Wallex": {
        "maker": float(
            os.environ.get("WALLEX_MAKER_FEE", "0.0025")
        ),
        "taker": float(
            os.environ.get("WALLEX_TAKER_FEE", "0.0030")
        ),
    },

    "BitPin": {
        "maker": float(
            os.environ.get("BITPIN_MAKER_FEE", "0.0002")
        ),
        "taker": float(
            os.environ.get("BITPIN_TAKER_FEE", "0.0005")
        ),
    },

    "Ramzinex": {
        "maker": float(
            os.environ.get("RAMZINEX_MAKER_FEE", "0.0020")
        ),
        "taker": float(
            os.environ.get("RAMZINEX_TAKER_FEE", "0.0025")
        ),
    },

    "Phinix": {
        "maker": float(
            os.environ.get("PHINIX_MAKER_FEE", "0.0020")
        ),
        "taker": float(
            os.environ.get("PHINIX_TAKER_FEE", "0.0020")
        ),
    },

    "Exir": {
        "maker": float(
            os.environ.get("EXIR_MAKER_FEE", "0.0030")
        ),
        "taker": float(
            os.environ.get("EXIR_TAKER_FEE", "0.0030")
        ),
    },

    "Sarrafex": {
        "maker": float(
            os.environ.get("SARRAFEX_MAKER_FEE", "0.0030")
        ),
        "taker": float(
            os.environ.get("SARRAFEX_TAKER_FEE", "0.0030")
        ),
    },
}


# ============================================================
# GLOBALS
# ============================================================

last_alert_time = {}

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; ArbitrageMonitor/1.0)"
    ),
    "Accept": "application/json",
})


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace(",", "").strip()

        return float(value)

    except Exception:
        return default


def extract_price(order):
    """
    Supports:
    [price, volume]
    {"price": ..., "quantity": ...}
    {"price": ..., "volume": ...}
    """

    if isinstance(order, (list, tuple)):

        if len(order) >= 1:
            return safe_float(order[0])

    if isinstance(order, dict):

        for key in (
            "price",
            "Price",
            "p",
        ):
            if key in order:
                return safe_float(order[key])

    return 0.0


def extract_volume(order):
    """
    Supports multiple common order book formats.
    """

    if isinstance(order, (list, tuple)):

        if len(order) >= 2:
            return safe_float(order[1])

    if isinstance(order, dict):

        for key in (
            "quantity",
            "volume",
            "amount",
            "available_amount",
            "qty",
            "Quantity",
            "Volume",
        ):
            if key in order:
                return safe_float(order[key])

    return 0.0


def normalize_orders(
    orders,
    reverse=False,
    limit=ORDERBOOK_LEVELS
):
    result = []

    if not isinstance(orders, list):
        return result

    for order in orders:

        price = extract_price(order)
        volume = extract_volume(order)

        if price <= 0 or volume <= 0:
            continue

        result.append({
            "price": price,
            "volume": volume,
        })

    result.sort(
        key=lambda x: x["price"],
        reverse=reverse
    )

    return result[:limit]


def create_market_data(
    asks,
    bids
):
    return {
        "asks": normalize_orders(
            asks,
            reverse=False
        ),
        "bids": normalize_orders(
            bids,
            reverse=True
        ),
    }


def get_exchange_fee(exchange_name):

    fees = EXCHANGE_FEES.get(
        exchange_name,
        {}
    )

    return fees.get(
        ORDER_TYPE,
        fees.get("taker", 0.0)
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(message):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "WARNING | Telegram bot token is not configured"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "WARNING | Telegram chat ID is not configured"
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        print(
            f"TELEGRAM | HTTP {response.status_code}"
        )

        if response.ok:
            return True

        print(
            "TELEGRAM ERROR:",
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "TELEGRAM ERROR:",
            str(e)
        )

        return False


# ============================================================
# WALLEX
# ============================================================

def get_wallex_market_data():

    url = (
        "https://api.wallex.ir/v1/depth"
        "?symbol=USDTTMN"
    )

    response = SESSION.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    asks = data.get("result", {}).get(
        "ask",
        data.get("asks", [])
    )

    bids = data.get("result", {}).get(
        "bid",
        data.get("bids", [])
    )

    market = create_market_data(
        asks,
        bids
    )

    if not market["asks"] or not market["bids"]:
        raise ValueError(
            "Wallex order book is empty"
        )

    print(
        f"SUCCESS | Wallex | "
        f"ASKS={len(market['asks'])} | "
        f"BIDS={len(market['bids'])}"
    )

    return market


# ============================================================
# BITPIN
# ============================================================

def get_bitpin_market_data():

    urls = [
        (
            "https://api.bitpin.market/"
            "v1/mth/orderbook/USDT_IRT/"
        ),
        (
            "https://api.bitpin.market/"
            "api/v1/mth/orderbook/USDT_IRT/"
        ),
        (
            "https://api.bitpin.org/"
            "api/v1/mth/orderbook/USDT_IRT/"
        ),
    ]

    last_error = None

    for url in urls:

        try:

            response = SESSION.get(
                url,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            data = response.json()

            asks = (
                data.get("asks")
                or data.get("ask")
                or data.get("sell")
                or []
            )

            bids = (
                data.get("bids")
                or data.get("bid")
                or data.get("buy")
                or []
            )

            if isinstance(data.get("data"), dict):

                nested = data["data"]

                asks = (
                    nested.get("asks")
                    or nested.get("ask")
                    or asks
                )

                bids = (
                    nested.get("bids")
                    or nested.get("bid")
                    or bids
                )

            market = create_market_data(
                asks,
                bids
            )

            if market["asks"] and market["bids"]:

                print(
                    f"SUCCESS | BitPin | "
                    f"ASKS={len(market['asks'])} | "
                    f"BIDS={len(market['bids'])}"
                )

                return market

        except Exception as e:

            last_error = e

    raise RuntimeError(
        f"BitPin unavailable | {last_error}"
    )


# ============================================================
# RAMZINEX
# ============================================================

def get_ramzinex_pair():

    pairs_url = (
        "https://publicapi.ramzinex.com/"
        "exchange/api/v1.0/exchange/pairs"
    )

    response = SESSION.get(
        pairs_url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    candidates = []

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "pairs",
            "items",
        ):

            value = data.get(key)

            if isinstance(value, list):
                candidates.extend(value)

            elif isinstance(value, dict):

                for item in value.values():

                    if isinstance(item, list):
                        candidates.extend(item)

                    elif isinstance(item, dict):
                        candidates.append(item)

    elif isinstance(data, list):
        candidates = data

    for item in candidates:

        if not isinstance(item, dict):
            continue

        text = str(item).lower()

        has_usdt = (
            "usdt" in text
            or "tether" in text
            or "تتر" in text
        )

        has_rial = (
            "rial" in text
            or "irr" in text
            or "irt" in text
            or "toman" in text
            or "tmn" in text
            or "تومان" in text
            or "ریال" in text
        )

        if has_usdt and has_rial:

            pair_id = (
                item.get("id")
                or item.get("pair_id")
                or item.get("pairId")
            )

            if pair_id is not None:
                return pair_id, item

    raise ValueError(
        "Ramzinex USDT/RIAL pair not found"
    )


def get_ramzinex_market_data():

    pair_id, pair_info = get_ramzinex_pair()

    print(
        f"INFO | Ramzinex | "
        f"Pair ID={pair_id} | "
        f"Pair={pair_info}"
    )

    urls = [
        (
            "https://publicapi.ramzinex.com/"
            "exchange/api/v1.0/exchange/"
            f"orderbooks/{pair_id}/buys_sells"
        ),
        (
            "https://publicapi.ramzinex.com/"
            "exchange/api/v1.0/exchange/"
            f"orderbooks/{pair_id}"
        ),
    ]

    last_error = None

    for url in urls:

        try:

            response = SESSION.get(
                url,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            data = response.json()

            root = data

            if isinstance(data, dict):

                if isinstance(
                    data.get("data"),
                    dict
                ):
                    root = data["data"]

            asks = (
                root.get("sells")
                or root.get("asks")
                or root.get("ask")
                or []
            )

            bids = (
                root.get("buys")
                or root.get("bids")
                or root.get("bid")
                or []
            )

            market = create_market_data(
                asks,
                bids
            )

            if not market["asks"] or not market["bids"]:
                continue

            # Ramzinex may return IRR.
            # If prices are much larger than normal Toman prices,
            # convert Rial -> Toman.
            first_ask = market["asks"][0]["price"]
            first_bid = market["bids"][0]["price"]

            if (
                first_ask > 1_000_000
                or first_bid > 1_000_000
            ):

                for side in (
                    market["asks"],
                    market["bids"]
                ):
                    for order in side:
                        order["price"] /= 10

                print(
                    "INFO | Ramzinex | "
                    "IRR -> TOMAN conversion applied"
                )

            print(
                f"SUCCESS | Ramzinex | "
                f"ASKS={len(market['asks'])} | "
                f"BIDS={len(market['bids'])}"
            )

            return market

        except Exception as e:

            last_error = e

    raise RuntimeError(
        f"Ramzinex unavailable | {last_error}"
    )


# ============================================================
# PHINIX
# ============================================================

def get_phinix_symbol():

    markets_url = (
        "https://api.phinix.ir/v1/markets"
    )

    response = SESSION.get(
        markets_url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    candidates = []

    if isinstance(data, dict):

        result = data.get("result")

        if isinstance(result, list):
            candidates.extend(result)

        elif isinstance(result, dict):
            candidates.extend(
                result.values()
            )

        markets = data.get("markets")

        if isinstance(markets, list):
            candidates.extend(markets)

        elif isinstance(markets, dict):
            candidates.extend(
                markets.values()
            )

    elif isinstance(data, list):

        candidates = data

    for item in candidates:

        if isinstance(item, str):

            symbol = item.upper()

            if symbol in (
                "USDTTMN",
                "USDTIRT",
                "USDTIRR",
                "USDTIRT"
            ):
                return symbol

        if isinstance(item, dict):

            text = str(item).lower()

            symbol = (
                item.get("symbol")
                or item.get("market")
                or item.get("name")
                or ""
            )

            symbol = str(symbol).upper()

            if (
                symbol in (
                    "USDTTMN",
                    "USDTIRT",
                    "USDTIRR"
                )
                or (
                    "usdt" in text
                    and (
                        "tmn" in text
                        or "irt" in text
                        or "irr" in text
                        or "toman" in text
                        or "تومان" in text
                    )
                )
            ):

                if symbol:
                    return symbol

    # Official documentation uses USDTTMN
    return "USDTTMN"


def get_phinix_market_data():

    symbol = get_phinix_symbol()

    print(
        f"INFO | Phinix | Symbol={symbol}"
    )

    url = (
        "https://api.phinix.ir/v1/depth"
    )

    response = SESSION.get(
        url,
        params={"symbol": symbol},
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    result = data.get(
        "result",
        data
    )

    if not isinstance(result, dict):
        raise ValueError(
            "Phinix invalid orderbook response"
        )

    asks = (
        result.get("ask")
        or result.get("asks")
        or []
    )

    bids = (
        result.get("bid")
        or result.get("bids")
        or []
    )

    market = create_market_data(
        asks,
        bids
    )

    if not market["asks"] or not market["bids"]:
        raise ValueError(
            "Phinix order book is empty"
        )

    print(
        f"SUCCESS | Phinix | "
        f"ASKS={len(market['asks'])} | "
        f"BIDS={len(market['bids'])}"
    )

    return market


# ============================================================
# EXIR
# ============================================================

def get_exir_symbol():

    url = (
        "https://api.exir.io/v2/constants"
    )

    response = SESSION.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    pairs = []

    if isinstance(data, dict):

        root = data.get(
            "data",
            data
        )

        if isinstance(root, dict):

            value = root.get("pairs")

            if isinstance(value, list):
                pairs = value

            elif isinstance(value, dict):
                pairs = list(
                    value.values()
                )

    for pair in pairs:

        if isinstance(pair, str):

            p = pair.lower()

            if (
                "usdt" in p
                and (
                    "irt" in p
                    or "irr" in p
                    or "tmn" in p
                    or "toman" in p
                )
            ):
                return p

        elif isinstance(pair, dict):

            text = str(pair).lower()

            symbol = (
                pair.get("symbol")
                or pair.get("name")
                or ""
            )

            symbol = str(symbol).lower()

            if (
                "usdt" in symbol
                and (
                    "irt" in symbol
                    or "irr" in symbol
                    or "tmn" in symbol
                    or "toman" in symbol
                )
            ):
                return symbol

            if (
                "usdt" in text
                and (
                    "irt" in text
                    or "irr" in text
                    or "tmn" in text
                    or "toman" in text
                )
            ):
                if symbol:
                    return symbol

    return "usdt-irt"


def get_exir_market_data():

    symbol = get_exir_symbol()

    print(
        f"INFO | Exir | Symbol={symbol}"
    )

    url = (
        "https://api.exir.io/v2/orderbook"
    )

    response = SESSION.get(
        url,
        params={"symbol": symbol},
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    root = data

    if isinstance(data, dict):

        if isinstance(
            data.get("data"),
            dict
        ):

            nested = data["data"]

            if isinstance(
                nested.get(symbol),
                dict
            ):
                root = nested[symbol]

            else:
                root = nested

        elif isinstance(
            data.get(symbol),
            dict
        ):
            root = data[symbol]

    asks = (
        root.get("asks")
        or root.get("ask")
        or []
    )

    bids = (
        root.get("bids")
        or root.get("bid")
        or []
    )

    market = create_market_data(
        asks,
        bids
    )

    if not market["asks"] or not market["bids"]:
        raise ValueError(
            "Exir order book is empty"
        )

    print(
        f"SUCCESS | Exir | "
        f"ASKS={len(market['asks'])} | "
        f"BIDS={len(market['bids'])}"
    )

    return market


# ============================================================
# SARRAFEX
# ============================================================

def get_sarrafex_market_data():

    url = (
        "https://api.sarrafex.com/"
        "Exchanger/query/orderbook"
    )

    params = {
        "$filter": "pair eq 'USDT/IRT'"
    }

    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    values = data.get(
        "value",
        []
    )

    target = None

    for item in values:

        if not isinstance(item, dict):
            continue

        pair = str(
            item.get("pair", "")
        ).upper()

        if (
            "USDT" in pair
            and (
                "IRT" in pair
                or "IRR" in pair
                or "TMN" in pair
            )
        ):

            target = item
            break

    if target is None:

        if values:
            target = values[0]

    if target is None:
        raise ValueError(
            "Sarrafex USDT order book not found"
        )

    asks = target.get(
        "asks",
        []
    )

    bids = target.get(
        "bids",
        []
    )

    market = create_market_data(
        asks,
        bids
    )

    if not market["asks"] or not market["bids"]:
        raise ValueError(
            "Sarrafex order book is empty"
        )

    print(
        f"SUCCESS | Sarrafex | "
        f"ASKS={len(market['asks'])} | "
        f"BIDS={len(market['bids'])}"
    )

    return market


# ============================================================
# BUY SIMULATION
# ============================================================

def simulate_buy(
    asks,
    toman_amount,
    fee_rate
):

    remaining_toman = toman_amount
    usdt_received = 0.0

    for order in asks:

        price = order["price"]
        volume = order["volume"]

        if price <= 0 or volume <= 0:
            continue

        max_toman = price * volume

        spend = min(
            remaining_toman,
            max_toman
        )

        usdt = spend / price

        usdt_received += usdt

        remaining_toman -= spend

        if remaining_toman <= 0:
            break

    if remaining_toman > 0:
        return None

    # Fee is deducted from received USDT
    usdt_after_fee = (
        usdt_received *
        (1 - fee_rate)
    )

    return usdt_after_fee


# ============================================================
# SELL SIMULATION
# ============================================================

def simulate_sell(
    bids,
    usdt_amount,
    fee_rate
):

    remaining_usdt = usdt_amount
    toman_received = 0.0

    for order in bids:

        price = order["price"]
        volume = order["volume"]

        if price <= 0 or volume <= 0:
            continue

        sell_volume = min(
            remaining_usdt,
            volume
        )

        toman_received += (
            sell_volume * price
        )

        remaining_usdt -= sell_volume

        if remaining_usdt <= 0:
            break

    if remaining_usdt > 0:
        return None

    # Fee deducted from received Toman
    toman_after_fee = (
        toman_received *
        (1 - fee_rate)
    )

    return toman_after_fee


# ============================================================
# ARBITRAGE CALCULATION
# ============================================================

def calculate_arbitrage(
    buy_exchange,
    buy_market,
    sell_exchange,
    sell_market
):

    buy_fee = get_exchange_fee(
        buy_exchange
    )

    sell_fee = get_exchange_fee(
        sell_exchange
    )

    usdt_bought = simulate_buy(
        buy_market["asks"],
        TRADE_AMOUNT_TOMAN,
        buy_fee
    )

    if usdt_bought is None:
        return None

    toman_received = simulate_sell(
        sell_market["bids"],
        usdt_bought,
        sell_fee
    )

    if toman_received is None:
        return None

    profit = (
        toman_received -
        TRADE_AMOUNT_TOMAN
    )

    profit_percent = (
        profit /
        TRADE_AMOUNT_TOMAN
    ) * 100

    return {
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,
        "profit": profit,
        "profit_percent": profit_percent,
        "usdt_bought": usdt_bought,
        "toman_received": toman_received,
        "buy_fee": buy_fee,
        "sell_fee": sell_fee,
    }


# ============================================================
# FETCH ALL EXCHANGES
# ============================================================

def fetch_all_exchanges():

    exchanges = {}

    # --------------------------------------------------------
    # Wallex
    # --------------------------------------------------------

    try:

        exchanges["Wallex"] = (
            get_wallex_market_data()
        )

    except Exception as e:

        print(
            f"WARNING | Wallex unavailable | {e}"
        )

    # --------------------------------------------------------
    # BitPin
    # --------------------------------------------------------

    try:

        exchanges["BitPin"] = (
            get_bitpin_market_data()
        )

    except Exception as e:

        print(
            f"WARNING | BitPin unavailable | {e}"
        )

    # --------------------------------------------------------
    # Ramzinex
    # --------------------------------------------------------

    try:

        exchanges["Ramzinex"] = (
            get_ramzinex_market_data()
        )

    except Exception as e:

        print(
            f"WARNING | Ramzinex unavailable | {e}"
        )

    # --------------------------------------------------------
    # Phinix
    # --------------------------------------------------------

    try:

        exchanges["Phinix"] = (
            get_phinix_market_data()
        )

    except Exception as e:

        print(
            f"WARNING | Phinix unavailable | {e}"
        )

    # --------------------------------------------------------
    # Exir
    # --------------------------------------------------------

    try:

        exchanges["Exir"] = (
            get_exir_market_data()
        )

    except Exception as e:

        print(
            f"WARNING | Exir unavailable | {e}"
        )

    # --------------------------------------------------------
    # Sarrafex
    # --------------------------------------------------------

    try:

        exchanges["Sarrafex"] = (
            get_sarrafex_market_data()
        )

    except Exception as e:

        print(
            f"WARNING | Sarrafex unavailable | {e}"
        )

    return exchanges


# ============================================================
# CALCULATE ALL ROUTES
# ============================================================

def calculate_all_routes(exchanges):

    results = []

    names = list(
        exchanges.keys()
    )

    for buy_exchange in names:

        for sell_exchange in names:

            if buy_exchange == sell_exchange:
                continue

            result = calculate_arbitrage(
                buy_exchange,
                exchanges[buy_exchange],
                sell_exchange,
                exchanges[sell_exchange]
            )

            if result is not None:

                results.append(result)

    results.sort(
        key=lambda x: x["profit"],
        reverse=True
    )

    return results


# ============================================================
# TELEGRAM ALERT
# ============================================================

def maybe_send_alert(result):

    profit = result["profit"]

    profit_percent = result[
        "profit_percent"
    ]

    if profit <= 0:
        return

    if profit_percent < MIN_PROFIT_PERCENT:
        return

    route_key = (
        f"{result['buy_exchange']}"
        "_TO_"
        f"{result['sell_exchange']}"
    )

    now = time.time()

    previous = last_alert_time.get(
        route_key,
        0
    )

    if (
        now - previous
        < ALERT_COOLDOWN_SECONDS
    ):
        return

    last_alert_time[
        route_key
    ] = now

    message = (
        "🚨 ARBITRAGE OPPORTUNITY\n\n"
        f"BUY: {result['buy_exchange']}\n"
        f"SELL: {result['sell_exchange']}\n\n"
        f"TRADE AMOUNT: "
        f"{TRADE_AMOUNT_TOMAN:,.0f} TOMAN\n\n"
        f"PROFIT: "
        f"{profit:,.0f} TOMAN\n"
        f"PROFIT %: "
        f"{profit_percent:.3f}%\n\n"
        f"USDT BOUGHT: "
        f"{result['usdt_bought']:.6f}\n"
        f"FINAL TOMAN: "
        f"{result['toman_received']:,.0f}\n\n"
        f"ORDER TYPE: {ORDER_TYPE.upper()}\n"
        f"MODE: MONITORING ONLY\n"
        f"NO REAL TRADES"
    )

    send_telegram_message(
        message
    )


# ============================================================
# PRINT RANKING
# ============================================================

def print_ranking(results):

    if not results:

        print(
            "NO VALID ARBITRAGE ROUTES"
        )

        return

    print()
    print(
        "=============================="
    )
    print(
        "ARBITRAGE RANKING"
    )
    print(
        "=============================="
    )

    for index, result in enumerate(
        results,
        start=1
    ):

        print(
            f"{index}. "
            f"{result['buy_exchange']} "
            f"-> "
            f"{result['sell_exchange']} "
            f"| Profit: "
            f"{result['profit']:,.0f} Toman "
            f"| "
            f"{result['profit_percent']:.3f}%"
        )

    print(
        "=============================="
    )
    print()


# ============================================================
# ONE CYCLE
# ============================================================

def run_cycle(cycle_number):

    print()
    print(
        "=================================================="
    )

    print(
        f"CYCLE #{cycle_number}"
    )

    print(
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print(
        "=================================================="
    )

    exchanges = fetch_all_exchanges()

    available_count = len(
        exchanges
    )

    route_count = (
        available_count *
        (available_count - 1)
    )

    print(
        f"AVAILABLE EXCHANGES: "
        f"{available_count}"
    )

    print(
        f"AVAILABLE ROUTES: "
        f"{route_count}"
    )

    if available_count < 2:

        print(
            "WARNING | Not enough exchanges "
            "for arbitrage calculation"
        )

        return

    results = calculate_all_routes(
        exchanges
    )

    print_ranking(results)

    for result in results:

        maybe_send_alert(
            result
        )


# ============================================================
# STARTUP MESSAGE
# ============================================================

def send_startup_message():

    message = (
        "🤖 ARBITRAGE BOT STARTED\n\n"
        "MODE: CONTINUOUS MONITORING\n"
        "EXCHANGES:\n"
        "Wallex + BitPin + Ramzinex + "
        "Phinix + Exir + Sarrafex\n\n"
        "MARKET: USDT / TOMAN\n"
        "TRADE AMOUNT: "
        f"{TRADE_AMOUNT_TOMAN:,.0f} TOMAN\n"
        "MIN PROFIT: "
        f"{MIN_PROFIT_PERCENT:.2f}%\n"
        "CHECK INTERVAL: "
        f"{CHECK_INTERVAL_SECONDS} seconds\n"
        "ORDER TYPE: "
        f"{ORDER_TYPE.upper()}\n"
        "MAX RUNTIME: "
        f"{MAX_RUNTIME_SECONDS / 3600:.2f} hours\n\n"
        "MODE: MONITORING ONLY\n"
        "NO REAL TRADES"
    )

    send_telegram_message(
        message
    )


# ============================================================
# CONTINUOUS MONITORING
# ============================================================

def continuous_monitoring():

    start_time = time.time()

    cycle_number = 0

    while True:

        elapsed = (
            time.time() -
            start_time
        )

        if elapsed >= MAX_RUNTIME_SECONDS:

            print()
            print(
                "MAX RUNTIME REACHED"
            )

            print(
                f"Runtime: "
                f"{elapsed / 3600:.2f} hours"
            )

            print(
                "Stopping cleanly..."
            )

            break

        cycle_number += 1

        try:

            run_cycle(
                cycle_number
            )

        except Exception as e:

            print(
                "ERROR | Cycle failed:",
                str(e)
            )

        elapsed = (
            time.time() -
            start_time
        )

        remaining = (
            MAX_RUNTIME_SECONDS -
            elapsed
        )

        if remaining <= 0:
            break

        sleep_time = min(
            CHECK_INTERVAL_SECONDS,
            remaining
        )

        print(
            f"NEXT CHECK IN "
            f"{sleep_time:.0f} SECONDS"
        )

        time.sleep(
            sleep_time
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "=================================================="
    )

    print(
        "ARBITRAGE BOT"
    )

    print(
        "MODE: CONTINUOUS MONITORING"
    )

    print(
        "EXCHANGES: "
        "Wallex + BitPin + Ramzinex + "
        "Phinix + Exir + Sarrafex"
    )

    print(
        "MARKET: USDT / TOMAN"
    )

    print(
        "ROUTES PER CYCLE: "
        "30 (when all 6 exchanges are available)"
    )

    print(
        f"TRADE AMOUNT: "
        f"{TRADE_AMOUNT_TOMAN:,.0f} TOMAN"
    )

    print(
        f"MIN PROFIT: "
        f"{MIN_PROFIT_PERCENT:.2f}%"
    )

    print(
        f"CHECK INTERVAL: "
        f"{CHECK_INTERVAL_SECONDS} seconds"
    )

    print(
        f"ORDER TYPE: "
        f"{ORDER_TYPE.upper()}"
    )

    print(
        f"MAX RUNTIME: "
        f"{MAX_RUNTIME_SECONDS / 3600:.2f} hours"
    )

    print(
        "MODE: MONITORING ONLY"
    )

    print(
        "NO REAL TRADES"
    )

    print(
        "=================================================="
    )

    print()

    send_startup_message()

    continuous_monitoring()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
