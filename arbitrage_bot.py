"""
============================================================
ربات مانیتورینگ آربیتراژ
Wallex + BitPin + Ramzinex

USDT / TOMAN

فقط مانیتورینگ
بدون معامله واقعی

امکانات:
- بررسی Order Book
- استفاده از Ask برای خرید
- استفاده از Bid برای فروش
- درنظر گرفتن عمق Order Book
- محاسبه کارمزد Maker / Taker
- محاسبه سود خالص
- تشخیص فرصت واقعی
- بررسی پایداری فرصت‌ها در چند چرخه
- پیشنهاد تخصیص سرمایه بر اساس داده چند چرخه
- هشدار تلگرام
- گزارش فارسی
- آمار روزانه / هفتگی / کل
- اجرای مداوم
- ساعت ایران
============================================================
"""

import os
import time
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


# ============================================================
# تنظیمات اصلی
# ============================================================

REQUEST_TIMEOUT = 15

ORDERBOOK_LEVELS = 20

# ------------------------------------------------------------
# سرمایه کل قابل استفاده
# ------------------------------------------------------------

TOTAL_CAPITAL_TOMAN = int(
    os.environ.get(
        "TOTAL_CAPITAL_TOMAN",
        "200000000"
    )
)

# ------------------------------------------------------------
# حداکثر سرمایه مورد بررسی در هر فرصت
# ------------------------------------------------------------

MAX_TRADE_AMOUNT_TOMAN = int(
    os.environ.get(
        "MAX_TRADE_AMOUNT_TOMAN",
        "50000000"
    )
)

# ------------------------------------------------------------
# حداقل سود برای هشدار
# ------------------------------------------------------------

MIN_PROFIT_PERCENT = float(
    os.environ.get(
        "MIN_SPREAD_PERCENT",
        "1.5"
    )
)

# ------------------------------------------------------------
# فاصله بررسی
# ------------------------------------------------------------

CHECK_INTERVAL_SECONDS = int(
    os.environ.get(
        "CHECK_INTERVAL_SECONDS",
        "10"
    )
)

# ------------------------------------------------------------
# فاصله تکرار هشدار
# ------------------------------------------------------------

ALERT_COOLDOWN_SECONDS = int(
    os.environ.get(
        "ALERT_COOLDOWN_SECONDS",
        "60"
    )
)

# ------------------------------------------------------------
# مدت اجرای ربات
# ------------------------------------------------------------

MAX_RUNTIME_SECONDS = int(
    os.environ.get(
        "MAX_RUNTIME_SECONDS",
        "20700"
    )
)

# ------------------------------------------------------------
# نوع کارمزد
# maker / taker
# ------------------------------------------------------------

ORDER_TYPE = os.environ.get(
    "ORDER_TYPE",
    "taker"
).lower()

if ORDER_TYPE not in (
    "maker",
    "taker"
):
    ORDER_TYPE = "taker"


# ============================================================
# تنظیمات تحلیل فرصت
# ============================================================

# چند چرخه اخیر برای تحلیل پایداری فرصت نگهداری شود
OPPORTUNITY_HISTORY_LIMIT = 60

# حداقل تعداد مشاهده مثبت برای اینکه یک مسیر
# در پیشنهاد تخصیص سرمایه وزن قابل توجه بگیرد
MIN_POSITIVE_OBSERVATIONS = 3

# حداقل درصد حجم Order Book که باید قابل اجرا باشد
# در صورت عدم تکمیل معامله، امتیاز فرصت کاهش پیدا می‌کند.
MIN_EXECUTION_RATIO = 0.80


# ============================================================
# فایل آمار
# ============================================================

STATS_FILE = "arbitrage_stats.json"


# ============================================================
# منطقه زمانی ایران
# ============================================================

TEHRAN_TZ = ZoneInfo(
    "Asia/Tehran"
)


# ============================================================
# تلگرام
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
# کارمزد صرافی‌ها
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
# صرافی‌های فعال
# ============================================================

