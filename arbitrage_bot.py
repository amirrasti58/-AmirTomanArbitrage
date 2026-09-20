"""
============================================================
ARBITRAGE BOT
Wallex + BitPin + Ramzinex + Exir

USDT / TOMAN
MONITORING ONLY
NO REAL TRADES

Features:
- Order Book based arbitrage
- Bid / Ask
- Order book depth
- Maker / Taker fees
- Net profit calculation
- Telegram alerts
- Market snapshot
- Continuous monitoring
- Daily / 7-day / total statistics
- Iran timezone
============================================================
"""

import os
import time
import json
from datetime import datetime
from zoneinfo import ZoneInfo

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

CHECK_INTERVAL_SECONDS = 10

ALERT_COOLDOWN_SECONDS = 60

MAX_RUNTIME_SECONDS = int(
    os.environ.get("MAX_RUNTIME_SECONDS", "20700")
)

ORDER_TYPE = os.environ.get("ORDER_TYPE", "taker").lower()

STATS_FILE = "arbitrage_stats.json"

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


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
# Values are decimal percentages:
#
# 0.0030 = 0.30%
# 0.0005 = 0.05%
#
# You can change them independently.
# ============================================================

FEES = {

    "Wallex": {
        "maker": 0.0025,
        "taker": 0.0030,
    },

    "BitPin": {
        "maker": 0.0002,
        "taker": 0.0005,
    },

    "Ramzinex": {
        "maker": 0.0020,
        "taker": 0.0025,
    },

    "Exir": {
        "maker": 0.0020,
        "taker": 0.0025,
    },
}


# ============================================================
# EXCHANGE ENABLE/DISABLE
# ============================================================

ENABLED_EXCHANGES = [
    "Wallex",
    "BitPin",
    "Ramzinex",
    "Exir",
]


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 ArbitrageBot/1.0",
    "Accept": "application/json",
})


# ============================================================
# STATE
# ============================================================

last_alert_time = {}

exchange_error_state = {}

runtime_start = time.time()

last_report_minute = None


# ============================================================
# BASIC HELPERS
# ============================================================

def now_tehran():
    return datetime.now(TEHRAN_TZ)


def format_toman(value):
    if value is None:
        return "-"

    return f"{value:,.0f}"


def safe_float(value, default=0.0):

    try:
        return float(value)
    except Exception:
        return default


def normalize_orderbook(data):
    """
    Converts orderbook levels into:
    [(price, volume), ...]
    """

    result = []

    if not isinstance(data, list):
        return result

    for item in data:

        try:

            if isinstance(item, (list, tuple)):

                if len(item) >= 2:
                    price = float(item[0])
                    volume = float(item[1])

                else:
                    continue

            elif isinstance(item, dict):

                price = float(
                    item.get("price", 0)
                )

                volume = float(
                    item.get(
                        "quantity",
                        item.get(
                            "volume",
                            item.get("amount", 0)
                        )
                    )
                )

            else:
                continue

            if price > 0 and volume > 0:

                result.append(
                    (price, volume)
                )

        except Exception:
            continue

    return result[:ORDERBOOK_LEVELS]


# ============================================================
# ERROR REPORTING
# ============================================================

def report_exchange_error(exchange, message):
    """
    Prevents the same error from being printed every 10 seconds.
    """

    current = time.time()

    previous = exchange_error_state.get(exchange)

    if previous:

        previous_message = previous.get("message")
        previous_time = previous.get("time", 0)

        if (
            previous_message == message
            and current - previous_time < 60
        ):
            return

    exchange_error_state[exchange] = {
        "message": message,
        "time": current,
    }

    print(
        f"[{exchange}] ERROR: {message}"
    )


# ============================================================
# WALLEX
# ============================================================

def get_wallex_orderbook():

    url = (
        "https://api.wallex.ir/v1/depth"
        "?symbol=USDTTMN"
    )

    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        raw = data.get("result", data)

        asks = normalize_orderbook(
            raw.get("ask", raw.get("asks", []))
        )

        bids = normalize_orderbook(
            raw.get("bid", raw.get("bids", []))
        )

        if not asks or not bids:
            raise ValueError(
                "Empty order book"
            )

        return {
            "exchange": "Wallex",
            "asks": asks,
            "bids": bids,
        }

    except Exception as e:

        report_exchange_error(
            "Wallex",
            str(e)
        )

        return None


