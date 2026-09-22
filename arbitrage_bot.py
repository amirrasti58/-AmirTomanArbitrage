"""
============================================================
ARBITRAGE MONITORING BOT
Wallex + BitPin + Ramzinex

USDT / TOMAN

MONITORING ONLY
NO REAL TRADES

FEATURES:
- Order Book
- Ask for buy / Bid for sell
- Order Book depth
- Maker / Taker fees
- Net profit calculation
- Telegram capital selection
- Custom capital input
- Detailed Telegram status
- Periodic report every 2 hours
- No periodic reports from 23:00 to 08:00
- Report cycle starts from 18:00
- Telegram /status command
- Arbitrage alerts
- Daily / weekly / total statistics
============================================================
"""

import os
import json
import time
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests


# ============================================================
# SETTINGS
# ============================================================

REQUEST_TIMEOUT = 15
ORDERBOOK_LEVELS = 20

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

if ORDER_TYPE not in ("maker", "taker"):
    ORDER_TYPE = "taker"


# ============================================================
# ANALYSIS SETTINGS
# ============================================================

MIN_EXECUTION_RATIO = 0.80

OPPORTUNITY_HISTORY_LIMIT = 60

MIN_ALLOCATION_OBSERVATIONS = 50

MIN_POSITIVE_OBSERVATIONS = 3

MAX_EXCHANGE_ALLOCATION_PERCENT = 0.70


# ============================================================
# FILES
# ============================================================

STATS_FILE = "arbitrage_stats.json"


# ============================================================
# TIMEZONE
# ============================================================

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
# FEES
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
}


# ============================================================
# ENABLED EXCHANGES
# ============================================================

ENABLED_EXCHANGES = [
    "Wallex",
    "BitPin",
    "Ramzinex",
]


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 ArbitrageBot/6.0",
    "Accept": "application/json",
})


# ============================================================
# GLOBAL STATE
# ============================================================

runtime_start = time.time()

last_alert_time = {}

exchange_error_state = {}

last_report_key = None

telegram_update_offset = None

waiting_for_custom_capital = False

selected_capital_toman = None

latest_orderbooks = {}

latest_routes = []

opportunity_history = []

state_lock = threading.Lock()


# ============================================================
# BASIC FUNCTIONS
# ============================================================

def now_tehran():

    return datetime.now(
        TEHRAN_TZ
    )


def format_toman(value):

    if value is None:
        return "-"

    return f"{value:,.0f}"


def format_percent(value):

    return f"{value:.3f}%"


def normalize_digits(text):

    return (
        str(text)
        .replace("۰", "0")
        .replace("۱", "1")
        .replace("۲", "2")
        .replace("۳", "3")
        .replace("۴", "4")
        .replace("۵", "5")
        .replace("۶", "6")
        .replace("۷", "7")
        .replace("۸", "8")
        .replace("۹", "9")
    )


# ============================================================
# ORDER BOOK NORMALIZATION
# ============================================================

def normalize_orderbook(data):

    result = []

    if not isinstance(data, list):

        return result

    for item in data:

        try:

            if isinstance(
                item,
                (list, tuple)
            ):

                if len(item) < 2:

                    continue

                price = float(
                    item[0]
                )

                volume = float(
                    item[1]
                )

            elif isinstance(
                item,
                dict
            ):

                price = float(
                    item.get(
                        "price",
                        0
                    )
                )

                volume = float(
                    item.get(
                        "quantity",
                        item.get(
                            "volume",
                            item.get(
                                "amount",
                                0
                            )
                        )
                    )
                )

            else:

                continue

            if (
                price > 0
                and
                volume > 0
            ):

                result.append(
                    (
                        price,
                        volume
                    )
                )

        except Exception:

            continue

    return result[
        :ORDERBOOK_LEVELS
    ]


# ============================================================
# EXCHANGE ERROR
# ============================================================

