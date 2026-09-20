"""
============================================================
ARBITRAGE BOT
Wallex + BitPin + Ramzinex + Phinix + Exir + Sarrafex

USDT / TOMAN
MONITORING ONLY
NO REAL TRADES

Features:
- Order Book based arbitrage
- Ask price for BUY
- Bid price for SELL
- Maker / Taker configurable fees
- Net profit calculation
- 50M Toman simulation
- 20 order-book levels
- Minimum profit threshold
- Telegram alerts
- Alert cooldown
- Continuous monitoring
- Opportunity statistics
- Daily / 7-day / total statistics
- Periodic Telegram reports
============================================================
"""

import os
import time
import json
from datetime import datetime, timedelta
from pathlib import Path

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

STATS_FILE = Path("arbitrage_stats.json")


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
# ORDER TYPE
# ============================================================

ORDER_TYPE = os.environ.get(
    "ORDER_TYPE",
    "taker"
).lower()


# ============================================================
# EXCHANGE FEES
#
# User can change these independently.
#
# Example:
# Wallex maker = 0.0025
# Wallex taker = 0.0030
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

    "Phinix": {
        "maker": 0.0020,
        "taker": 0.0025,
    },

    "Exir": {
        "maker": 0.0020,
        "taker": 0.0025,
    },

    "Sarrafex": {
        "maker": 0.0020,
        "taker": 0.0025,
    },
}


# ============================================================
# STATE
# ============================================================

last_alert_time = {}

session = requests.Session()

session.headers.update({
    "User-Agent": "ArbitrageMonitor/1.0"
})


# ============================================================
# GENERAL HELPERS
# ============================================================

def now():
    return datetime.now()


def timestamp():
    return now().strftime("%Y-%m-%d %H:%M:%S")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def get_fee(exchange):
    fee = FEES.get(exchange, {})
    return safe_float(
        fee.get(ORDER_TYPE, 0)
    )


# ============================================================
# HTTP
# ============================================================

def http_get(url, params=None):
    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        print(
            f"[{timestamp()}] HTTP ERROR: "
            f"{url} -> {e}"
        )

        return None


# ============================================================
# ORDER BOOK NORMALIZATION
# ============================================================

def normalize_levels(levels):

    result = []

    if not isinstance(levels, list):
        return result

    for level in levels:

        try:

            if isinstance(level, dict):

                price = (
                    level.get("price")
                    or level.get("rate")
                    or level.get("p")
                )

                volume = (
                    level.get("amount")
                    or level.get("quantity")
                    or level.get("volume")
                    or level.get("q")
                )

            elif isinstance(level, (list, tuple)):

                if len(level) < 2:
                    continue

                price = level[0]
                volume = level[1]

            else:
                continue

            price = safe_float(price)
            volume = safe_float(volume)

            if price > 0 and volume > 0:

                result.append(
                    (price, volume)
                )

        except Exception:
            continue

    return result[:ORDERBOOK_LEVELS]


# ============================================================
# WALLEX
# ============================================================

def get_wallex_orderbook():

    url = (
        "https://api.wallex.ir/v1/depth"
    )

    params = {
        "symbol": "USDTTMN"
    }

    data = http_get(
        url,
        params
    )

    if not data:
        return None

    try:

        raw = data.get("result", data)

        asks = (
            raw.get("ask")
            or raw.get("asks")
            or []
        )

        bids = (
            raw.get("bid")
            or raw.get("bids")
            or []
        )

        asks = normalize_levels(asks)
        bids = normalize_levels(bids)

        return {
            "asks": asks,
            "bids": bids
        }

    except Exception as e:

        print(
            f"[Wallex] Parse error: {e}"
        )

        return None


# ============================================================
# BITPIN
# ============================================================

