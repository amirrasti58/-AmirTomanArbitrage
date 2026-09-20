"""
============================================================
ARBITRAGE BOT
Wallex + BitPin + Ramzinex + Nobitex + Exir + Sarrafex

USDT / TOMAN
Order Book / Fees / Net Profit / Telegram Alerts
Continuous Monitoring

MONITORING ONLY
NO REAL TRADING
NO API KEYS REQUIRED FOR PUBLIC MARKET DATA
============================================================
"""

import os
import time
from datetime import datetime

import requests


# ============================================================
# SETTINGS
# ============================================================

REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "15"))

ORDERBOOK_LEVELS = int(
    os.environ.get("ORDERBOOK_LEVELS", "20")
)

TRADE_AMOUNT_TOMAN = float(
    os.environ.get("TRADE_AMOUNT_TOMAN", "50000000")
)

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
    "ORDER_TYPE", "taker"
).lower()


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN", ""
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID", ""
)


# ============================================================
# EXCHANGE FEES
#
# Values are percentages in decimal form:
# 0.0030 = 0.30%
#
# Can be overridden through GitHub Secrets / Variables.
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

    "Nobitex": {
        "maker": float(
            os.environ.get("NOBITEX_MAKER_FEE", "0.0020")
        ),
        "taker": float(
            os.environ.get("NOBITEX_TAKER_FEE", "0.0025")
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
        "ArbitrageMonitor/1.0"
    ),
    "Accept": "application/json",
})


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=0.0):
    """
    Safely convert a value to float.
    Handles strings containing commas.
    """

    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace(",", "").strip()

        return float(value)

    except (ValueError, TypeError):
        return default


def extract_price(item):
    """
    Extract price from common order formats.

    Supported examples:

    [price, volume]

    {"price": ..., "quantity": ...}

    {"price": ..., "amount": ...}

    {"rate": ..., "amount": ...}
    """

    if isinstance(item, (list, tuple)):
        if len(item) >= 2:
            return safe_float(item[0])

    if isinstance(item, dict):

        for key in (
            "price",
            "rate",
            "unit_price",
            "unitPrice",
        ):
            if key in item:
                return safe_float(item[key])

    return 0.0


def extract_volume(item):
    """
    Extract quantity/volume from common order formats.
    """

    if isinstance(item, (list, tuple)):
        if len(item) >= 2:
            return safe_float(item[1])

    if isinstance(item, dict):

        for key in (
            "quantity",
            "amount",
            "volume",
            "qty",
            "remaining",
        ):
            if key in item:
                return safe_float(item[key])

    return 0.0


def normalize_orders(orders, limit=ORDERBOOK_LEVELS):
    """
    Convert exchange-specific order formats into:

    [
        (price, volume),
        ...
    ]
    """

    result = []

    if not isinstance(orders, list):
        return result

    for item in orders:

        price = extract_price(item)
        volume = extract_volume(item)

        if price > 0 and volume > 0:

            result.append(
                (price, volume)
            )

        if len(result) >= limit:
            break

    return result


def create_market_data(
    name,
    asks,
    bids,
    extra=None
):
    """
    Standard exchange market-data structure.
    """

    return {
        "name": name,
        "asks": asks,
        "bids": bids,
        "extra": extra or {},
    }


def get_exchange_fee(exchange_name):
    """
    Return configured maker/taker fee.
    """

    exchange = EXCHANGE_FEES.get(
        exchange_name,
        {}
    )

    fee = exchange.get(
        ORDER_TYPE,
        exchange.get("taker", 0.0)
    )

    return safe_float(fee)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    """
    Send Telegram message.
    """

    if not TELEGRAM_BOT_TOKEN:
        print(
            "WARNING | TELEGRAM_BOT_TOKEN is not configured"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "WARNING | TELEGRAM_CHAT_ID is not configured"
        )
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        print(
            f"TELEGRAM HTTP STATUS: "
            f"{response.status_code}"
        )

        if response.ok:

            try:
                data = response.json()

                if data.get("ok") is True:
                    print(
                        "TELEGRAM SUCCESS: MESSAGE SENT"
                    )
                    return True

            except Exception:
                pass

        print(
            "TELEGRAM ERROR:",
            response.text[:500]
        )

    except Exception as exc:

        print(
            "TELEGRAM REQUEST ERROR:",
            exc
        )

    return False