# ============================================================
# BITPIN
# ============================================================

def get_bitpin_orderbook():

    """
    Correct BitPin public endpoint:

    /api/v1/mth/orderbook/USDT_IRT/

    No symbol query parameter is required.
    """

    url = (
        "https://api.bitpin.market"
        "/api/v1/mth/orderbook/USDT_IRT/"
    )

    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        asks = normalize_orderbook(
            data.get("asks", [])
        )

        bids = normalize_orderbook(
            data.get("bids", [])
        )

        if not asks or not bids:
            raise ValueError(
                "Empty order book"
            )

        return {
            "exchange": "BitPin",
            "asks": asks,
            "bids": bids,
        }

    except Exception as e:

        report_exchange_error(
            "BitPin",
            str(e)
        )

        return None


# ============================================================
# RAMZINEX
# ============================================================

def get_ramzinex_orderbook():

    """
    Ramzinex pair 11 was the confirmed USDT/IRR pair
    used in the previous working version.

    Ramzinex prices are converted from IRR to TOMAN.
    """

    pair_id = 11

    endpoints = [

        (
            "https://publicapi.ramzinex.com"
            f"/exchange/api/v1.0/exchange/"
            f"orderbooks/{pair_id}/buys_sells"
        ),

        (
            "https://publicapi.ramzinex.com"
            f"/exchange/api/v1.0/exchange/"
            f"orderbooks/{pair_id}"
        ),
    ]

    for url in endpoints:

        try:

            response = SESSION.get(
                url,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            data = response.json()

            raw = data.get("data", data)

            buys = []
            sells = []

            if isinstance(raw, dict):

                buys = raw.get(
                    "buys",
                    raw.get(
                        "bids",
                        raw.get("buy", [])
                    )
                )

                sells = raw.get(
                    "sells",
                    raw.get(
                        "asks",
                        raw.get("sell", [])
                    )
                )

            bids = normalize_orderbook(buys)
            asks = normalize_orderbook(sells)

            # Ramzinex pair is IRR.
            # Convert Rial -> Toman.
            bids = [
                (price / 10, volume)
                for price, volume in bids
            ]

            asks = [
                (price / 10, volume)
                for price, volume in asks
            ]

            if bids and asks:

                return {
                    "exchange": "Ramzinex",
                    "asks": asks,
                    "bids": bids,
                }

        except Exception as e:

            report_exchange_error(
                "Ramzinex",
                str(e)
            )

    return None


# ============================================================
# EXIR
# ============================================================

def find_exir_usdt_toman_symbol():

    """
    Exir:
    1. Read /v2/constants
    2. Find active/public USDT + Iranian fiat pair
    """

    url = (
        "https://api.exir.io/v2/constants"
    )

    response = SESSION.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    pairs = data.get("pairs", {})

    if not isinstance(pairs, dict):
        return None

    candidates = []

    for symbol, info in pairs.items():

        symbol_text = str(symbol).lower()

        if not isinstance(info, dict):
            continue

        active = info.get(
            "active",
            True
        )

        public = info.get(
            "is_public",
            True
        )

        if not active or not public:
            continue

        parts = symbol_text.replace(
            "_",
            "-"
        ).split("-")

        if len(parts) != 2:
            continue

        first = parts[0]
        second = parts[1]

        if "usdt" in parts and (
            "irt" in parts
            or "irr" in parts
            or "toman" in parts
            or "tmn" in parts
        ):

            candidates.append(
                symbol_text
            )

    if not candidates:
        return None

    # Prefer USDT/IRT
    preferred = [
        "usdt-irt",
        "usdt-irr",
        "usdt-toman",
        "usdt-tmn",
        "irt-usdt",
        "irr-usdt",
        "toman-usdt",
        "tmn-usdt",
    ]

    for item in preferred:

        if item in candidates:
            return item

    return candidates[0]


def get_exir_orderbook():

    try:

        symbol = (
            find_exir_usdt_toman_symbol()
        )

        if not symbol:

            raise ValueError(
                "No USDT/Toman market found in Exir constants"
            )

        url = (
            "https://api.exir.io/v2/orderbook"
        )

        response = SESSION.get(
            url,
            params={
                "symbol": symbol
            },
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        raw = data.get(
            symbol,
            data
        )

        if not isinstance(raw, dict):
            raise ValueError(
                "Invalid Exir orderbook response"
            )

        bids = normalize_orderbook(
            raw.get("bids", [])
        )

        asks = normalize_orderbook(
            raw.get("asks", [])
        )

        if not bids or not asks:
            raise ValueError(
                f"Empty order book for {symbol}"
            )

        # If Exir returns IRR, convert to Toman.
        if "irr" in symbol:

            bids = [
                (price / 10, volume)
                for price, volume in bids
            ]

            asks = [
                (price / 10, volume)
                for price, volume in asks
            ]

        return {
            "exchange": "Exir",
            "symbol": symbol,
            "asks": asks,
            "bids": bids,
        }

    except Exception as e:

        report_exchange_error(
            "Exir",
            str(e)
        )

        return None


# ============================================================
# FETCH ALL ORDER BOOKS
# ============================================================

def get_all_orderbooks():

    orderbooks = {}

    functions = {

        "Wallex":
            get_wallex_orderbook,

        "BitPin":
            get_bitpin_orderbook,

        "Ramzinex":
            get_ramzinex_orderbook,

        "Exir":
            get_exir_orderbook,
    }

    for exchange in ENABLED_EXCHANGES:

        function = functions.get(exchange)

        if function is None:
            continue

        result = function()

        if result:

            orderbooks[exchange] = result

    return orderbooks


# ============================================================
# FEES
# ============================================================

def get_fee(exchange):

    exchange_fees = FEES.get(
        exchange,
        {}
    )

    if ORDER_TYPE == "maker":

        return exchange_fees.get(
            "maker",
            0
        )

    return exchange_fees.get(
        "taker",
        0
    )


# ============================================================
# BUY FROM ORDER BOOK
# ============================================================

def calculate_buy(
    asks,
    amount_toman,
    fee
):

    remaining_toman = amount_toman

    received_usdt = 0

    spent_toman = 0

    average_price = 0

    for price, volume in asks:

        if remaining_toman <= 0:
            break

        max_cost = price * volume

        cost = min(
            remaining_toman,
            max_cost
        )

        usdt = cost / price

        spent_toman += cost

        received_usdt += usdt

        remaining_toman -= cost

    if spent_toman <= 0:
        return None

    # Fee charged against received USDT
    received_after_fee = (
        received_usdt * (1 - fee)
    )

    average_price = (
        spent_toman / received_usdt
    )

    return {
        "spent_toman": spent_toman,
        "usdt_before_fee": received_usdt,
        "usdt": received_after_fee,
        "average_price": average_price,
    }


# ============================================================
# SELL TO ORDER BOOK
# ============================================================

def calculate_sell(
    bids,
    usdt_amount,
    fee
):

    remaining_usdt = usdt_amount

    received_toman = 0

    sold_usdt = 0

    for price, volume in bids:

        if remaining_usdt <= 0:
            break

        amount = min(
            remaining_usdt,
            volume
        )

        received_toman += (
            amount * price
        )

        sold_usdt += amount

        remaining_usdt -= amount

    if sold_usdt <= 0:
        return None

    # Fee charged against received TOMAN
    received_after_fee = (
        received_toman * (1 - fee)
    )

    average_price = (
        received_toman / sold_usdt
    )

    return {
        "sold_usdt": sold_usdt,
        "received_toman": received_after_fee,
        "received_before_fee": received_toman,
        "average_price": average_price,
    }


# ============================================================
# ARBITRAGE ROUTE
# ============================================================

def calculate_route(
    buy_exchange,
    sell_exchange,
    orderbooks
):

    buy_book = orderbooks.get(
        buy_exchange
    )

    sell_book = orderbooks.get(
        sell_exchange
    )

    if not buy_book or not sell_book:
        return None

    buy_fee = get_fee(
        buy_exchange
    )

    sell_fee = get_fee(
        sell_exchange
    )

    buy_result = calculate_buy(
        buy_book["asks"],
        TRADE_AMOUNT_TOMAN,
        buy_fee
    )

    if not buy_result:
        return None

    sell_result = calculate_sell(
        sell_book["bids"],
        buy_result["usdt"],
        sell_fee
    )

    if not sell_result:
        return None

    actual_spent = (
        buy_result["spent_toman"]
    )

    final_toman = (
        sell_result["received_toman"]
    )

    net_profit = (
        final_toman - actual_spent
    )

    profit_percent = (
        net_profit
        / actual_spent
        * 100
    )

    return {

        "buy_exchange":
            buy_exchange,

        "sell_exchange":
            sell_exchange,

        "buy_price":
            buy_result["average_price"],

        "sell_price":
            sell_result["average_price"],

        "usdt":
            buy_result["usdt"],

        "spent":
            actual_spent,

        "received":
            final_toman,

        "net_profit":
            net_profit,

        "profit_percent":
            profit_percent,

        "buy_fee":
            buy_fee,

        "sell_fee":
            sell_fee,
    }


# ============================================================
# FIND ROUTES
# ============================================================

def calculate_all_routes(orderbooks):

    routes = []

    exchanges = list(
        orderbooks.keys()
    )

    for buy_exchange in exchanges:

        for sell_exchange in exchanges:

            if buy_exchange == sell_exchange:
                continue

            route = calculate_route(
                buy_exchange,
                sell_exchange,
                orderbooks
            )

            if route:
                routes.append(route)

    routes.sort(
        key=lambda x: x["net_profit"],
        reverse=True
    )

    return routes


# ============================================================
# MARKET SNAPSHOT
# ============================================================

def print_market_snapshot(
    orderbooks
):

    best_ask = None
    best_bid = None

    for exchange, book in orderbooks.items():

        if book["asks"]:

            ask_price = book["asks"][0][0]

            if (
                best_ask is None
                or ask_price < best_ask[0]
            ):

                best_ask = (
                    ask_price,
                    exchange
                )

        if book["bids"]:

            bid_price = book["bids"][0][0]

            if (
                best_bid is None
                or bid_price > best_bid[0]
            ):

                best_bid = (
                    bid_price,
                    exchange
                )

    print()
    print("========== MARKET SNAPSHOT ==========")

    if best_ask:

        print(
            f"Lowest Ask / Buy : "
            f"{best_ask[1]} -> "
            f"{format_toman(best_ask[0])}"
        )

    else:

        print(
            "Lowest Ask / Buy : -"
        )

    if best_bid:

        print(
            f"Highest Bid / Sell: "
            f"{best_bid[1]} -> "
            f"{format_toman(best_bid[0])}"
        )

    else:

        print(
            "Highest Bid / Sell: -"
        )

    print(
        "====================================="
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        return False

    if not TELEGRAM_CHAT_ID:
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {

        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            message,
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        return True

    except Exception as e:

        print(
            f"[Telegram] ERROR: {e}"
        )

        return False


# ============================================================
# ARBITRAGE ALERT
# ============================================================

def send_arbitrage_alert(route):

    buy_exchange = route[
        "buy_exchange"
    ]

    sell_exchange = route[
        "sell_exchange"
    ]

    route_key = (
        f"{buy_exchange}_TO_{sell_exchange}"
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

    profit = route[
        "net_profit"
    ]

    profit_percent = route[
        "profit_percent"
    ]

    if profit <= 0:
        return

    if profit_percent < MIN_PROFIT_PERCENT:
        return

    message = (
        "🚨 ARBITRAGE OPPORTUNITY\n\n"

        f"Buy: {buy_exchange}\n"
        f"Sell: {sell_exchange}\n\n"

        f"Buy price: "
        f"{format_toman(route['buy_price'])}\n"

        f"Sell price: "
        f"{format_toman(route['sell_price'])}\n\n"

        f"Capital: "
        f"{format_toman(route['spent'])} Toman\n"

        f"USDT: "
        f"{route['usdt']:.4f}\n\n"

        f"Net profit: "
        f"{format_toman(profit)} Toman\n"

        f"Profit: "
        f"{profit_percent:.3f}%\n\n"

        f"Buy fee: "
        f"{route['buy_fee'] * 100:.3f}%\n"

        f"Sell fee: "
        f"{route['sell_fee'] * 100:.3f}%\n\n"

        "⚠️ MONITORING ONLY\n"
        "NO REAL TRADE"
    )

    if send_telegram(message):

        last_alert_time[
            route_key
        ] = now


# ============================================================
# STATS
# ============================================================

def default_stats():

    return {

        "total_opportunities": 0,

        "total_profitable_opportunities": 0,

        "total_profit_toman": 0,

        "daily": {},

        "weekly": {},
    }


def load_stats():

    if not os.path.exists(
        STATS_FILE
    ):
        return default_stats()

    try:

        with open(
            STATS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, dict):
            return default_stats()

        return data

    except Exception:

        return default_stats()


def save_stats(stats):

    try:

        with open(
            STATS_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                stats,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            f"[Stats] Save error: {e}"
        )


def update_stats(
    stats,
    routes
):

    today = now_tehran().strftime(
        "%Y-%m-%d"
    )

    week = now_tehran().strftime(
        "%Y-W%W"
    )

    if today not in stats["daily"]:

        stats["daily"][today] = {
            "opportunities": 0,
            "profitable": 0,
            "profit_toman": 0,
        }

    if week not in stats["weekly"]:

        stats["weekly"][week] = {
            "opportunities": 0,
            "profitable": 0,
            "profit_toman": 0,
        }

    for route in routes:

        stats[
            "total_opportunities"
        ] += 1

        stats[
            "daily"
        ][today][
            "opportunities"
        ] += 1

        stats[
            "weekly"
        ][week][
            "opportunities"
        ] += 1

        if (
            route["net_profit"] > 0
            and
            route["profit_percent"]
            >= MIN_PROFIT_PERCENT
        ):

            profit = route[
                "net_profit"
            ]

            stats[
                "total_profitable_opportunities"
            ] += 1

            stats[
                "total_profit_toman"
            ] += profit

            stats[
                "daily"
            ][today][
                "profitable"
            ] += 1

            stats[
                "daily"
            ][today][
                "profit_toman"
            ] += profit

            stats[
                "weekly"
            ][week][
                "profitable"
            ] += 1

            stats[
                "weekly"
            ][week][
                "profit_toman"
            ] += profit

    save_stats(stats)


# ============================================================
# PERIODIC TELEGRAM REPORT
# ============================================================

REPORT_TIMES = {
    "10:00",
    "16:00",
    "18:00",
}


def send_periodic_report(stats):

    global last_report_minute

    now = now_tehran()

    current_time = now.strftime(
        "%H:%M"
    )

    if current_time not in REPORT_TIMES:
        return

    if last_report_minute == current_time:
        return

    last_report_minute = current_time

    today = now.strftime(
        "%Y-%m-%d"
    )

    week = now.strftime(
        "%Y-W%W"
    )

    daily = stats[
        "daily"
    ].get(
        today,
        {
            "opportunities": 0,
            "profitable": 0,
            "profit_toman": 0,
        }
    )

    weekly = stats[
        "weekly"
    ].get(
        week,
        {
            "opportunities": 0,
            "profitable": 0,
            "profit_toman": 0,
        }
    )

    message = (
        "📊 ARBITRAGE REPORT\n\n"

        f"Date: {today}\n"
        f"Time: {current_time} Tehran\n\n"

        "TODAY\n"
        f"Opportunities: "
        f"{daily['opportunities']}\n"

        f"Profitable: "
        f"{daily['profitable']}\n"

        f"Profit: "
        f"{format_toman(daily['profit_toman'])} Toman\n\n"

        "7-DAY PERIOD\n"
        f"Opportunities: "
        f"{weekly['opportunities']}\n"

        f"Profitable: "
        f"{weekly['profitable']}\n"

        f"Profit: "
        f"{format_toman(weekly['profit_toman'])} Toman\n\n"

        "TOTAL\n"
        f"Opportunities: "
        f"{stats['total_opportunities']}\n"

        f"Profitable: "
        f"{stats['total_profitable_opportunities']}\n"

        f"Total profit: "
        f"{format_toman(stats['total_profit_toman'])} Toman"
    )

    send_telegram(message)


# ============================================================
# PRINT ROUTES
# ============================================================

def print_routes(routes):

    print()
    print(
        "================ ROUTE RANKING ================"
    )

    if not routes:

        print(
            "No valid arbitrage routes."
        )

        print(
            "================================================"
        )

        return

    for index, route in enumerate(
        routes,
        start=1
    ):

        print(
            f"{index}. "
            f"{route['buy_exchange']} "
            f"-> "
            f"{route['sell_exchange']} | "
            f"Profit: "
            f"{route['profit_percent']:.3f}% | "
            f"Net: "
            f"{format_toman(route['net_profit'])} Toman"
        )

    print(
        "================================================"
    )


# ============================================================
# STARTUP MESSAGE
# ============================================================

def send_startup_message():

    message = (
        "🤖 ARBITRAGE BOT STARTED\n\n"

        "MONITORING ONLY\n"
        "NO REAL TRADES\n\n"

        "Exchanges:\n"
        "• Wallex\n"
        "• BitPin\n"
        "• Ramzinex\n"
        "• Exir\n\n"

        f"Capital: "
        f"{format_toman(TRADE_AMOUNT_TOMAN)} Toman\n"

        f"Minimum profit: "
        f"{MIN_PROFIT_PERCENT:.3f}%\n"

        f"Interval: "
        f"{CHECK_INTERVAL_SECONDS} seconds\n"

        f"Order type: "
        f"{ORDER_TYPE}\n\n"

        "Timezone: Asia/Tehran"
    )

    send_telegram(message)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "=============================================="
    )
    print(
        "ARBITRAGE BOT STARTED"
    )
    print(
        "MONITORING ONLY - NO REAL TRADES"
    )
    print(
        "=============================================="
    )

    print(
        f"Capital: "
        f"{format_toman(TRADE_AMOUNT_TOMAN)} Toman"
    )

    print(
        f"Minimum profit: "
        f"{MIN_PROFIT_PERCENT:.3f}%"
    )

    print(
        f"Interval: "
        f"{CHECK_INTERVAL_SECONDS} seconds"
    )

    print(
        f"Order type: "
        f"{ORDER_TYPE}"
    )

    print(
        "Exchanges: "
        + ", ".join(ENABLED_EXCHANGES)
    )

    print(
        "=============================================="
    )

    send_startup_message()

    stats = load_stats()

    while True:

        if (
            time.time()
            - runtime_start
            >= MAX_RUNTIME_SECONDS
        ):

            print()
            print(
                "Maximum runtime reached."
            )

            print(
                "Stopping safely."
            )

            break

        cycle_start = time.time()

        print()
        print(
            "------------------------------------------------"
        )

        print(
            f"Time: "
            f"{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}"
            f" Tehran"
        )

        print(
            "Fetching order books..."
        )

        orderbooks = (
            get_all_orderbooks()
        )

        print(
            f"Valid order books: "
            f"{len(orderbooks)}/"
            f"{len(ENABLED_EXCHANGES)}"
        )

        if orderbooks:

            print_market_snapshot(
                orderbooks
            )

            routes = calculate_all_routes(
                orderbooks
            )

            print_routes(routes)

            if routes:

                best_route = routes[0]

                print()
                print(
                    "BEST ROUTE"
                )

                print(
                    f"{best_route['buy_exchange']}"
                    f" -> "
                    f"{best_route['sell_exchange']}"
                )

                print(
                    f"Net profit: "
                    f"{format_toman(best_route['net_profit'])}"
                    f" Toman"
                )

                print(
                    f"Profit: "
                    f"{best_route['profit_percent']:.3f}%"
                )

                send_arbitrage_alert(
                    best_route
                )

            update_stats(
                stats,
                routes
            )

        else:

            print(
                "No valid order books available."
            )

        send_periodic_report(
            stats
        )

        elapsed = (
            time.time()
            - cycle_start
        )

        sleep_time = max(
            0,
            CHECK_INTERVAL_SECONDS
            - elapsed
        )

        time.sleep(
            sleep_time
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print(
            "Bot stopped manually."
        )

    except Exception as e:

        print()
        print(
            f"FATAL ERROR: {e}"
        )

        raise