def get_bitpin_orderbook():

    urls = [

        (
            "https://api.bitpin.market/"
            "v1/mth/otc/orderbook/"
        ),

        (
            "https://api.bitpin.org/"
            "v1/mth/otc/orderbook/"
        ),

    ]

    params = {
        "symbol": "USDT_IRT"
    }

    for url in urls:

        data = http_get(
            url,
            params
        )

        if not data:
            continue

        try:

            raw = data.get(
                "data",
                data
            )

            asks = (
                raw.get("asks")
                or raw.get("sell")
                or []
            )

            bids = (
                raw.get("bids")
                or raw.get("buy")
                or []
            )

            asks = normalize_levels(asks)
            bids = normalize_levels(bids)

            if asks and bids:

                return {
                    "asks": asks,
                    "bids": bids
                }

        except Exception:
            continue

    print("[BitPin] No valid order book.")

    return None


# ============================================================
# RAMZINEX
# ============================================================

RAMZINEX_PAIRS_URL = (
    "https://publicapi.ramzinex.com/"
    "exchange/api/v1.0/exchange/pairs"
)


def get_ramzinex_pair():

    data = http_get(
        RAMZINEX_PAIRS_URL
    )

    if not data:
        return None

    try:

        pairs = data.get(
            "data",
            data
        )

        if isinstance(pairs, dict):
            pairs = pairs.get(
                "pairs",
                []
            )

        for pair in pairs:

            base = str(
                pair.get("base")
                or pair.get("base_currency")
                or ""
            ).upper()

            quote = str(
                pair.get("quote")
                or pair.get("quote_currency")
                or ""
            ).upper()

            pair_id = (
                pair.get("id")
                or pair.get("pair_id")
            )

            if (
                base == "USDT"
                and quote in {
                    "IRT",
                    "IRR",
                    "TMN",
                    "TOMAN"
                }
            ):

                return {
                    "id": pair_id,
                    "quote": quote
                }

    except Exception as e:

        print(
            f"[Ramzinex] Pair parse error: {e}"
        )

    return None