ENABLED_EXCHANGES = [
    "Wallex",
    "BitPin",
    "Ramzinex",
]


# ============================================================
# Session
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 ArbitrageBot/3.0",
    "Accept": "application/json",
})


# ============================================================
# وضعیت داخلی
# ============================================================

last_alert_time = {}

exchange_error_state = {}

runtime_start = time.time()

last_report_minute = None


# ============================================================
# تاریخچه فرصت‌ها
# ============================================================

opportunity_history = []


# ============================================================
# توابع عمومی
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


def safe_float(
    value,
    default=0.0
):

    try:

        return float(value)

    except Exception:

        return default


# ============================================================
# نرمال‌سازی Order Book
# ============================================================

def normalize_orderbook(data):

    result = []

    if not isinstance(
        data,
        list
    ):
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
# مدیریت خطای صرافی
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

        previous_message = previous.get(
            "message"
        )

        previous_time = previous.get(
            "time",
            0
        )

        if (
            previous_message == message
            and
            current - previous_time < 60
        ):

            return

    exchange_error_state[
        exchange
    ] = {
        "message": message,
        "time": current,
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

            # قیمت Ramzinex در این Pair ریالی است
            # تبدیل ریال به تومان

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
# دریافت Order Book همه صرافی‌ها
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
# کارمزد
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
# خرید از Ask ها
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

        "usdt_before_fee":
            received_usdt,

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
# فروش به Bid ها
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

        "received_before_fee":
            received_toman,

        "average_price":
            average_price,

        "unfilled_usdt":
            remaining_usdt,

        "execution_ratio":
            execution_ratio,
    }


# ============================================================
# محاسبه یک مسیر آربیتراژ
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

    # نسبت اجرای واقعی دو طرف مسیر
    execution_ratio = min(
        buy_result[
            "execution_ratio"
        ],
        sell_result[
            "execution_ratio"
        ]
    )

    return {

        "buy_exchange":
            buy_exchange,

        "sell_exchange":
            sell_exchange,

        "buy_price":
            buy_result[
                "average_price"
            ],

        "sell_price":
            sell_result[
                "average_price"
            ],

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

        "buy_unfilled_toman":
            buy_result[
                "unfilled_toman"
            ],

        "sell_unfilled_usdt":
            sell_result[
                "unfilled_usdt"
            ],

        "execution_ratio":
            execution_ratio,

        "fully_executable":
            (
                execution_ratio
                >= MIN_EXECUTION_RATIO
            ),
    }


# ============================================================
# محاسبه همه مسیرها
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
# وضعیت بازار
# ============================================================

def print_market_snapshot(
    orderbooks
):

    best_ask = None

    best_bid = None

    for exchange, book in orderbooks.items():

        if book["asks"]:

            ask_price = (
                book["asks"][0][0]
            )

            if (
                best_ask is None
                or
                ask_price
                < best_ask[0]
            ):

                best_ask = (
                    ask_price,
                    exchange
                )

        if book["bids"]:

            bid_price = (
                book["bids"][0][0]
            )

            if (
                best_bid is None
                or
                bid_price
                > best_bid[0]
            ):

                best_bid = (
                    bid_price,
                    exchange
                )

    print()

    print(
        "========== وضعیت بازار =========="
    )

    if best_ask:

        print(
            "کمترین قیمت خرید: "
            f"{best_ask[1]} "
            "→ "
            f"{format_toman(best_ask[0])} تومان"
        )

    else:

        print(
            "کمترین قیمت خرید: -"
        )

    if best_bid:

        print(
            "بیشترین قیمت فروش: "
            f"{best_bid[1]} "
            "→ "
            f"{format_toman(best_bid[0])} تومان"
        )

    else:

        print(
            "بیشترین قیمت فروش: -"
        )

    print(
        "================================"
    )


# ============================================================
# رتبه‌بندی مسیرها
# ============================================================