def report_exchange_error(
    exchange,
    message
):

    current = time.time()

    previous = exchange_error_state.get(
        exchange
    )

    if previous:

        if (
            previous["message"] == message
            and
            current - previous["time"] < 60
        ):

            return

    exchange_error_state[
        exchange
    ] = {

        "message":
            message,

        "time":
            current,
    }

    print(
        f"⚠️ خطای {exchange}: {message}"
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

        raw = data.get(
            "result",
            data
        )

        asks = normalize_orderbook(
            raw.get(
                "ask",
                raw.get(
                    "asks",
                    []
                )
            )
        )

        bids = normalize_orderbook(
            raw.get(
                "bid",
                raw.get(
                    "bids",
                    []
                )
            )
        )

        if (
            not asks
            or
            not bids
        ):

            raise ValueError(
                "Order Book خالی است"
            )

        return {

            "exchange":
                "Wallex",

            "asks":
                asks,

            "bids":
                bids,
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
            data.get(
                "asks",
                []
            )
        )

        bids = normalize_orderbook(
            data.get(
                "bids",
                []
            )
        )

        if (
            not asks
            or
            not bids
        ):

            raise ValueError(
                "Order Book خالی است"
            )

        return {

            "exchange":
                "BitPin",

            "asks":
                asks,

            "bids":
                bids,
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

            raw = data.get(
                "data",
                data
            )

            buys = []

            sells = []

            if isinstance(
                raw,
                dict
            ):

                buys = raw.get(
                    "buys",
                    raw.get(
                        "bids",
                        raw.get(
                            "buy",
                            []
                        )
                    )
                )

                sells = raw.get(
                    "sells",
                    raw.get(
                        "asks",
                        raw.get(
                            "sell",
                            []
                        )
                    )
                )

            bids = normalize_orderbook(
                buys
            )

            asks = normalize_orderbook(
                sells
            )

            # Ramzinex Pair 11 is IRR.
            # Convert Rial to Toman.

            bids = [
                (
                    price / 10,
                    volume
                )
                for price, volume in bids
            ]

            asks = [
                (
                    price / 10,
                    volume
                )
                for price, volume in asks
            ]

            if (
                bids
                and
                asks
            ):

                return {

                    "exchange":
                        "Ramzinex",

                    "asks":
                        asks,

                    "bids":
                        bids,
                }

        except Exception as e:

            report_exchange_error(
                "Ramzinex",
                str(e)
            )

    return None


# ============================================================
# GET ALL ORDER BOOKS
# ============================================================

def get_all_orderbooks():

    functions = {

        "Wallex":
            get_wallex_orderbook,

        "BitPin":
            get_bitpin_orderbook,

        "Ramzinex":
            get_ramzinex_orderbook,
    }

    orderbooks = {}

    for exchange in ENABLED_EXCHANGES:

        function = functions.get(
            exchange
        )

        if function is None:

            continue

        result = function()

        if result:

            orderbooks[
                exchange
            ] = result

    return orderbooks


# ============================================================
# FEES
# ============================================================

def get_fee(exchange):

    exchange_fees = FEES.get(
        exchange,
        {}
    )

    return exchange_fees.get(
        ORDER_TYPE,
        0
    )


# ============================================================
# BUY FROM ASKS
# ============================================================

def calculate_buy(
    asks,
    amount_toman,
    fee
):

    remaining_toman = (
        amount_toman
    )

    received_usdt = 0.0

    spent_toman = 0.0

    for price, volume in asks:

        if remaining_toman <= 0:

            break

        max_cost = (
            price * volume
        )

        cost = min(
            remaining_toman,
            max_cost
        )

        usdt = (
            cost / price
        )

        spent_toman += cost

        received_usdt += usdt

        remaining_toman -= cost

    if spent_toman <= 0:

        return None

    usdt_after_fee = (
        received_usdt
        * (1 - fee)
    )

    average_price = (
        spent_toman
        / received_usdt
    )

    execution_ratio = (
        spent_toman
        / amount_toman
        if amount_toman > 0
        else 0
    )

    return {

        "spent_toman":
            spent_toman,

        "usdt":
            usdt_after_fee,

        "average_price":
            average_price,

        "unfilled_toman":
            remaining_toman,

        "execution_ratio":
            execution_ratio,
    }


# ============================================================
# SELL TO BIDS
# ============================================================

def calculate_sell(
    bids,
    usdt_amount,
    fee
):

    remaining_usdt = (
        usdt_amount
    )

    received_toman = 0.0

    sold_usdt = 0.0

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

    received_after_fee = (
        received_toman
        * (1 - fee)
    )

    average_price = (
        received_toman
        / sold_usdt
    )

    execution_ratio = (
        sold_usdt
        / usdt_amount
        if usdt_amount > 0
        else 0
    )

    return {

        "sold_usdt":
            sold_usdt,

        "received_toman":
            received_after_fee,

        "average_price":
            average_price,

        "unfilled_usdt":
            remaining_usdt,

        "execution_ratio":
            execution_ratio,
    }


# ============================================================
# CALCULATE ROUTE
# ============================================================

def calculate_route(
    buy_exchange,
    sell_exchange,
    orderbooks,
    amount_toman
):

    buy_book = orderbooks.get(
        buy_exchange
    )

    sell_book = orderbooks.get(
        sell_exchange
    )

    if (
        not buy_book
        or
        not sell_book
    ):

        return None

    buy_fee = get_fee(
        buy_exchange
    )

    sell_fee = get_fee(
        sell_exchange
    )

    buy_result = calculate_buy(
        buy_book["asks"],
        amount_toman,
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

    if actual_spent <= 0:

        return None

    net_profit = (
        final_toman
        - actual_spent
    )

    profit_percent = (
        net_profit
        / actual_spent
        * 100
    )

    execution_ratio = min(
        buy_result["execution_ratio"],
        sell_result["execution_ratio"]
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

        "execution_ratio":
            execution_ratio,

        "fully_executable":
            (
                execution_ratio
                >= MIN_EXECUTION_RATIO
            ),
    }


# ============================================================
# ALL ROUTES
# ============================================================

def calculate_all_routes(
    orderbooks,
    amount_toman
):

    routes = []

    exchanges = list(
        orderbooks.keys()
    )

    for buy_exchange in exchanges:

        for sell_exchange in exchanges:

            if (
                buy_exchange
                == sell_exchange
            ):

                continue

            route = calculate_route(
                buy_exchange,
                sell_exchange,
                orderbooks,
                amount_toman
            )

            if route:

                routes.append(
                    route
                )

    routes.sort(
        key=lambda x:
            x["net_profit"],
        reverse=True
    )

    return routes


# ============================================================
# MARKET SNAPSHOT
# ============================================================

def print_market_snapshot(
    orderbooks
):

    print()

    print(
        "========== وضعیت بازار =========="
    )

    for exchange in ENABLED_EXCHANGES:

        book = orderbooks.get(
            exchange
        )

        if not book:

            print(
                f"{exchange}: ❌ نامعتبر"
            )

            continue

        ask = (
            book["asks"][0][0]
            if book["asks"]
            else None
        )

        bid = (
            book["bids"][0][0]
            if book["bids"]
            else None
        )

        print(
            f"{exchange}: "
            f"Ask={format_toman(ask)} | "
            f"Bid={format_toman(bid)}"
        )

    best_ask = None
    best_bid = None

    for exchange, book in orderbooks.items():

        if book["asks"]:

            price = book["asks"][0][0]

            if (
                best_ask is None
                or
                price < best_ask[0]
            ):

                best_ask = (
                    price,
                    exchange
                )

        if book["bids"]:

            price = book["bids"][0][0]

            if (
                best_bid is None
                or
                price > best_bid[0]
            ):

                best_bid = (
                    price,
                    exchange
                )

    if best_ask:

        print(
            "🟢 کمترین Ask: "
            f"{best_ask[1]} → "
            f"{format_toman(best_ask[0])} تومان"
        )

    if best_bid:

        print(
            "🔴 بیشترین Bid: "
            f"{best_bid[1]} → "
            f"{format_toman(best_bid[0])} تومان"
        )

    print(
        "================================"
    )


# ============================================================
# PRINT ROUTES
# ============================================================

def print_routes(routes):

    print()

    print(
        "========== رتبه‌بندی مسیرها =========="
    )

    if not routes:

        print(
            "هیچ مسیر قابل محاسبه‌ای وجود ندارد."
        )

        print(
            "====================================="
        )

        return

    for index, route in enumerate(
        routes,
        start=1
    ):

        status = (
            "کامل"
            if route["fully_executable"]
            else "ناقص"
        )

        print(
            f"{index}. "
            f"{route['buy_exchange']} → "
            f"{route['sell_exchange']} | "
            f"سود: "
            f"{format_percent(route['profit_percent'])} | "
            f"خالص: "
            f"{format_toman(route['net_profit'])} تومان | "
            f"اجرا: "
            f"{route['execution_ratio'] * 100:.1f}% | "
            f"{status}"
        )

    print(
        "====================================="
    )


# ============================================================
# HISTORY
# ============================================================

def route_key(
    buy_exchange,
    sell_exchange
):

    return (
        f"{buy_exchange}_"
        f"{sell_exchange}"
    )


def update_opportunity_history(
    routes
):

    global opportunity_history

    snapshot = {}

    current_time = now_tehran().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    for route in routes:

        key = route_key(
            route["buy_exchange"],
            route["sell_exchange"]
        )

        snapshot[key] = {

            "time":
                current_time,

            "profit_percent":
                route["profit_percent"],

            "net_profit":
                route["net_profit"],

            "execution_ratio":
                route["execution_ratio"],

            "qualified":
                (
                    route["net_profit"] > 0
                    and
                    route["profit_percent"]
                    >= MIN_PROFIT_PERCENT
                    and
                    route["execution_ratio"]
                    >= MIN_EXECUTION_RATIO
                ),
        }

    opportunity_history.append(
        snapshot
    )

    if (
        len(opportunity_history)
        > OPPORTUNITY_HISTORY_LIMIT
    ):

        opportunity_history = (
            opportunity_history[
                -OPPORTUNITY_HISTORY_LIMIT:
            ]
        )


def analyze_route_history(
    key
):

    observations = []

    for snapshot in opportunity_history:

        data = snapshot.get(
            key
        )

        if data:

            observations.append(
                data
            )

    if not observations:

        return {

            "observations":
                0,

            "positive_observations":
                0,

            "qualified_observations":
                0,

            "positive_ratio":
                0,

            "qualified_ratio":
                0,

            "average_profit_percent":
                0,

            "average_net_profit":
                0,

            "average_execution_ratio":
                0,
        }

    positive = [
        x for x in observations
        if x["net_profit"] > 0
    ]

    qualified = [
        x for x in observations
        if x["qualified"]
    ]

    return {

        "observations":
            len(observations),

        "positive_observations":
            len(positive),

        "qualified_observations":
            len(qualified),

        "positive_ratio":
            len(positive)
            / len(observations),

        "qualified_ratio":
            len(qualified)
            / len(observations),

        "average_profit_percent":
            sum(
                x["profit_percent"]
                for x in observations
            )
            / len(observations),

        "average_net_profit":
            sum(
                x["net_profit"]
                for x in observations
            )
            / len(observations),

        "average_execution_ratio":
            sum(
                x["execution_ratio"]
                for x in observations
            )
            / len(observations),
    }


# ============================================================
# STATS
# ============================================================

def default_stats():

    return {

        "total_route_checks":
            0,

        "total_positive_opportunities":
            0,

        "total_qualified_opportunities":
            0,

        "total_simulated_profit_toman":
            0,

        "total_alerts":
            0,

        "daily":
            {},

        "weekly":
            {},
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
        ) as file:

            data = json.load(
                file
            )

        if not isinstance(
            data,
            dict
        ):

            return default_stats()

        defaults = default_stats()

        for key, value in defaults.items():

            if key not in data:

                data[key] = value

        return data

    except Exception:

        return default_stats()


def save_stats(
    stats
):

    try:

        with open(
            STATS_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                stats,
                file,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            f"⚠️ خطای ذخیره آمار: {e}"
        )


def update_stats(
    stats,
    routes
):

    now = now_tehran()

    today = now.strftime(
        "%Y-%m-%d"
    )

    week = now.strftime(
        "%Y-W%W"
    )

    if today not in stats["daily"]:

        stats["daily"][today] = {

            "route_checks":
                0,

            "positive":
                0,

            "qualified":
                0,

            "simulated_profit_toman":
                0,

            "alerts":
                0,
        }

    if week not in stats["weekly"]:

        stats["weekly"][week] = {

            "route_checks":
                0,

            "positive":
                0,

            "qualified":
                0,

            "simulated_profit_toman":
                0,

            "alerts":
                0,
        }

    count = len(
        routes
    )

    stats[
        "total_route_checks"
    ] += count

    stats[
        "daily"
    ][today][
        "route_checks"
    ] += count

    stats[
        "weekly"
    ][week][
        "route_checks"
    ] += count

    for route in routes:

        if route["net_profit"] > 0:

            stats[
                "total_positive_opportunities"
            ] += 1

            stats[
                "daily"
            ][today][
                "positive"
            ] += 1

            stats[
                "weekly"
            ][week][
                "positive"
            ] += 1

        if (
            route["net_profit"] > 0
            and
            route["profit_percent"]
            >= MIN_PROFIT_PERCENT
            and
            route["execution_ratio"]
            >= MIN_EXECUTION_RATIO
        ):

            profit = route[
                "net_profit"
            ]

            stats[
                "total_qualified_opportunities"
            ] += 1

            stats[
                "total_simulated_profit_toman"
            ] += profit

            stats[
                "daily"
            ][today][
                "qualified"
            ] += 1

            stats[
                "daily"
            ][today][
                "simulated_profit_toman"
            ] += profit

            stats[
                "weekly"
            ][week][
                "qualified"
            ] += 1

            stats[
                "weekly"
            ][week][
                "simulated_profit_toman"
            ] += profit

    save_stats(
        stats
    )


# ============================================================
# TELEGRAM KEYBOARD
# ============================================================

def capital_keyboard():

    return {

        "inline_keyboard": [

            [
                {
                    "text":
                        "💰 50 میلیون",

                    "callback_data":
                        "CAPITAL:50000000"
                },

                {
                    "text":
                        "💰 100 میلیون",

                    "callback_data":
                        "CAPITAL:100000000"
                },
            ],

            [
                {
                    "text":
                        "💰 200 میلیون",

                    "callback_data":
                        "CAPITAL:200000000"
                },

                {
                    "text":
                        "💰 500 میلیون",

                    "callback_data":
                        "CAPITAL:500000000"
                },
            ],

            [
                {
                    "text":
                        "💰 1 میلیارد",

                    "callback_data":
                        "CAPITAL:1000000000"
                },
            ],

            [
                {
                    "text":
                        "✏️ ورود مبلغ دلخواه",

                    "callback_data":
                        "CAPITAL:CUSTOM"
                },
            ],

            [
                {
                    "text":
                        "📊 وضعیت فعلی",

                    "callback_data":
                        "STATUS"
                },
            ],
        ]
    }


# ============================================================
# TELEGRAM SEND
# ============================================================

def send_telegram(
    message,
    reply_markup=None
):

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

    if reply_markup is not None:

        payload[
            "reply_markup"
        ] = reply_markup

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
            f"⚠️ خطای Telegram: {e}"
        )

        return False


# ============================================================
# TELEGRAM CALLBACK ANSWER
# ============================================================

def answer_callback(
    callback_id,
    text
):

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/answerCallbackQuery"
    )

    try:

        SESSION.post(
            url,
            json={
                "callback_query_id":
                    callback_id,

                "text":
                    text,
            },
            timeout=REQUEST_TIMEOUT
        )

    except Exception:

        pass


# ============================================================
# CUSTOM CAPITAL
# ============================================================

def set_capital(
    amount
):

    global selected_capital_toman

    if amount <= 0:

        return False

    selected_capital_toman = int(
        amount
    )

    send_telegram(
        "✅ موجودی انتخاب شد.\n\n"
        f"💰 موجودی فعلی:\n"
        f"{format_toman(selected_capital_toman)} تومان\n\n"
        "از این مبلغ برای محاسبه فرصت‌های "
        "آربیتراژ استفاده می‌شود.\n\n"
        "❌ هیچ معامله‌ای انجام نمی‌شود.",
        capital_keyboard()
    )

    print(
        "💰 موجودی جدید: "
        f"{format_toman(selected_capital_toman)} تومان"
    )

    return True


# ============================================================
# TELEGRAM UPDATE HANDLER
# ============================================================

def handle_telegram_update(
    update
):

    global waiting_for_custom_capital

    # --------------------------------------------------------
    # CALLBACK
    # --------------------------------------------------------

    callback = update.get(
        "callback_query"
    )

    if callback:

        callback_id = callback.get(
            "id"
        )

        data = callback.get(
            "data",
            ""
        )

        answer_callback(
            callback_id,
            "در حال پردازش..."
        )

        if data == "STATUS":

            send_current_status_message()

            return

        if data == "CAPITAL:CUSTOM":

            waiting_for_custom_capital = True

            send_telegram(
                "✏️ لطفاً مبلغ موجودی خود را "
                "به تومان ارسال کنید.\n\n"
                "مثال:\n"
                "370000000\n\n"
                "یا:\n"
                "370 میلیون"
            )

            return

        if data.startswith(
            "CAPITAL:"
        ):

            value = data.split(
                ":",
                1
            )[1]

            try:

                amount = int(
                    value
                )

                waiting_for_custom_capital = False

                set_capital(
                    amount
                )

            except Exception:

                send_telegram(
                    "❌ مبلغ نامعتبر است."
                )

            return

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    message = update.get(
        "message"
    )

    if not message:

        return

    text = message.get(
        "text",
        ""
    ).strip()

    if not text:

        return

    # --------------------------------------------------------
    # COMMAND
    # --------------------------------------------------------

    if text == "/status":

        send_current_status_message()

        return

    if text == "/capital":

        send_telegram(
            "💰 انتخاب موجودی:",
            capital_keyboard()
        )

        return

    # --------------------------------------------------------
    # CUSTOM CAPITAL
    # --------------------------------------------------------

    if waiting_for_custom_capital:

        try:

            normalized = normalize_digits(
                text
            )

            normalized = (
                normalized
                .replace(
                    ",",
                    ""
                )
                .replace(
                    "٬",
                    ""
                )
                .replace(
                    " ",
                    ""
                )
            )

            multiplier = 1

            if (
                "میلیارد"
                in normalized
            ):

                multiplier = 1_000_000_000

                normalized = (
                    normalized
                    .replace(
                        "میلیارد",
                        ""
                    )
                )

            elif (
                "میلیون"
                in normalized
            ):

                multiplier = 1_000_000

                normalized = (
                    normalized
                    .replace(
                        "میلیون",
                        ""
                    )
                )

            amount = float(
                normalized
            ) * multiplier

            amount = int(
                amount
            )

            if amount <= 0:

                raise ValueError

            waiting_for_custom_capital = False

            set_capital(
                amount
            )

        except Exception:

            send_telegram(
                "❌ مبلغ قابل تشخیص نیست.\n\n"
                "مثال صحیح:\n"
                "370000000\n"
                "یا\n"
                "370 میلیون"
            )


# ============================================================
# TELEGRAM LISTENER
# ============================================================

def telegram_listener():

    global telegram_update_offset

    if not TELEGRAM_BOT_TOKEN:

        print(
            "⚠️ TELEGRAM_BOT_TOKEN تنظیم نشده."
        )

        return

    print(
        "📱 Telegram listener فعال شد."
    )

    while True:

        try:

            url = (
                "https://api.telegram.org/bot"
                f"{TELEGRAM_BOT_TOKEN}"
                "/getUpdates"
            )

            params = {

                "timeout":
                    25,
            }

            if telegram_update_offset is not None:

                params[
                    "offset"
                ] = telegram_update_offset

            response = SESSION.get(
                url,
                params=params,
                timeout=35
            )

            response.raise_for_status()

            data = response.json()

            updates = data.get(
                "result",
                []
            )

            for update in updates:

                telegram_update_offset = (
                    update["update_id"] + 1
                )

                try:

                    handle_telegram_update(
                        update
                    )

                except Exception as e:

                    print(
                        "⚠️ خطای پردازش Telegram: "
                        f"{e}"
                    )

        except Exception as e:

            print(
                f"⚠️ خطای Telegram listener: {e}"
            )

            time.sleep(5)


def start_telegram_listener():

    thread = threading.Thread(
        target=telegram_listener,
        daemon=True
    )

    thread.start()


# ============================================================
# CURRENT STATUS MESSAGE
# ============================================================

def build_current_status_message(
    stats
):

    now = now_tehran()

    lines = []

    lines.append(
        "📊 وضعیت فعلی آربیتراژ"
    )

    lines.append(
        ""
    )

    lines.append(
        f"🕐 زمان: "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} تهران"
    )

    lines.append(
        ""
    )

    # --------------------------------------------------------
    # CAPITAL
    # --------------------------------------------------------

    lines.append(
        "💰 موجودی:"
    )

    if selected_capital_toman is None:

        lines.append(
            "❌ هنوز انتخاب نشده"
        )

    else:

        lines.append(
            format_toman(
                selected_capital_toman
            )
            + " تومان"
        )

    # --------------------------------------------------------
    # EXCHANGES
    # --------------------------------------------------------

    lines.append(
        ""
    )

    lines.append(
        "🏦 وضعیت صرافی‌ها:"
    )

    for exchange in ENABLED_EXCHANGES:

        book = latest_orderbooks.get(
            exchange
        )

        if not book:

            lines.append(
                f"• {exchange}: ❌"
            )

            continue

        ask = (
            book["asks"][0][0]
            if book["asks"]
            else None
        )

        bid = (
            book["bids"][0][0]
            if book["bids"]
            else None
        )

        lines.append(
            f"• {exchange}: ✅"
        )

        lines.append(
            f"  Ask: {format_toman(ask)}"
        )

        lines.append(
            f"  Bid: {format_toman(bid)}"
        )

    # --------------------------------------------------------
    # BEST ROUTE
    # --------------------------------------------------------

    if latest_routes:

        best = latest_routes[0]

        lines.append(
            ""
        )

        lines.append(
            "🏆 بهترین مسیر:"
        )

        lines.append(
            f"{best['buy_exchange']} → "
            f"{best['sell_exchange']}"
        )

        lines.append(
            ""
        )

        lines.append(
            f"💵 سود خالص: "
            f"{format_toman(best['net_profit'])} تومان"
        )

        lines.append(
            f"📈 سود: "
            f"{format_percent(best['profit_percent'])}"
        )

        lines.append(
            f"🎯 حد هشدار: "
            f"{format_percent(MIN_PROFIT_PERCENT)}"
        )

        distance = (
            MIN_PROFIT_PERCENT
            - best["profit_percent"]
        )

        if distance < 0:

            distance = 0

        lines.append(
            f"📉 فاصله تا حد هشدار: "
            f"{format_percent(distance)}"
        )

        lines.append(
            f"📦 قابلیت اجرای Order Book: "
            f"{best['execution_ratio'] * 100:.1f}%"
        )

        lines.append(
            f"💱 مقدار USDT: "
            f"{best['usdt']:.4f}"
        )

        lines.append(
            ""
        )

        lines.append(
            "💲 قیمت‌ها:"
        )

        lines.append(
            f"• خرید: "
            f"{format_toman(best['buy_price'])}"
        )

        lines.append(
            f"• فروش: "
            f"{format_toman(best['sell_price'])}"
        )

        lines.append(
            ""
        )

        lines.append(
            "💳 کارمزد:"
        )

        lines.append(
            f"• خرید: "
            f"{best['buy_fee'] * 100:.3f}%"
        )

        lines.append(
            f"• فروش: "
            f"{best['sell_fee'] * 100:.3f}%"
        )

        if (
            best["net_profit"] > 0
            and
            best["profit_percent"]
            >= MIN_PROFIT_PERCENT
            and
            best["execution_ratio"]
            >= MIN_EXECUTION_RATIO
        ):

            lines.append(
                ""
            )

            lines.append(
                "🚨 وضعیت: "
                "فرصت واجد شرایط هشدار است."
            )

        elif best["net_profit"] > 0:

            lines.append(
                ""
            )

            lines.append(
                "🟡 وضعیت: "
                "سود مثبت است، "
                "اما به حد هشدار نرسیده."
            )

        else:

            lines.append(
                ""
            )

            lines.append(
                "🔴 وضعیت: "
                "بهترین مسیر بعد از کارمزد سودده نیست."
            )

        # ----------------------------------------------------
        # TOP 3
        # ----------------------------------------------------

        lines.append(
            ""
        )

        lines.append(
            "🏆 سه مسیر برتر:"
        )

        for index, route in enumerate(
            latest_routes[:3],
            start=1
        ):

            lines.append(
                f"{index}. "
                f"{route['buy_exchange']} → "
                f"{route['sell_exchange']} | "
                f"{format_percent(route['profit_percent'])} | "
                f"{format_toman(route['net_profit'])} تومان"
            )

    else:

        lines.append(
            ""
        )

        lines.append(
            "ℹ️ هنوز مسیر قابل محاسبه‌ای وجود ندارد."
        )

        if selected_capital_toman is None:

            lines.append(
                "ابتدا موجودی را از دکمه Telegram انتخاب کنید."
            )

    # --------------------------------------------------------
    # DAILY STATS
    # --------------------------------------------------------

    today = now.strftime(
        "%Y-%m-%d"
    )

    daily = stats[
        "daily"
    ].get(
        today,
        {
            "route_checks":
                0,

            "positive":
                0,

            "qualified":
                0,

            "simulated_profit_toman":
                0,

            "alerts":
                0,
        }
    )

    lines.append(
        ""
    )

    lines.append(
        "📅 آمار امروز:"
    )

    lines.append(
        f"• بررسی مسیر: "
        f"{daily['route_checks']}"
    )

    lines.append(
        f"• فرصت سودده: "
        f"{daily['positive']}"
    )

    lines.append(
        f"• فرصت واجد شرایط: "
        f"{daily['qualified']}"
    )

    lines.append(
        f"• هشدار ارسال‌شده: "
        f"{daily['alerts']}"
    )

    lines.append(
        f"• سود شبیه‌سازی‌شده: "
        f"{format_toman(daily['simulated_profit_toman'])} تومان"
    )

    lines.append(
        ""
    )

    lines.append(
        "⚠️ فقط مانیتورینگ و شبیه‌سازی."
    )

    lines.append(
        "❌ معامله واقعی انجام نمی‌شود."
    )

    return "\n".join(
        lines
    )