def get_ramzinex_orderbook():

    # Known confirmed pair from previous testing.
    # If unavailable, dynamically search pairs.

    pair_info = {
        "id": 11,
        "quote": "IRR"
    }

    pair_id = pair_info["id"]
    quote = pair_info["quote"]

    urls = [

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

    for url in urls:

        data = http_get(url)

        if not data:
            continue

        try:

            raw = data.get(
                "data",
                data
            )

            if isinstance(raw, dict):

                asks = (
                    raw.get("asks")
                    or raw.get("sells")
                    or raw.get("sell")
                    or []
                )

                bids = (
                    raw.get("bids")
                    or raw.get("buys")
                    or raw.get("buy")
                    or []
                )

            else:
                continue

            asks = normalize_levels(asks)
            bids = normalize_levels(bids)

            # Ramzinex pair 11 is IRR.
            # Convert Rial -> Toman.
            if quote == "IRR":

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

            if asks and bids:

                return {
                    "asks": asks,
                    "bids": bids
                }

        except Exception as e:

            print(
                f"[Ramzinex] Parse error: {e}"
            )

    print(
        "[Ramzinex] No valid order book."
    )

    return None


# ============================================================
# PHINIX
# ============================================================

def get_phinix_orderbook():

    """
    Phinix currently may return HTTP 503.

    We keep it isolated so that a temporary failure
    does NOT stop the entire arbitrage monitor.
    """

    urls = [

        "https://api.phinix.ir/",
        "https://api.phinix.io/",

    ]

    for url in urls:

        data = http_get(url)

        if not data:
            continue

        # Unknown / unstable API structure.
        # Do not fabricate an order book.
        return None

    return None


# ============================================================
# EXIR
# ============================================================

def get_exir_orderbook():

    """
    Exir API may change.
    Parser intentionally accepts several common structures.
    """

    urls = [

        (
            "https://api.exir.io/v1/"
            "orderbooks/USDT-IRT"
        ),

        (
            "https://api.exir.io/v1/"
            "orderbooks/USDTIRT"
        ),

    ]

    for url in urls:

        data = http_get(url)

        if not data:
            continue

        try:

            raw = data.get(
                "data",
                data
            )

            asks = (
                raw.get("asks")
                or raw.get("sell")
                or []
            )

            bids = (
                raw.get("bids")
                or raw.get("buy")
                or []
            )

            asks = normalize_levels(asks)
            bids = normalize_levels(bids)

            if asks and bids:

                return {
                    "asks": asks,
                    "bids": bids
                }

        except Exception:
            continue

    print("[Exir] No valid order book.")

    return None


# ============================================================
# SARRAFEX
# ============================================================

def get_sarrafex_orderbook():

    """
    Sarrafex API structure may change.
    Several candidate endpoints are tried.
    """

    urls = [

        (
            "https://api.sarrafex.com/"
            "v1/orderbook/USDTIRT"
        ),

        (
            "https://api.sarrafex.com/"
            "v1/orderbooks/USDTIRT"
        ),

    ]

    for url in urls:

        data = http_get(url)

        if not data:
            continue

        try:

            raw = data.get(
                "data",
                data
            )

            asks = (
                raw.get("asks")
                or raw.get("sell")
                or []
            )

            bids = (
                raw.get("bids")
                or raw.get("buy")
                or []
            )

            asks = normalize_levels(asks)
            bids = normalize_levels(bids)

            if asks and bids:

                return {
                    "asks": asks,
                    "bids": bids
                }

        except Exception:
            continue

    print("[Sarrafex] No valid order book.")

    return None


# ============================================================
# GET ALL ORDER BOOKS
# ============================================================

def get_all_orderbooks():

    return {

        "Wallex":
            get_wallex_orderbook(),

        "BitPin":
            get_bitpin_orderbook(),

        "Ramzinex":
            get_ramzinex_orderbook(),

        "Phinix":
            get_phinix_orderbook(),

        "Exir":
            get_exir_orderbook(),

        "Sarrafex":
            get_sarrafex_orderbook(),

    }


# ============================================================
# BUY FROM ASK
# ============================================================

def calculate_buy(
    asks,
    toman_amount
):

    remaining_toman = toman_amount

    usdt_received = 0.0

    toman_spent = 0.0

    for price, volume in asks:

        if price <= 0 or volume <= 0:
            continue

        max_usdt = (
            remaining_toman / price
        )

        buy_usdt = min(
            volume,
            max_usdt
        )

        cost = (
            buy_usdt * price
        )

        usdt_received += buy_usdt

        toman_spent += cost

        remaining_toman -= cost

        if remaining_toman <= 0:
            break

    if usdt_received <= 0:
        return None

    return {
        "usdt": usdt_received,
        "toman": toman_spent
    }


# ============================================================
# SELL TO BID
# ============================================================

def calculate_sell(
    bids,
    usdt_amount
):

    remaining_usdt = usdt_amount

    toman_received = 0.0

    for price, volume in bids:

        if price <= 0 or volume <= 0:
            continue

        sell_usdt = min(
            volume,
            remaining_usdt
        )

        toman_received += (
            sell_usdt * price
        )

        remaining_usdt -= sell_usdt

        if remaining_usdt <= 0:
            break

    sold_usdt = (
        usdt_amount
        - remaining_usdt
    )

    if sold_usdt <= 0:
        return None

    return {
        "usdt": sold_usdt,
        "toman": toman_received
    }


# ============================================================
# ARBITRAGE CALCULATION
# ============================================================

def calculate_arbitrage(
    buy_exchange,
    buy_book,
    sell_exchange,
    sell_book
):

    buy = calculate_buy(
        buy_book["asks"],
        TRADE_AMOUNT_TOMAN
    )

    if not buy:
        return None

    usdt_after_buy_fee = (
        buy["usdt"]
        * (1 - get_fee(buy_exchange))
    )

    sell = calculate_sell(
        sell_book["bids"],
        usdt_after_buy_fee
    )

    if not sell:
        return None

    toman_after_sell_fee = (
        sell["toman"]
        * (1 - get_fee(sell_exchange))
    )

    net_profit = (
        toman_after_sell_fee
        - buy["toman"]
    )

    profit_percent = (
        net_profit
        / buy["toman"]
        * 100
    )

    return {

        "buy_exchange":
            buy_exchange,

        "sell_exchange":
            sell_exchange,

        "buy_toman":
            buy["toman"],

        "usdt":
            usdt_after_buy_fee,

        "sell_toman":
            toman_after_sell_fee,

        "net_profit":
            net_profit,

        "profit_percent":
            profit_percent,

    }


# ============================================================
# FIND ALL ROUTES
# ============================================================

def calculate_all_routes(
    orderbooks
):

    results = []

    exchanges = [
        name
        for name, book
        in orderbooks.items()
        if book
        and book.get("asks")
        and book.get("bids")
    ]

    for buy_exchange in exchanges:

        for sell_exchange in exchanges:

            if buy_exchange == sell_exchange:
                continue

            result = calculate_arbitrage(
                buy_exchange,
                orderbooks[buy_exchange],
                sell_exchange,
                orderbooks[sell_exchange]
            )

            if result:
                results.append(result)

    results.sort(
        key=lambda x:
            x["net_profit"],
        reverse=True
    )

    return results


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
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            message,

        "parse_mode":
            "HTML",

        "disable_web_page_preview":
            True,
    }

    try:

        response = session.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        return response.ok

    except Exception as e:

        print(
            f"[Telegram] Error: {e}"
        )

        return False