def print_routes(routes):

    print()

    print(
        "========== رتبه‌بندی فرصت‌ها =========="
    )

    if not routes:

        print(
            "هیچ مسیر معتبری پیدا نشد."
        )

        print(
            "======================================="
        )

        return

    for index, route in enumerate(
        routes,
        start=1
    ):

        execution_text = (
            "کامل"
            if route["fully_executable"]
            else
            "ناقص"
        )

        print(
            f"{index}. "
            f"خرید از {route['buy_exchange']} "
            f"→ فروش در {route['sell_exchange']} | "
            f"سود: "
            f"{format_percent(route['profit_percent'])} | "
            f"سود خالص: "
            f"{format_toman(route['net_profit'])} تومان | "
            f"اجرا: {execution_text}"
        )

    print(
        "======================================="
    )


# ============================================================
# ثبت تاریخچه فرصت‌ها
# ============================================================

def update_opportunity_history(
    routes
):

    global opportunity_history

    now = now_tehran().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    snapshot = {}

    for route in routes:

        route_key = (
            f"{route['buy_exchange']}"
            "_"
            f"{route['sell_exchange']}"
        )

        snapshot[
            route_key
        ] = {

            "time": now,

            "profit_percent":
                route["profit_percent"],

            "net_profit":
                route["net_profit"],

            "spent":
                route["spent"],

            "execution_ratio":
                route["execution_ratio"],

            "qualified":
                (
                    route["net_profit"] > 0
                    and
                    route["profit_percent"]
                    >= MIN_PROFIT_PERCENT
                ),
        }

    opportunity_history.append(
        snapshot
    )

    if len(
        opportunity_history
    ) > OPPORTUNITY_HISTORY_LIMIT:

        opportunity_history = (
            opportunity_history[
                -OPPORTUNITY_HISTORY_LIMIT:
            ]
        )


# ============================================================
# تحلیل پایداری یک مسیر
# ============================================================

def analyze_route_history(
    route_key
):

    observations = []

    for snapshot in opportunity_history:

        data = snapshot.get(
            route_key
        )

        if data:

            observations.append(
                data
            )

    if not observations:

        return {

            "observations": 0,

            "positive_observations": 0,

            "qualified_observations": 0,

            "positive_ratio": 0,

            "qualified_ratio": 0,

            "average_profit_percent": 0,

            "average_net_profit": 0,

            "average_execution_ratio": 0,

            "score": 0,
        }

    positive = [
        x for x in observations
        if x["net_profit"] > 0
    ]

    qualified = [
        x for x in observations
        if x["qualified"]
    ]

    average_profit = (
        sum(
            x["profit_percent"]
            for x in observations
        )
        / len(observations)
    )

    average_net_profit = (
        sum(
            x["net_profit"]
            for x in observations
        )
        / len(observations)
    )

    average_execution = (
        sum(
            x["execution_ratio"]
            for x in observations
        )
        / len(observations)
    )

    positive_ratio = (
        len(positive)
        / len(observations)
    )

    qualified_ratio = (
        len(qualified)
        / len(observations)
    )

    # --------------------------------------------------------
    # امتیاز پایداری
    #
    # هدف:
    # فرصت‌هایی که:
    # - بیشتر تکرار شده‌اند
    # - سود بیشتری داشته‌اند
    # - حجم بیشتری را قابل اجرا کرده‌اند
    # امتیاز بالاتری بگیرند.
    # --------------------------------------------------------

    stability_score = (
        positive_ratio * 35
        +
        qualified_ratio * 35
        +
        min(
            max(
                average_profit,
                0
            ),
            5
        )
        * 5
        +
        average_execution * 25
    )

    return {

        "observations":
            len(observations),

        "positive_observations":
            len(positive),

        "qualified_observations":
            len(qualified),

        "positive_ratio":
            positive_ratio,

        "qualified_ratio":
            qualified_ratio,

        "average_profit_percent":
            average_profit,

        "average_net_profit":
            average_net_profit,

        "average_execution_ratio":
            average_execution,

        "score":
            stability_score,
    }