def send_current_status_message(
    stats=None
):

    if stats is None:

        stats = load_stats()

    return send_telegram(
        build_current_status_message(
            stats
        )
    )


# ============================================================
# REPORT SCHEDULE
# ============================================================

REPORT_HOURS = {
    8,
    10,
    12,
    14,
    16,
    18,
    20,
    22,
}


def send_periodic_report(
    stats
):

    global last_report_key

    now = now_tehran()

    hour = now.hour

    minute = now.minute

    # --------------------------------------------------------
    # 23:00 تا 07:59 هیچ گزارش دوره‌ای
    # --------------------------------------------------------

    if (
        hour >= 23
        or
        hour < 8
    ):

        return

    # --------------------------------------------------------
    # فقط در ساعت‌های تعیین‌شده
    # --------------------------------------------------------

    if hour not in REPORT_HOURS:

        return

    # گزارش فقط در اولین چرخه همان ساعت
    if minute != 0:

        return

    report_key = (
        now.strftime(
            "%Y-%m-%d-%H"
        )
    )

    if (
        last_report_key
        == report_key
    ):

        return

    last_report_key = report_key

    send_current_status_message(
        stats
    )


# ============================================================
# ARBITRAGE ALERT
# ============================================================

def send_arbitrage_alert(
    route,
    stats
):

    key = route_key(
        route["buy_exchange"],
        route["sell_exchange"]
    )

    current = time.time()

    previous = last_alert_time.get(
        key,
        0
    )

    if (
        current - previous
        < ALERT_COOLDOWN_SECONDS
    ):

        return False

    if route["net_profit"] <= 0:

        return False

    if (
        route["profit_percent"]
        < MIN_PROFIT_PERCENT
    ):

        return False

    if (
        route["execution_ratio"]
        < MIN_EXECUTION_RATIO
    ):

        return False

    message = (
        "🚨 فرصت آربیتراژ\n\n"

        f"خرید از: "
        f"{route['buy_exchange']}\n"

        f"فروش در: "
        f"{route['sell_exchange']}\n\n"

        f"💰 موجودی محاسباتی: "
        f"{format_toman(route['spent'])} تومان\n"

        f"💱 مقدار USDT: "
        f"{route['usdt']:.4f}\n\n"

        f"💵 سود خالص: "
        f"{format_toman(route['net_profit'])} تومان\n"

        f"📈 سود: "
        f"{format_percent(route['profit_percent'])}\n"

        f"📦 اجرای Order Book: "
        f"{route['execution_ratio'] * 100:.1f}%\n\n"

        f"💲 میانگین خرید: "
        f"{format_toman(route['buy_price'])}\n"

        f"💲 میانگین فروش: "
        f"{format_toman(route['sell_price'])}\n\n"

        f"💳 کارمزد خرید: "
        f"{route['buy_fee'] * 100:.3f}%\n"

        f"💳 کارمزد فروش: "
        f"{route['sell_fee'] * 100:.3f}%\n\n"

        "⚠️ فقط هشدار و مانیتورینگ\n"
        "❌ معامله واقعی انجام نمی‌شود."
    )

    if send_telegram(
        message
    ):

        last_alert_time[
            key
        ] = current

        today = now_tehran().strftime(
            "%Y-%m-%d"
        )

        week = now_tehran().strftime(
            "%Y-W%W"
        )

        stats[
            "total_alerts"
        ] += 1

        if today in stats["daily"]:

            stats[
                "daily"
            ][today][
                "alerts"
            ] += 1

        if week in stats["weekly"]:

            stats[
                "weekly"
            ][week][
                "alerts"
            ] += 1

        save_stats(
            stats
        )

        return True

    return False