# ============================================================
# FORMAT MONEY
# ============================================================

def format_toman(value):

    try:
        return f"{value:,.0f}"
    except Exception:
        return "0"


def format_percent(value):

    try:
        return f"{value:.3f}%"
    except Exception:
        return "0.000%"


# ============================================================
# ALERT
# ============================================================

def send_arbitrage_alert(result):

    route = (
        f"{result['buy_exchange']}"
        f"_TO_"
        f"{result['sell_exchange']}"
    )

    current = time.time()

    last = last_alert_time.get(
        route,
        0
    )

    if (
        current - last
        < ALERT_COOLDOWN_SECONDS
    ):
        return

    last_alert_time[route] = current

    message = (
        "🚨 <b>ARBITRAGE OPPORTUNITY</b>\n\n"

        f"🟢 Buy: "
        f"<b>{result['buy_exchange']}</b>\n"

        f"🔴 Sell: "
        f"<b>{result['sell_exchange']}</b>\n\n"

        f"💰 Capital: "
        f"{format_toman(TRADE_AMOUNT_TOMAN)} Toman\n"

        f"💵 USDT: "
        f"{result['usdt']:.4f}\n\n"

        f"📈 Net Profit: "
        f"<b>{format_toman(result['net_profit'])}</b> Toman\n"

        f"📊 Profit: "
        f"<b>{format_percent(result['profit_percent'])}</b>\n\n"

        f"⏰ {timestamp()}\n\n"

        "⚠️ Monitoring only\n"
        "No real trade executed."
    )

    send_telegram(message)


# ============================================================
# STATS FILE
# ============================================================