# ============================================================
# پیشنهاد تخصیص سرمایه
# ============================================================

def calculate_capital_allocation(
    routes,
    total_capital
):

    """
    این تابع موجودی واقعی صرافی‌ها را نمی‌داند.

    فقط بر اساس رفتار مشاهده‌شده بازار،
    یک پیشنهاد برای محل مناسب‌تر تأمین سرمایه
    ارائه می‌دهد.

    این پیشنهاد دستور معامله نیست.
    """

    scores = {
        exchange: 0.0
        for exchange
        in ENABLED_EXCHANGES
    }

    route_analysis = []

    for route in routes:

        if route["net_profit"] <= 0:
            continue

        route_key = (
            f"{route['buy_exchange']}"
            "_"
            f"{route['sell_exchange']}"
        )

        analysis = analyze_route_history(
            route_key
        )

        # اگر هنوز داده کافی نداریم،
        # فرصت را با احتیاط وزن می‌دهیم.
        observation_factor = min(
            analysis["observations"]
            / MIN_POSITIVE_OBSERVATIONS,
            1.0
        )

        execution_factor = max(
            min(
                route["execution_ratio"],
                1.0
            ),
            0
        )

        profit_factor = max(
            route["profit_percent"],
            0
        )

        # سود فعلی + پایداری + قابلیت اجرا
        current_quality = (
            profit_factor
            * (
                0.40
                +
                0.60
                * observation_factor
            )
            * (
                0.50
                +
                0.50
                * execution_factor
            )
        )

        stability_quality = (
            analysis["score"]
            * 0.03
        )

        final_score = (
            current_quality
            +
            stability_quality
        )

        if final_score <= 0:
            continue

        route_analysis.append(
            (
                route,
                analysis,
                final_score
            )
        )

        # صرافی خرید اهمیت بیشتری دارد،
        # چون برای شروع مسیر به سرمایه تومانی
        # نیاز داریم.
        scores[
            route["buy_exchange"]
        ] += final_score

        # صرافی فروش نیز برای داشتن USDT
        # در سمت مقصد اهمیت دارد.
        scores[
            route["sell_exchange"]
        ] += (
            final_score
            * 0.50
        )

    total_score = sum(
        scores.values()
    )

    if total_score <= 0:

        return {

            exchange: 0
            for exchange
            in ENABLED_EXCHANGES
        }

    # --------------------------------------------------------
    # تخصیص اولیه
    # --------------------------------------------------------

    allocation = {}

    for exchange in ENABLED_EXCHANGES:

        share = (
            scores[exchange]
            / total_score
        )

        allocation[
            exchange
        ] = int(
            total_capital
            * share
        )

    # --------------------------------------------------------
    # اصلاح اختلاف گرد کردن
    # --------------------------------------------------------

    allocated = sum(
        allocation.values()
    )

    difference = (
        total_capital
        - allocated
    )

    if ENABLED_EXCHANGES:

        allocation[
            ENABLED_EXCHANGES[0]
        ] += difference

    return allocation


# ============================================================
# نمایش پیشنهاد تخصیص سرمایه
# ============================================================

def print_capital_allocation(
    routes
):

    allocation = (
        calculate_capital_allocation(
            routes,
            TOTAL_CAPITAL_TOMAN
        )
    )

    print()

    print(
        "========== پیشنهاد تخصیص سرمایه =========="
    )

    print(
        f"سرمایه کل قابل استفاده: "
        f"{format_toman(TOTAL_CAPITAL_TOMAN)} تومان"
    )

    print()

    if not any(
        allocation.values()
    ):

        print(
            "فعلاً داده کافی برای پیشنهاد "
            "تخصیص سرمایه وجود ندارد."
        )

        print(
            "ربات ترجیح می‌دهد بدون داده کافی "
            "پیشنهاد عددی ندهد."
        )

        print(
            "=========================================="
        )

        return allocation

    for exchange in ENABLED_EXCHANGES:

        amount = allocation.get(
            exchange,
            0
        )

        percentage = (
            amount
            / TOTAL_CAPITAL_TOMAN
            * 100
            if TOTAL_CAPITAL_TOMAN > 0
            else 0
        )

        print(
            f"{exchange}: "
            f"{format_toman(amount)} تومان "
            f"({percentage:.1f}%)"
        )

    print()

    print(
        "ℹ️ این پیشنهاد بر اساس داده‌های "
        "مشاهده‌شده چند چرخه اخیر است."
    )

    print(
        "⚠️ موجودی واقعی صرافی‌ها در محاسبه "
        "وارد نشده است."
    )

    print(
        "⚠️ این پیشنهاد به معنی انجام معامله نیست."
    )

    print(
        "=========================================="
    )

    return allocation