# ============================================================
# ALLOCATION ANALYSIS
# ============================================================

def calculate_capital_allocation(
    routes,
    total_capital
):

    if (
        len(opportunity_history)
        < MIN_ALLOCATION_OBSERVATIONS
    ):

        return None

    scores = {
        exchange: 0.0
        for exchange in ENABLED_EXCHANGES
    }

    for route in routes:

        if route["net_profit"] <= 0:

            continue

        key = route_key(
            route["buy_exchange"],
            route["sell_exchange"]
        )

        history = analyze_route_history(
            key
        )

        if (
            history["observations"]
            < MIN_POSITIVE_OBSERVATIONS
        ):

            continue

        observation_factor = min(
            history["observations"]
            / MIN_ALLOCATION_OBSERVATIONS,
            1
        )

        positive_factor = (
            history["positive_ratio"]
        )

        qualified_factor = (
            history["qualified_ratio"]
        )

        execution_factor = (
            history["average_execution_ratio"]
        )

        profit_factor = min(
            max(
                route["profit_percent"],
                0
            )
            / max(
                MIN_PROFIT_PERCENT,
                0.1
            ),
            1
        )

        score = (
            observation_factor * 0.15
            +
            positive_factor * 0.20
            +
            qualified_factor * 0.25
            +
            execution_factor * 0.20
            +
            profit_factor * 0.20
        )

        scores[
            route["buy_exchange"]
        ] += (
            score * 0.60
        )

        scores[
            route["sell_exchange"]
        ] += (
            score * 0.40
        )

    total_score = sum(
        scores.values()
    )

    if total_score <= 0:

        return None

    weights = {
        exchange:
            scores[exchange]
            / total_score

        for exchange
        in ENABLED_EXCHANGES
    }

    # سقف 70 درصد
    for exchange in weights:

        weights[
            exchange
        ] = min(
            weights[exchange],
            MAX_EXCHANGE_ALLOCATION_PERCENT
        )

    return {
        exchange:
            int(
                total_capital
                * weights[exchange]
            )

        for exchange
        in ENABLED_EXCHANGES
    }