# ============================================================
# WALLEX
# ============================================================

def get_wallex_market_data():

    name = "Wallex"

    url = (
        "https://api.wallex.ir/v1/depth"
        "?symbol=USDTTMN"
    )

    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        raw_data = data.get(
            "result",
            data
        )

        asks = normalize_orders(
            raw_data.get("ask", [])
        )

        if not asks:
            asks = normalize_orders(
                raw_data.get("asks", [])
            )

        bids = normalize_orders(
            raw_data.get("bid", [])
        )

        if not bids:
            bids = normalize_orders(
                raw_data.get("bids", [])
            )

        if not asks or not bids:
            raise ValueError(
                "Wallex returned empty orderbook"
            )

        print(
            f"SUCCESS | {name} | "
            f"ASKS={len(asks)} | "
            f"BIDS={len(bids)}"
        )

        return create_market_data(
            name,
            asks,
            bids
        )

    except Exception as exc:

        print(
            f"ERROR | {name} | {exc}"
        )

        return None


# ============================================================
# BITPIN
# ============================================================

def get_bitpin_market_data():

    name = "BitPin"

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

    for url in urls:

        try:

            response = SESSION.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            raw = data.get(
                "data",
                data
            )

            asks = normalize_orders(
                raw.get("asks", [])
            )

            bids = normalize_orders(
                raw.get("bids", [])
            )

            if asks and bids:

                print(
                    f"SUCCESS | {name} | "
                    f"ASKS={len(asks)} | "
                    f"BIDS={len(bids)}"
                )

                return create_market_data(
                    name,
                    asks,
                    bids
                )

        except Exception:
            continue

    print(
        f"ERROR | {name} | "
        "All BitPin orderbook endpoints failed"
    )

    return None


# ============================================================
# RAMZINEX HELPERS
# ============================================================

def recursive_find_pair_id(obj):
    """
    Search recursively for a USDT / IRR / IRT / TMN / TOMAN pair.

    Ramzinex response structures may contain nested data.
    """

    if isinstance(obj, dict):

        lower = {
            str(k).lower(): v
            for k, v in obj.items()
        }

        pair_text_parts = []

        for key in (
            "name",
            "symbol",
            "url_name",
            "pair",
            "pair_name",
            "market",
            "slug",
        ):

            if key in lower:
                pair_text_parts.append(
                    str(lower[key]).lower()
                )

        pair_text = " ".join(
            pair_text_parts
        )

        normalized = (
            pair_text
            .replace("_", "-")
            .replace("/", "-")
            .replace(" ", "-")
        )

        if "usdt" in normalized:

            quote_ok = any(
                x in normalized
                for x in (
                    "irr",
                    "irt",
                    "tmn",
                    "toman",
                )
            )

            if quote_ok:

                for key in (
                    "pair_id",
                    "pairid",
                    "id",
                ):

                    if key in lower:

                        candidate = lower[key]

                        try:
                            return int(candidate)
                        except Exception:
                            pass

        for value in obj.values():

            found = recursive_find_pair_id(
                value
            )

            if found is not None:
                return found

    elif isinstance(obj, list):

        for item in obj:

            found = recursive_find_pair_id(
                item
            )

            if found is not None:
                return found

    return None