# ============================================================
# تلگرام
# ============================================================

def send_telegram(
    message
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
            f"⚠️ خطای تلگرام: {e}"
        )

        return False


# ============================================================
# هشدار آربیتراژ
# ============================================================

def send_arbitrage_alert(
    route
):

    buy_exchange = (
        route["buy_exchange"]
    )

    sell_exchange = (
        route["sell_exchange"]
    )

    route_key = (
        f"{buy_exchange}_"
        f"به_"
        f"{sell_exchange}"
    )

    current_time = time.time()

    previous_time = (
        last_alert_time.get(
            route_key,
            0
        )
    )

    if (
        current_time
        - previous_time
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

    if (
        profit_percent
        < MIN_PROFIT_PERCENT
    ):

        return

    history = analyze_route_history(
        route_key
    )

    message = (
        "🚨 فرصت آربیتراژ\n\n"

        f"خرید از: {buy_exchange}\n"
        f"فروش در: {sell_exchange}\n\n"

        f"قیمت میانگین خرید: "
        f"{format_toman(route['buy_price'])} تومان\n"

        f"قیمت میانگین فروش: "
        f"{format_toman(route['sell_price'])} تومان\n\n"

        f"سرمایه استفاده‌شده: "
        f"{format_toman(route['spent'])} تومان\n"

        f"مقدار USDT: "
        f"{route['usdt']:.4f}\n\n"

        f"سود خالص: "
        f"{format_toman(profit)} تومان\n"

        f"درصد سود: "
        f"{format_percent(profit_percent)}\n\n"

        f"قابلیت اجرای Order Book: "
        f"{route['execution_ratio'] * 100:.1f}%\n"

        f"تعداد مشاهده مسیر: "
        f"{history['observations']}\n"

        f"تعداد مشاهده سودده: "
        f"{history['positive_observations']}\n\n"

        f"کارمزد خرید: "
        f"{route['buy_fee'] * 100:.3f}%\n"

        f"کارمزد فروش: "
        f"{route['sell_fee'] * 100:.3f}%\n\n"

        "⚠️ فقط هشدار و مانیتورینگ\n"
        "❌ معامله واقعی انجام نمی‌شود."
    )

    if send_telegram(
        message
    ):

        last_alert_time[
            route_key
        ] = current_time


# ============================================================
# ساختار پیش‌فرض آمار
# ============================================================

def default_stats():

    return {

        "total_route_checks": 0,

        "total_positive_opportunities": 0,

        "total_qualified_opportunities": 0,

        "total_simulated_profit_toman": 0,

        "total_alerts": 0,

        "daily": {},

        "weekly": {},
    }


# ============================================================
# بارگذاری آمار
# ============================================================

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


# ============================================================
# ذخیره آمار
# ============================================================

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
            f"⚠️ خطا در ذخیره آمار: {e}"
        )