def print_capital_allocation(
    routes
):

    if selected_capital_toman is None:

        return

    allocation = calculate_capital_allocation(
        routes,
        selected_capital_toman
    )

    print()

    print(
        "========== تحلیل سرمایه =========="
    )

    if allocation is None:

        print(
            "⏳ هنوز داده کافی برای "
            "پیشنهاد تخصیص سرمایه نداریم."
        )

        print(
            f"حداقل داده لازم: "
            f"{MIN_ALLOCATION_OBSERVATIONS} چرخه"
        )

        print(
            "================================="
        )

        return

    for exchange in ENABLED_EXCHANGES:

        amount = allocation.get(
            exchange,
            0
        )

        percentage = (
            amount
            / selected_capital_toman
            * 100
        )

        print(
            f"{exchange}: "
            f"{format_toman(amount)} تومان "
            f"({percentage:.1f}%)"
        )

    print(
        "⚠️ این فقط پیشنهاد تحلیلی است."
    )

    print(
        "❌ معامله واقعی انجام نمی‌شود."
    )

    print(
        "================================="
    )


# ============================================================
# STARTUP MESSAGE
# ============================================================

def send_startup_message():

    message = (
        "🤖 ربات آربیتراژ شروع شد\n\n"

        "📡 حالت: فقط مانیتورینگ\n"

        "❌ معامله واقعی: خیر\n\n"

        "🏦 صرافی‌ها:\n"
        "• Wallex\n"
        "• BitPin\n"
        "• Ramzinex\n\n"

        f"📈 حداقل سود هشدار: "
        f"{format_percent(MIN_PROFIT_PERCENT)}\n"

        f"⏱️ فاصله بررسی: "
        f"{CHECK_INTERVAL_SECONDS} ثانیه\n"

        f"💳 نوع کارمزد: "
        f"{ORDER_TYPE}\n\n"

        "💰 موجودی هنوز انتخاب نشده.\n"
        "از دکمه زیر انتخاب کنید.\n\n"

        "📊 گزارش وضعیت: هر دو ساعت\n"

        "🌙 گزارش دوره‌ای: "
        "23:00 تا 08:00 متوقف\n"

        "⏰ چرخه گزارش از 18:00 محاسبه می‌شود."
    )

    send_telegram(
        message,
        capital_keyboard()
    )