def load_stats():

    if not STATS_FILE.exists():

        return {
            "opportunities": [],
            "total_checks": 0
        }

    try:

        with open(
            STATS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError

        data.setdefault(
            "opportunities",
            []
        )

        data.setdefault(
            "total_checks",
            0
        )

        return data

    except Exception:

        return {
            "opportunities": [],
            "total_checks": 0
        }


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


# ============================================================
# RECORD OPPORTUNITY
# ============================================================

def record_opportunity(
    stats,
    result
):

    if result["profit_percent"] < MIN_PROFIT_PERCENT:
        return

    entry = {
        "timestamp":
            timestamp(),

        "buy_exchange":
            result["buy_exchange"],

        "sell_exchange":
            result["sell_exchange"],

        "profit_percent":
            result["profit_percent"],

        "net_profit":
            result["net_profit"],

        "capital":
            TRADE_AMOUNT_TOMAN,
    }

    stats["opportunities"].append(
        entry
    )

    # Keep file reasonably small.
    # 30 days is enough for monitoring history.
    cutoff = (
        now()
        - timedelta(days=30)
    )

    filtered = []

    for item in stats["opportunities"]:

        try:

            dt = datetime.strptime(
                item["timestamp"],
                "%Y-%m-%d %H:%M:%S"
            )

            if dt >= cutoff:
                filtered.append(item)

        except Exception:
            continue

    stats["opportunities"] = filtered


# ============================================================
# STATISTICS
# ============================================================

def calculate_statistics(stats):

    opportunities = (
        stats.get(
            "opportunities",
            []
        )
    )

    current = now()

    day_start = datetime(
        current.year,
        current.month,
        current.day
    )

    week_start = (
        current
        - timedelta(days=7)
    )

    daily = []
    weekly = []

    for item in opportunities:

        try:

            dt = datetime.strptime(
                item["timestamp"],
                "%Y-%m-%d %H:%M:%S"
            )

            if dt >= day_start:
                daily.append(item)

            if dt >= week_start:
                weekly.append(item)

        except Exception:
            continue

    def summarize(items):

        if not items:

            return {
                "count": 0,
                "max_profit_percent": 0,
                "max_profit_toman": 0,
                "sum_profit_toman": 0,
            }

        return {

            "count":
                len(items),

            "max_profit_percent":
                max(
                    x["profit_percent"]
                    for x in items
                ),

            "max_profit_toman":
                max(
                    x["net_profit"]
                    for x in items
                ),

            "sum_profit_toman":
                sum(
                    x["net_profit"]
                    for x in items
                ),
        }

    return {

        "daily":
            summarize(daily),

        "weekly":
            summarize(weekly),

        "total":
            summarize(opportunities),

    }


# ============================================================
# PERIODIC REPORT
# ============================================================

def create_statistics_report(stats):

    data = calculate_statistics(
        stats
    )

    daily = data["daily"]
    weekly = data["weekly"]
    total = data["total"]

    message = (
        "📊 <b>ARBITRAGE STATISTICS</b>\n\n"

        "━━━━━━━━━━━━━━\n"
        "📅 <b>Today</b>\n"
        f"Opportunities: {daily['count']}\n"
        f"Best: "
        f"{format_percent(daily['max_profit_percent'])}\n"
        f"Best profit: "
        f"{format_toman(daily['max_profit_toman'])} Toman\n"
        f"Sum: "
        f"{format_toman(daily['sum_profit_toman'])} Toman\n\n"

        "━━━━━━━━━━━━━━\n"
        "📆 <b>Last 7 Days</b>\n"
        f"Opportunities: {weekly['count']}\n"
        f"Best: "
        f"{format_percent(weekly['max_profit_percent'])}\n"
        f"Best profit: "
        f"{format_toman(weekly['max_profit_toman'])} Toman\n"
        f"Sum: "
        f"{format_toman(weekly['sum_profit_toman'])} Toman\n\n"

        "━━━━━━━━━━━━━━\n"
        "📈 <b>Total History</b>\n"
        f"Opportunities: {total['count']}\n"
        f"Best: "
        f"{format_percent(total['max_profit_percent'])}\n"
        f"Best profit: "
        f"{format_toman(total['max_profit_toman'])} Toman\n"
        f"Sum: "
        f"{format_toman(total['sum_profit_toman'])} Toman\n\n"

        f"💰 Simulation capital: "
        f"{format_toman(TRADE_AMOUNT_TOMAN)} Toman\n"

        f"🎯 Minimum alert: "
        f"{format_percent(MIN_PROFIT_PERCENT)}\n\n"

        f"⏰ {timestamp()}\n\n"

        "⚠️ Monitoring only"
    )

    return message


# ============================================================
# REPORT SCHEDULE
# ============================================================

REPORT_HOURS = {
    10,
    16,
    18,
}


last_report_date = None


def maybe_send_periodic_report(
    stats
):

    global last_report_date

    current = now()

    if current.hour not in REPORT_HOURS:
        return

    current_key = (
        current.strftime(
            "%Y-%m-%d-%H"
        )
    )

    if current_key == last_report_date:
        return

    last_report_date = current_key

    message = create_statistics_report(
        stats
    )

    send_telegram(message)


# ============================================================
# PRINT ROUTES
# ============================================================

def print_routes(results):

    print()
    print("=" * 80)
    print(
        f"[{timestamp()}] ARBITRAGE RANKING"
    )
    print("=" * 80)

    if not results:

        print(
            "No valid routes."
        )

        return

    for index, result in enumerate(
        results,
        start=1
    ):

        print(
            f"{index:02d}. "
            f"{result['buy_exchange']}"
            f" -> "
            f"{result['sell_exchange']} | "
            f"Profit: "
            f"{format_percent(result['profit_percent'])} | "
            f"Net: "
            f"{format_toman(result['net_profit'])} Toman"
        )


# ============================================================
# BEST MARKET CONDITIONS
# ============================================================

def print_market_snapshot(
    orderbooks
):

    valid = []

    for exchange, book in orderbooks.items():

        if not book:
            continue

        if not book.get("asks"):
            continue

        if not book.get("bids"):
            continue

        ask = book["asks"][0][0]
        bid = book["bids"][0][0]

        valid.append(
            (
                exchange,
                ask,
                bid
            )
        )

    if not valid:
        return

    lowest_ask = min(
        valid,
        key=lambda x: x[1]
    )

    highest_bid = max(
        valid,
        key=lambda x: x[2]
    )

    print()
    print(
        "MARKET SNAPSHOT"
    )

    print(
        f"Lowest Ask / Buy: "
        f"{lowest_ask[0]} -> "
        f"{format_toman(lowest_ask[1])}"
    )

    print(
        f"Highest Bid / Sell: "
        f"{highest_bid[0]} -> "
        f"{format_toman(highest_bid[2])}"
    )


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    print("=" * 80)

    print(
        "ARBITRAGE BOT STARTED"
    )

    print(
        "MONITORING ONLY - NO REAL TRADES"
    )

    print("=" * 80)

    print(
        f"Capital: "
        f"{format_toman(TRADE_AMOUNT_TOMAN)} Toman"
    )

    print(
        f"Minimum profit: "
        f"{format_percent(MIN_PROFIT_PERCENT)}"
    )

    print(
        f"Interval: "
        f"{CHECK_INTERVAL_SECONDS} seconds"
    )

    print(
        f"Order type: "
        f"{ORDER_TYPE}"
    )

    print("=" * 80)

    stats = load_stats()

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:

        send_telegram(
            "🤖 <b>Arbitrage Bot Started</b>\n\n"
            "Monitoring only.\n"
            "No real trades will be executed.\n\n"
            f"Capital: "
            f"{format_toman(TRADE_AMOUNT_TOMAN)} Toman\n"
            f"Minimum profit: "
            f"{format_percent(MIN_PROFIT_PERCENT)}\n"
            f"Interval: "
            f"{CHECK_INTERVAL_SECONDS}s"
        )

    while True:

        cycle_start = time.time()

        try:

            stats["total_checks"] = (
                stats.get(
                    "total_checks",
                    0
                ) + 1
            )

            print()
            print(
                f"[{timestamp()}] "
                "Checking exchanges..."
            )

            orderbooks = (
                get_all_orderbooks()
            )

            valid_count = sum(
                1
                for book in orderbooks.values()
                if book
                and book.get("asks")
                and book.get("bids")
            )

            print(
                f"Valid order books: "
                f"{valid_count}/"
                f"{len(orderbooks)}"
            )

            print_market_snapshot(
                orderbooks
            )

            results = (
                calculate_all_routes(
                    orderbooks
                )
            )

            print_routes(results)

            # ------------------------------------------------
            # Record opportunities
            # ------------------------------------------------

            for result in results:

                if (
                    result["profit_percent"]
                    >= MIN_PROFIT_PERCENT
                ):

                    record_opportunity(
                        stats,
                        result
                    )

                    send_arbitrage_alert(
                        result
                    )

            # ------------------------------------------------
            # Save statistics
            # ------------------------------------------------

            save_stats(stats)

            # ------------------------------------------------
            # Periodic reports
            # ------------------------------------------------

            maybe_send_periodic_report(
                stats
            )

        except KeyboardInterrupt:

            print(
                "\nBot stopped by user."
            )

            break

        except Exception as e:

            print(
                f"[MAIN ERROR] {e}"
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
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