# ============================================================
# ثبت آمار
# ============================================================

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

            "route_checks": 0,

            "positive": 0,

            "qualified": 0,

            "simulated_profit_toman": 0,

            "alerts": 0,
        }

    if week not in stats["weekly"]:

        stats["weekly"][week] = {

            "route_checks": 0,

            "positive": 0,

            "qualified": 0,

            "simulated_profit_toman": 0,

            "alerts": 0,
        }

    # --------------------------------------------------------
    # هر route که بررسی شده
    # --------------------------------------------------------

    route_count = len(
        routes
    )

    stats[
        "total_route_checks"
    ] += route_count

    stats[
        "daily"
    ][today][
        "route_checks"
    ] += route_count

    stats[
        "weekly"
    ][week][
        "route_checks"
    ] += route_count

    # --------------------------------------------------------
    # فرصت‌های مثبت و واجد شرایط
    # --------------------------------------------------------

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
# گزارش دوره‌ای
# ============================================================

REPORT_TIMES = {
    "10:00",
    "16:00",
    "18:00",
}


def send_periodic_report(
    stats
):

    global last_report_minute

    now = now_tehran()

    current_time = now.strftime(
        "%H:%M"
    )

    if (
        current_time
        not in REPORT_TIMES
    ):

        return

    if (
        last_report_minute
        == current_time
    ):

        return

    last_report_minute = (
        current_time
    )

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
            "route_checks": 0,
            "positive": 0,
            "qualified": 0,
            "simulated_profit_toman": 0,
            "alerts": 0,
        }
    )

    weekly = stats[
        "weekly"
    ].get(
        week,
        {
            "route_checks": 0,
            "positive": 0,
            "qualified": 0,
            "simulated_profit_toman": 0,
            "alerts": 0,
        }
    )

    message = (
        "📊 گزارش آربیتراژ\n\n"

        f"تاریخ: {today}\n"
        f"ساعت: {current_time} تهران\n\n"

        "امروز:\n"

        f"مسیرهای بررسی‌شده: "
        f"{daily['route_checks']}\n"

        f"فرصت‌های سودده: "
        f"{daily['positive']}\n"

        f"فرصت‌های واجد شرایط: "
        f"{daily['qualified']}\n"

        f"سود شبیه‌سازی‌شده: "
        f"{format_toman(daily['simulated_profit_toman'])} تومان\n\n"

        "۷ روز اخیر:\n"

        f"مسیرهای بررسی‌شده: "
        f"{weekly['route_checks']}\n"

        f"فرصت‌های سودده: "
        f"{weekly['positive']}\n"

        f"فرصت‌های واجد شرایط: "
        f"{weekly['qualified']}\n"

        f"سود شبیه‌سازی‌شده: "
        f"{format_toman(weekly['simulated_profit_toman'])} تومان\n\n"

        "کل دوره:\n"

        f"مسیرهای بررسی‌شده: "
        f"{stats['total_route_checks']}\n"

        f"فرصت‌های سودده: "
        f"{stats['total_positive_opportunities']}\n"

        f"فرصت‌های واجد شرایط: "
        f"{stats['total_qualified_opportunities']}\n"

        f"سود شبیه‌سازی‌شده کل: "
        f"{format_toman(stats['total_simulated_profit_toman'])} تومان\n\n"

        "⚠️ اعداد سود، شبیه‌سازی Order Book هستند "
        "و به معنی سود واقعی انجام‌شده نیستند."
    )

    send_telegram(
        message
    )


# ============================================================
# پیام شروع
# ============================================================

def send_startup_message():

    message = (
        "🤖 ربات آربیتراژ شروع شد\n\n"

        "حالت: فقط مانیتورینگ\n"
        "معامله واقعی: خیر\n\n"

        "صرافی‌ها:\n"
        "• Wallex\n"
        "• BitPin\n"
        "• Ramzinex\n\n"

        f"سرمایه کل قابل استفاده: "
        f"{format_toman(TOTAL_CAPITAL_TOMAN)} تومان\n"

        f"حداکثر سرمایه هر فرصت: "
        f"{format_toman(MAX_TRADE_AMOUNT_TOMAN)} تومان\n"

        f"حداقل سود: "
        f"{format_percent(MIN_PROFIT_PERCENT)}\n"

        f"فاصله بررسی: "
        f"{CHECK_INTERVAL_SECONDS} ثانیه\n"

        f"نوع کارمزد: "
        f"{ORDER_TYPE}\n\n"

        "تحلیل سرمایه:\n"
        "بر اساس تکرار فرصت + سود + نقدشوندگی\n\n"

        "منطقه زمانی: تهران"
    )

    send_telegram(
        message
    )