def extract_ramzinex_orders(obj):
    """
    Recursively locate bids/asks in Ramzinex response.

    Returns:

    (asks, bids)
    """

    if isinstance(obj, dict):

        lower = {
            str(k).lower(): v
            for k, v in obj.items()
        }

        asks_raw = None
        bids_raw = None

        for key in (
            "asks",
            "ask",
            "sells",
            "sell",
        ):

            if key in lower:
                if isinstance(
                    lower[key],
                    list
                ):
                    asks_raw = lower[key]
                    break

        for key in (
            "bids",
            "bid",
            "buys",
            "buy",
        ):

            if key in lower:
                if isinstance(
                    lower[key],
                    list
                ):
                    bids_raw = lower[key]
                    break

        if asks_raw is not None and bids_raw is not None:

            asks = normalize_orders(
                asks_raw
            )

            bids = normalize_orders(
                bids_raw
            )

            if asks and bids:
                return asks, bids

        for value in obj.values():

            asks, bids = extract_ramzinex_orders(
                value
            )

            if asks and bids:
                return asks, bids

    elif isinstance(obj, list):

        for item in obj:

            asks, bids = extract_ramzinex_orders(
                item
            )

            if asks and bids:
                return asks, bids

    return [], []


def get_ramzinex_market_data():

    name = "Ramzinex"

    pairs_url = (
        "https://publicapi.ramzinex.com/"
        "exchange/api/v1.0/exchange/pairs"
    )

    try:

        pairs_response = SESSION.get(
            pairs_url,
            timeout=REQUEST_TIMEOUT,
        )

        pairs_response.raise_for_status()

        pairs_data = pairs_response.json()

    except Exception as exc:

        print(
            f"ERROR | {name} | "
            f"Pairs request failed: {exc}"
        )

        return None

    pair_id = recursive_find_pair_id(
        pairs_data
    )

    if pair_id is None:

        print(
            f"ERROR | {name} | "
            "USDT/IRT pair was not found"
        )

        return None

    print(
        f"INFO | {name} | "
        f"USDT pair ID={pair_id}"
    )

    orderbook_urls = [

        (
            "https://publicapi.ramzinex.com/"
            f"exchange/api/v1.0/exchange/"
            f"orderbooks/{pair_id}/buys_sells"
        ),

        (
            "https://publicapi.ramzinex.com/"
            f"exchange/api/v1.0/exchange/"
            f"orderbooks/{pair_id}"
        ),
    ]

    for orderbook_url in orderbook_urls:

        try:

            response = SESSION.get(
                orderbook_url,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            asks, bids = extract_ramzinex_orders(
                data
            )

            if asks and bids:

                # Ramzinex may report prices in IRR.
                #
                # If the values are clearly 10x larger
                # than normal Toman prices, convert them.
                #
                # This is intentionally conservative.

                top_ask = asks[0][0]
                top_bid = bids[0][0]

                if (
                    top_ask > 1_000_000
                    and top_bid > 1_000_000
                ):

                    asks = [
                        (
                            price / 10,
                            volume
                        )
                        for price, volume in asks
                    ]

                    bids = [
                        (
                            price / 10,
                            volume
                        )
                        for price, volume in bids
                    ]

                    print(
                        f"INFO | {name} | "
                        "IRR -> TOMAN conversion applied"
                    )

                print(
                    f"SUCCESS | {name} | "
                    f"ASKS={len(asks)} | "
                    f"BIDS={len(bids)}"
                )

                return create_market_data(
                    name,
                    asks,
                    bids,
                    {
                        "pair_id": pair_id
                    }
                )

        except Exception:
            continue

    print(
        f"ERROR | {name} | "
        "Ramzinex orderbook endpoints failed"
    )

    return None


# ============================================================
# NOBITEX
# ============================================================

def get_nobitex_market_data():

    name = "Nobitex"

    urls = [
        (
            "https://api.nobitex.ir/"
            "v3/orderbook/USDTIRT"
        ),
        (
            "https://api.nobitex.ir/"
            "v3/orderbook/all"
        ),
    ]

    last_error = None

    for url in urls:

        try:

            response = SESSION.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            # /v3/orderbook/USDTIRT
            if "asks" in data and "bids" in data:

                raw = data

            # /v3/orderbook/all
            elif isinstance(data, dict):

                raw = data.get(
                    "USDTIRT",
                    data.get(
                        "usdtirt",
                        {}
                    )
                )

            else:
                raw = {}

            asks = normalize_orders(
                raw.get("asks", [])
            )

            bids = normalize_orders(
                raw.get("bids", [])
            )

            if asks and bids:

                print(
                    f"SUCCESS | {name} | "
                    f"ASKS={len(asks)} | "
                    f"BIDS={len(bids)}"
                )

                return create_market_data(
                    name,
                    asks,
                    bids
                )

            last_error = (
                "Nobitex returned empty orderbook"
            )

        except Exception as exc:

            last_error = exc

            # Retry once for transient network errors.
            time.sleep(1)

    print(
        f"WARNING | {name} unavailable | "
        f"{last_error}"
    )

    return None


# ============================================================
# EXIR HELPERS
# ============================================================

def get_exir_symbol():

    constants_url = (
        "https://api.exir.io/v2/constants"
    )

    response = SESSION.get(
        constants_url,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    pairs = data.get(
        "pairs",
        {}
    )

    if isinstance(pairs, dict):

        # First try explicit pair metadata.
        for key, pair in pairs.items():

            if not isinstance(pair, dict):
                continue

            pair_base = str(
                pair.get(
                    "pair_base",
                    ""
                )
            ).lower()

            pair_quote = str(
                pair.get(
                    "pair_2",
                    ""
                )
            ).lower()

            if (
                pair_base == "usdt"
                and pair_quote in (
                    "irt",
                    "irr",
                    "tmn",
                    "toman",
                )
            ):

                return str(
                    pair.get(
                        "name",
                        key
                    )
                ).lower()

        # Fallback: inspect pair names.
        for key in pairs.keys():

            symbol = str(key).lower()

            normalized = (
                symbol
                .replace("_", "-")
                .replace("/", "-")
            )

            if (
                "usdt" in normalized
                and any(
                    quote in normalized
                    for quote in (
                        "irt",
                        "irr",
                        "tmn",
                        "toman",
                    )
                )
            ):

                return symbol

    # Final known candidate.
    candidates = [
        "usdt-irt",
        "usdt-irr",
        "usdt-tmn",
        "usdt-toman",
    ]

    return candidates[0]


def get_exir_market_data():

    name = "Exir"

    try:

        symbol = get_exir_symbol()

        print(
            f"INFO | {name} | "
            f"Symbol={symbol}"
        )

        url = (
            "https://api.exir.io/v2/orderbook"
        )

        response = SESSION.get(
            url,
            params={
                "symbol": symbol
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        # Official Exir response is:
        #
        # {
        #   "btc-usdt": {
        #       "bids": [...],
        #       "asks": [...]
        #   }
        # }
        #
        # Therefore the old parser which looked for
        # top-level asks/bids was incorrect.

        raw = data.get(
            symbol,
            {}
        )

        # Case-insensitive fallback.
        if not raw:

            symbol_lower = symbol.lower()

            for key, value in data.items():

                if (
                    str(key).lower()
                    == symbol_lower
                ):

                    raw = value
                    break

        asks = normalize_orders(
            raw.get("asks", [])
        )

        bids = normalize_orders(
            raw.get("bids", [])
        )

        if not asks or not bids:

            print(
                f"ERROR | {name} | "
                "Exir returned empty orderbook"
            )

            return None

        # Exir currently returns 10 levels.
        print(
            f"SUCCESS | {name} | "
            f"ASKS={len(asks)} | "
            f"BIDS={len(bids)}"
        )

        return create_market_data(
            name,
            asks,
            bids,
            {
                "symbol": symbol
            }
        )

    except Exception as exc:

        print(
            f"ERROR | {name} | {exc}"
        )

        return None


# ============================================================
# SARRAFEX
# ============================================================

def get_sarrafex_market_data():

    name = "Sarrafex"

    url = (
        "https://api.sarrafex.com/"
        "Exchanger/query/orderbook"
    )

    params = {
        "$filter": "pair eq 'USDT/IRT'"
    }

    try:

        response = SESSION.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        values = data.get(
            "value",
            []
        )

        if not isinstance(values, list):
            values = []

        selected = None

        for item in values:

            if not isinstance(item, dict):
                continue

            pair = str(
                item.get("Pair", "")
            ).upper()

            if pair in (
                "USDT/IRT",
                "USDTIRT",
                "USDT/IRR",
            ):

                selected = item
                break

        # If filter already returned one item,
        # accept it.
        if selected is None and len(values) == 1:
            selected = values[0]

        if selected is None:

            print(
                f"ERROR | {name} | "
                "USDT/IRT pair not found"
            )

            return None

        asks = normalize_orders(
            selected.get("asks", [])
        )

        bids = normalize_orders(
            selected.get("bids", [])
        )

        if not asks or not bids:

            print(
                f"ERROR | {name} | "
                "Sarrafex returned empty orderbook"
            )

            return None

        print(
            f"SUCCESS | {name} | "
            f"ASKS={len(asks)} | "
            f"BIDS={len(bids)}"
        )

        return create_market_data(
            name,
            asks,
            bids
        )

    except Exception as exc:

        print(
            f"ERROR | {name} | {exc}"
        )

        return None


# ============================================================
# ORDERBOOK SIMULATION
# ============================================================

def simulate_buy(
    asks,
    toman_amount,
    fee
):
    """
    Spend toman_amount on asks.

    Returns:

    {
        "usdt": acquired amount,
        "spent": actual toman,
        "average_price": ...
    }

    Fee is charged on acquired USDT.
    """

    remaining_toman = toman_amount

    total_usdt = 0.0
    total_spent = 0.0

    for price, volume in asks:

        if price <= 0 or volume <= 0:
            continue

        max_usdt = (
            remaining_toman / price
        )

        usdt_to_buy = min(
            volume,
            max_usdt
        )

        if usdt_to_buy <= 0:
            continue

        spent = (
            usdt_to_buy * price
        )

        total_usdt += usdt_to_buy
        total_spent += spent

        remaining_toman -= spent

        if remaining_toman <= 0.000001:
            break

    if total_usdt <= 0:
        return None

    # Buy-side fee.
    net_usdt = (
        total_usdt * (1 - fee)
    )

    average_price = (
        total_spent / total_usdt
    )

    return {
        "usdt": net_usdt,
        "gross_usdt": total_usdt,
        "spent": total_spent,
        "average_price": average_price,
    }


def simulate_sell(
    bids,
    usdt_amount,
    fee
):
    """
    Sell usdt_amount through bids.
    """

    remaining_usdt = usdt_amount

    total_toman = 0.0
    total_sold = 0.0

    for price, volume in bids:

        if price <= 0 or volume <= 0:
            continue

        usdt_to_sell = min(
            volume,
            remaining_usdt
        )

        if usdt_to_sell <= 0:
            continue

        received = (
            usdt_to_sell * price
        )

        total_toman += received
        total_sold += usdt_to_sell

        remaining_usdt -= usdt_to_sell

        if remaining_usdt <= 0.000001:
            break

    if total_sold <= 0:
        return None

    # Sell-side fee.
    net_toman = (
        total_toman * (1 - fee)
    )

    average_price = (
        total_toman / total_sold
    )

    return {
        "usdt": total_sold,
        "gross_toman": total_toman,
        "received": net_toman,
        "average_price": average_price,
    }


# ============================================================
# ARBITRAGE CALCULATION
# ============================================================

def calculate_arbitrage(
    buy_market,
    sell_market
):
    """
    Buy USDT on buy_market.
    Sell USDT on sell_market.

    All fees are included.
    """

    buy_exchange = buy_market["name"]
    sell_exchange = sell_market["name"]

    buy_fee = get_exchange_fee(
        buy_exchange
    )

    sell_fee = get_exchange_fee(
        sell_exchange
    )

    buy_result = simulate_buy(
        buy_market["asks"],
        TRADE_AMOUNT_TOMAN,
        buy_fee
    )

    if not buy_result:
        return None

    sell_result = simulate_sell(
        sell_market["bids"],
        buy_result["usdt"],
        sell_fee
    )

    if not sell_result:
        return None

    final_toman = sell_result[
        "received"
    ]

    profit = (
        final_toman
        - TRADE_AMOUNT_TOMAN
    )

    profit_percent = (
        profit
        / TRADE_AMOUNT_TOMAN
        * 100
    )

    return {
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,

        "buy_fee": buy_fee,
        "sell_fee": sell_fee,

        "buy_price": buy_result[
            "average_price"
        ],

        "sell_price": sell_result[
            "average_price"
        ],

        "usdt_bought": buy_result[
            "usdt"
        ],

        "final_toman": final_toman,

        "profit": profit,

        "profit_percent": profit_percent,
    }


# ============================================================
# FETCH ALL EXCHANGES
# ============================================================

def fetch_all_exchanges():

    fetchers = [
        get_wallex_market_data,
        get_bitpin_market_data,
        get_ramzinex_market_data,
        get_nobitex_market_data,
        get_exir_market_data,
        get_sarrafex_market_data,
    ]

    markets = {}

    for fetcher in fetchers:

        try:

            result = fetcher()

            if result:

                markets[
                    result["name"]
                ] = result

            else:

                print(
                    "WARNING | Exchange skipped"
                )

        except Exception as exc:

            print(
                "WARNING | Exchange skipped |",
                exc
            )

    return markets


# ============================================================
# TELEGRAM ALERT
# ============================================================

def send_arbitrage_alert(result):

    route = (
        f'{result["buy_exchange"]}'
        f'_TO_'
        f'{result["sell_exchange"]}'
    )

    now = time.time()

    last_time = last_alert_time.get(
        route,
        0
    )

    if (
        now - last_time
        < ALERT_COOLDOWN_SECONDS
    ):
        return

    if result["profit"] <= 0:
        return

    if (
        result["profit_percent"]
        < MIN_PROFIT_PERCENT
    ):
        return

    last_alert_time[route] = now

    message = (
        "🚨 ARBITRAGE OPPORTUNITY\n"
        "\n"
        f'BUY: {result["buy_exchange"]}\n'
        f'SELL: {result["sell_exchange"]}\n'
        "\n"
        f'Buy Avg: '
        f'{result["buy_price"]:,.0f} Toman\n'
        f'Sell Avg: '
        f'{result["sell_price"]:,.0f} Toman\n'
        "\n"
        f'Amount: '
        f'{TRADE_AMOUNT_TOMAN:,.0f} Toman\n'
        f'USDT: '
        f'{result["usdt_bought"]:.4f}\n'
        "\n"
        f'Profit: '
        f'{result["profit"]:,.0f} Toman\n'
        f'Profit %: '
        f'{result["profit_percent"]:.3f}%\n'
        "\n"
        f'Buy Fee: '
        f'{result["buy_fee"] * 100:.3f}%\n'
        f'Sell Fee: '
        f'{result["sell_fee"] * 100:.3f}%\n'
        "\n"
        "⚠️ Monitoring only\n"
        "No automatic trade executed."
    )

    send_telegram(message)


# ============================================================
# RANKING
# ============================================================

def print_ranking(results):

    if not results:

        print(
            "NO VALID ARBITRAGE ROUTES"
        )

        return

    results.sort(
        key=lambda x: x["profit"],
        reverse=True
    )

    print(
        "\n"
        "============================="
        "=============================="
    )

    print(
        "ARBITRAGE RANKING"
    )

    print(
        "============================="
        "=============================="
    )

    for index, result in enumerate(
        results,
        start=1
    ):

        print(
            f"{index:02d}. "
            f'{result["buy_exchange"]} '
            f'-> '
            f'{result["sell_exchange"]} | '
            f'Profit: '
            f'{result["profit"]:,.0f} Toman | '
            f'{result["profit_percent"]:.3f}%'
        )

    print(
        "============================="
        "=============================="
    )


# ============================================================
# ONE MONITORING CYCLE
# ============================================================

def run_cycle(cycle_number):

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print()
    print(
        "================================================"
    )
    print(
        f"MONITORING CYCLE #{cycle_number}"
    )
    print(
        f"CHECK: {now}"
    )
    print(
        "================================================"
    )

    markets = fetch_all_exchanges()

    exchange_count = len(markets)

    route_count = (
        exchange_count
        * (exchange_count - 1)
    )

    print()
    print(
        f"AVAILABLE EXCHANGES: "
        f"{exchange_count}"
    )

    print(
        f"AVAILABLE ROUTES: "
        f"{route_count}"
    )

    if exchange_count < 2:

        print(
            "WARNING | Not enough exchanges "
            "for arbitrage calculation"
        )

        return

    names = list(
        markets.keys()
    )

    results = []

    for buy_name in names:

        for sell_name in names:

            if buy_name == sell_name:
                continue

            buy_market = markets[
                buy_name
            ]

            sell_market = markets[
                sell_name
            ]

            result = calculate_arbitrage(
                buy_market,
                sell_market
            )

            if result:

                results.append(
                    result
                )

                # Telegram alert only for
                # positive results above threshold.
                send_arbitrage_alert(
                    result
                )

    print_ranking(results)


# ============================================================
# CONTINUOUS MONITORING
# ============================================================

def run_continuous_monitoring():

    start_time = time.time()

    cycle_number = 0

    while True:

        elapsed = (
            time.time()
            - start_time
        )

        if elapsed >= MAX_RUNTIME_SECONDS:

            print()
            print(
                "================================================"
            )

            print(
                "MAX RUNTIME REACHED"
            )

            print(
                f"Runtime: "
                f"{elapsed / 60:.1f} minutes"
            )

            print(
                "Stopping current GitHub Actions job."
            )

            print(
                "================================================"
            )

            break

        cycle_number += 1

        try:

            run_cycle(
                cycle_number
            )

        except Exception as exc:

            print(
                "CRITICAL CYCLE ERROR:",
                exc
            )

        elapsed = (
            time.time()
            - start_time
        )

        remaining = (
            MAX_RUNTIME_SECONDS
            - elapsed
        )

        if remaining <= 0:
            break

        sleep_time = min(
            CHECK_INTERVAL_SECONDS,
            remaining
        )

        print()
        print(
            f"Next check in "
            f"{sleep_time:.0f} seconds..."
        )

        time.sleep(
            sleep_time
        )


# ============================================================
# STARTUP
# ============================================================

def print_startup():

    print(
        "================================================"
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
        "Nobitex + Exir + Sarrafex"
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
        "================================================"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print_startup()

    startup_message = (
        "🤖 ARBITRAGE BOT STARTED\n"
        "\n"
        "Market: USDT / TOMAN\n"
        "Exchanges: 6\n"
        "Trade Amount: "
        f"{TRADE_AMOUNT_TOMAN:,.0f} Toman\n"
        "Minimum Profit: "
        f"{MIN_PROFIT_PERCENT:.2f}%\n"
        "Interval: "
        f"{CHECK_INTERVAL_SECONDS} sec\n"
        "Order Type: "
        f"{ORDER_TYPE.upper()}\n"
        "\n"
        "Monitoring only.\n"
        "No automatic trading."
    )

    send_telegram(
        startup_message
    )

    run_continuous_monitoring()

    print()
    print(
        "ARBITRAGE BOT FINISHED"
    )


if __name__ == "__main__":
    main()