# ============================================================
# MAIN
# ============================================================

def main():

    global latest_orderbooks
    global latest_routes

    print()

    print(
        "================================================"
    )

    print(
        "🤖 ربات آربیتراژ شروع شد"
    )

    print(
        "📡 فقط مانیتورینگ - بدون معامله واقعی"
    )

    print(
        "================================================"
    )

    print(
        "💰 موجودی: "
        "از داخل Telegram انتخاب می‌شود"
    )

    print(
        f"📈 حداقل سود هشدار: "
        f"{format_percent(MIN_PROFIT_PERCENT)}"
    )

    print(
        f"⏱️ فاصله بررسی: "
        f"{CHECK_INTERVAL_SECONDS} ثانیه"
    )

    print(
        f"💳 نوع کارمزد: "
        f"{ORDER_TYPE}"
    )

    print(
        "🏦 صرافی‌ها: "
        + ", ".join(
            ENABLED_EXCHANGES
        )
    )

    print(
        "================================================"
    )

    stats = load_stats()

    send_startup_message()

    start_telegram_listener()

    while True:

        if (
            time.time()
            - runtime_start
            >= MAX_RUNTIME_SECONDS
        ):

            print()

            print(
                "⏹️ حداکثر زمان اجرا به پایان رسید."
            )

            print(
                "ربات به شکل امن متوقف شد."
            )

            save_stats(
                stats
            )

            break

        cycle_start = time.time()

        print()

        print(
            "------------------------------------------------"
        )

        print(
            "🕐 زمان: "
            f"{now_tehran().strftime('%Y-%m-%d %H:%M:%S')} "
            "تهران"
        )

        print(
            "🔎 دریافت Order Book..."
        )

        orderbooks = (
            get_all_orderbooks()
        )

        latest_orderbooks = (
            orderbooks
        )

        print(
            f"📚 Order Book معتبر: "
            f"{len(orderbooks)}/"
            f"{len(ENABLED_EXCHANGES)}"
        )

        if orderbooks:

            print_market_snapshot(
                orderbooks
            )

            # ------------------------------------------------
            # اگر موجودی انتخاب نشده باشد
            # ------------------------------------------------

            if selected_capital_toman is None:

                routes = []

                latest_routes = []

                print()

                print(
                    "⚠️ موجودی هنوز انتخاب نشده."
                )

                print(
                    "از Telegram مبلغ موجودی "
                    "را انتخاب کنید."
                )

            else:

                # --------------------------------------------
                # محاسبه مسیرها
                # --------------------------------------------

                routes = calculate_all_routes(
                    orderbooks,
                    selected_capital_toman
                )

                latest_routes = routes

            # ------------------------------------------------
            # HISTORY
            # ------------------------------------------------

            update_opportunity_history(
                routes
            )

            # ------------------------------------------------
            # ROUTES
            # ------------------------------------------------

            print_routes(
                routes
            )

            # ------------------------------------------------
            # BEST ROUTE
            # ------------------------------------------------

            if routes:

                best = routes[0]

                print()

                print(
                    "⭐ بهترین مسیر فعلی:"
                )

                print(
                    f"{best['buy_exchange']}"
                    " → "
                    f"{best['sell_exchange']}"
                )

                print(
                    f"💰 موجودی انتخاب‌شده: "
                    f"{format_toman(selected_capital_toman)} تومان"
                )

                print(
                    f"💵 سود خالص: "
                    f"{format_toman(best['net_profit'])} تومان"
                )

                print(
                    f"📈 درصد سود: "
                    f"{format_percent(best['profit_percent'])}"
                )

                print(
                    f"🎯 حد هشدار: "
                    f"{format_percent(MIN_PROFIT_PERCENT)}"
                )

                print(
                    f"📦 اجرای Order Book: "
                    f"{best['execution_ratio'] * 100:.1f}%"
                )

                if (
                    best["net_profit"] > 0
                    and
                    best["profit_percent"]
                    >= MIN_PROFIT_PERCENT
                    and
                    best["execution_ratio"]
                    >= MIN_EXECUTION_RATIO
                ):

                    print(
                        "🚨 فرصت واجد شرایط هشدار است."
                    )

                    if send_arbitrage_alert(
                        best,
                        stats
                    ):

                        print(
                            "📨 هشدار Telegram ارسال شد."
                        )

                elif best["net_profit"] > 0:

                    print(
                        "🟡 سود مثبت است، "
                        "اما به حد هشدار نرسیده."
                    )

                else:

                    print(
                        "🔴 بهترین مسیر بعد از "
                        "کارمزد سودده نیست."
                    )

            else:

                print(
                    "ℹ️ مسیر قابل محاسبه وجود ندارد."
                )

            # ------------------------------------------------
            # CAPITAL ANALYSIS
            # ------------------------------------------------

            print_capital_allocation(
                routes
            )

            # ------------------------------------------------
            # STATS
            # ------------------------------------------------

            update_stats(
                stats,
                routes
            )

        else:

            latest_routes = []

            print(
                "❌ هیچ Order Book معتبری دریافت نشد."
            )

        # ----------------------------------------------------
        # PERIODIC REPORT
        # ----------------------------------------------------

        send_periodic_report(
            stats
        )

        # ----------------------------------------------------
        # SLEEP
        # ----------------------------------------------------

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
            "⏹️ ربات به صورت دستی متوقف شد."
        )

    except Exception as e:

        print()

        print(
            f"❌ خطای جدی: {e}"
        )

        raise