# ============================================================
# MAIN
# ============================================================

def main():

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
        f"💰 سرمایه کل قابل استفاده: "
        f"{format_toman(TOTAL_CAPITAL_TOMAN)} تومان"
    )

    print(
        f"💵 حداکثر سرمایه هر فرصت: "
        f"{format_toman(MAX_TRADE_AMOUNT_TOMAN)} تومان"
    )

    print(
        f"📈 حداقل سود: "
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
        +
        ", ".join(
            ENABLED_EXCHANGES
        )
    )

    print(
        "================================================"
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
                "⏹️ حداکثر زمان اجرا به پایان رسید."
            )

            print(
                "ربات به شکل امن متوقف شد."
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
            "🔎 در حال دریافت Order Book..."
        )

        orderbooks = (
            get_all_orderbooks()
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

            routes = calculate_all_routes(
                orderbooks,
                MAX_TRADE_AMOUNT_TOMAN
            )

            # ------------------------------------------------
            # ثبت تاریخچه قبل از تحلیل تخصیص
            # ------------------------------------------------

            update_opportunity_history(
                routes
            )

            print_routes(
                routes
            )

            # ------------------------------------------------
            # بهترین مسیر فعلی
            # ------------------------------------------------

            if routes:

                best_route = routes[0]

                print()

                print(
                    "⭐ بهترین مسیر فعلی:"
                )

                print(
                    f"{best_route['buy_exchange']}"
                    " → "
                    f"{best_route['sell_exchange']}"
                )

                print(
                    f"💰 سود خالص: "
                    f"{format_toman(best_route['net_profit'])} تومان"
                )

                print(
                    f"📈 درصد سود: "
                    f"{format_percent(best_route['profit_percent'])}"
                )

                print(
                    f"📦 قابلیت اجرای Order Book: "
                    f"{best_route['execution_ratio'] * 100:.1f}%"
                )

                route_key = (
                    f"{best_route['buy_exchange']}"
                    "_"
                    f"{best_route['sell_exchange']}"
                )

                history = analyze_route_history(
                    route_key
                )

                print(
                    f"🔁 تعداد مشاهده این مسیر: "
                    f"{history['observations']}"
                )

                print(
                    f"📈 دفعات سودده: "
                    f"{history['positive_observations']}"
                )

                print(
                    f"🎯 دفعات رسیدن به حداقل سود: "
                    f"{history['qualified_observations']}"
                )

                if (
                    best_route["profit_percent"]
                    >= MIN_PROFIT_PERCENT
                    and
                    best_route["net_profit"]
                    > 0
                    and
                    best_route["execution_ratio"]
                    >= MIN_EXECUTION_RATIO
                ):

                    print(
                        "🚨 این مسیر به حداقل سود "
                        "و حداقل قابلیت اجرای تعیین‌شده رسیده است."
                    )

                    send_arbitrage_alert(
                        best_route
                    )

                else:

                    print(
                        "ℹ️ فعلاً فرصت واجد شرایط "
                        "برای هشدار وجود ندارد."
                    )

            # ------------------------------------------------
            # پیشنهاد تخصیص سرمایه
            # ------------------------------------------------

            print_capital_allocation(
                routes
            )

            # ------------------------------------------------
            # آمار
            # ------------------------------------------------

            update_stats(
                stats,
                routes
            )

        else:

            print(
                "❌ هیچ Order Book معتبری دریافت نشد."
            )

        # ----------------------------------------------------
        # گزارش دوره‌ای
        # ----------------------------------------------------

        send_periodic_report(
            stats
        )

        # ----------------------------------------------------
        # زمان خواب
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
# اجرای برنامه
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
