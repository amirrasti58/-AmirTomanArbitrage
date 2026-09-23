"""
============================================================
ربات مانیتورینگ آربیتراژ
Wallex + BitPin + Ramzinex

USDT / TOMAN

امکانات:
- دریافت Order Book
- Ask برای خرید / Bid برای فروش
- عمق Order Book
- کارمزد Maker / Taker
- محاسبه سود خالص
- انتخاب موجودی از داخل Telegram
- موجودی پیش‌فرض ۵۰ میلیون تومان
- گزارش وضعیت هر دو ساعت
- عدم ارسال گزارش دوره‌ای از 23:00 تا 08:00
- چرخه گزارش:
  18:00 / 20:00 / 22:00
  سپس روز بعد 08:00 / 10:00 / ...
- هشدار فرصت واقعی در صورت عبور از حد سود
- آمار روزانه / هفتگی / کل
- پیشنهاد تخصیص سرمایه فقط پس از داده کافی
============================================================
"""

import json
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


# ============================================================
# تنظیمات اصلی
# ============================================================

REQUEST_TIMEOUT = 15
ORDERBOOK_LEVELS = 20

MIN_PROFIT_PERCENT = float(
    os.environ.get("MIN_SPREAD_PERCENT", "1.0")
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

if ORDER_TYPE not in ("maker", "taker"):
    ORDER_TYPE = "taker"


# ============================================================
# تحلیل فرصت
# ============================================================

OPPORTUNITY_HISTORY_LIMIT = 120
MIN_ALLOCATION_OBSERVATIONS = 50
MIN_POSITIVE_OBSERVATIONS = 3
MIN_EXECUTION_RATIO = 0.80
MAX_EXCHANGE_ALLOCATION_PERCENT = 0.70


# ============================================================
# فایل آمار
# ============================================================

STATS_FILE = "arbitrage_stats.json"


# ============================================================
# منطقه زمانی
# ============================================================

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


# ============================================================
# تلگرام
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN", ""
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID", ""
)


# ============================================================
# کارمزد
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
# صرافی‌ها
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
    "User-Agent": "Mozilla/5.0 ArbitrageBot/5.0",
    "Accept": "application/json",
})


# ============================================================
# وضعیت داخلی
# ============================================================

runtime_start = time.time()
last_report_minute = None
last_alert_time = {}
exchange_error_state = {}

selected_capital_toman = 50_000_000

waiting_for_custom_capital = False
telegram_update_offset = None

latest_orderbooks = {}
latest_routes = []

opportunity_history = []


# ============================================================
# ابزارهای عمومی
# ============================================================

def now_tehran():
    return datetime.now(TEHRAN_TZ)


def format_toman(value):
    if value is None:
        return "-"

    return f"{value:,.0f}"


def format_percent(value):
    """
    مثبت:
    1.2%

    منفی:
    1.2%-
    """

    if value is None:
        return "-"

    if value < 0:
        return f"{abs(value):.1f}%-"

    return f"{value:.1f}%"


def format_toman_signed(value):
    """
    مثبت:
    134,977

    منفی:
    134,977-
    """

    if value is None:
        return "-"

    if value < 0:
        return f"{abs(value):,.0f}-"

    return f"{value:,.0f}"


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
# فرمت وضعیت Order Book
# ============================================================

def format_orderbook_execution(route):
    """
    اگر کل حجم مورد نیاز قابل اجرا باشد:
        قابلیت اجرای کامل را دارد

    اگر ناقص باشد:
        مثلا 90٪ Order Book اجرا می‌گردد
    """

    ratio = route.get(
        "execution_ratio",
        0
    )

    if ratio >= 1.0:
        return "قابلیت اجرای کامل را دارد"

    return (
        f"{ratio * 100:.0f}٪ Order Book اجرا می‌گردد"
    )


def format_route_side(
    exchange,
    amount_toman,
    usdt_amount,
    average_price,
    orderbook_levels,
    action
):
    """
    توضیح یک سمت معامله.

    خرید:
    خرید 50,000,000 تومان از Wallex
    با 1 لول Order Book

    فروش:
    فروش 219.3 تتر در Wallex
    با 1 لول Order Book
    """

    if action == "buy":

        return (
            f"خرید {format_toman(amount_toman)} تومان "
            f"از {exchange} "
            f"با {orderbook_levels} لول Order Book"
        )

    return (
        f"فروش {usdt_amount:.1f} تتر "
        f"در {exchange} "
        f"با {orderbook_levels} لول Order Book"
    )


def get_orderbook_levels_for_amount(
    levels,
    target_amount,
    is_buy
):
    """
    تعداد واقعی لول‌هایی که برای حجم موردنیاز
    مصرف شده‌اند.
    """

    remaining = target_amount
    used_levels = 0

    for price, volume in levels:

        if remaining <= 0:
            break

        used_levels += 1

        if is_buy:

            level_value = price * volume

        else:

            level_value = volume

        remaining -= level_value

    return used_levels


# ============================================================
# Order Book
# ============================================================

def normalize_orderbook(data):

    result = []

    if not isinstance(data, list):
        return result

    for item in data:

        try:

            if isinstance(item, (list, tuple)):

                if len(item) < 2:
                    continue

                price = float(item[0])
                volume = float(item[1])

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
            and current - previous["time"] < 60
        ):
            return

    exchange_error_state[exchange] = {
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
        "https://api.wallex.ir/v1/"
        "depth?symbol=USDTTMN"
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
                raw.get("asks", [])
            )
        )

        bids = normalize_orderbook(
            raw.get(
                "bid",
                raw.get("bids", [])
            )
        )

        if not asks or not bids:
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
            data.get("asks", [])
        )

        bids = normalize_orderbook(
            data.get("bids", [])
        )

        if not asks or not bids:
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

            bids = normalize_orderbook(
                buys
            )

            asks = normalize_orderbook(
                sells
            )

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
# دریافت همه Order Book ها
# ============================================================

def get_all_orderbooks():

    functions = {
        "Wallex": get_wallex_orderbook,
        "BitPin": get_bitpin_orderbook,
        "Ramzinex": get_ramzinex_orderbook,
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
            orderbooks[exchange] = result

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


def get_fee_currency(
    exchange,
    side
):
    """
    واحد کارمزد:

    خرید:
    معمولاً تتر

    فروش:
    معمولاً تومان

    اگر مشخص نباشد:
    تومان/تتر
    """

    if exchange in FEES:

        if side == "buy":
            return "تتر"

        if side == "sell":
            return "تومان"

    return "تومان/تتر"


# ============================================================
# خرید از Ask
# ============================================================

def calculate_buy(
    asks,
    amount_toman,
    fee
):

    remaining_toman = amount_toman
    received_usdt = 0.0
    spent_toman = 0.0
    used_levels = 0

    for price, volume in asks:

        if remaining_toman <= 0:
            break

        used_levels += 1

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

    usdt_after_fee = (
        received_usdt * (1 - fee)
    )

    average_price = (
        spent_toman / received_usdt
    )

    execution_ratio = (
        spent_toman / amount_toman
    )

    return {
        "spent_toman": spent_toman,
        "usdt_before_fee": received_usdt,
        "usdt": usdt_after_fee,
        "average_price": average_price,
        "unfilled_toman": remaining_toman,
        "execution_ratio": execution_ratio,
        "used_levels": used_levels,
    }


# ============================================================
# فروش به Bid
# ============================================================

def calculate_sell(
    bids,
    usdt_amount,
    fee
):

    remaining_usdt = usdt_amount
    received_toman = 0.0
    sold_usdt = 0.0
    used_levels = 0

    for price, volume in bids:

        if remaining_usdt <= 0:
            break

        used_levels += 1

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
        received_toman * (1 - fee)
    )

    average_price = (
        received_toman / sold_usdt
    )

    execution_ratio = (
        sold_usdt / usdt_amount
    )

    return {
        "sold_usdt": sold_usdt,
        "received_toman": received_after_fee,
        "received_before_fee": received_toman,
        "average_price": average_price,
        "unfilled_usdt": remaining_usdt,
        "execution_ratio": execution_ratio,
        "used_levels": used_levels,
    }


# ============================================================
# یک مسیر آربیتراژ
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
        final_toman - actual_spent
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
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,

        "buy_price": buy_result[
            "average_price"
        ],

        "sell_price": sell_result[
            "average_price"
        ],

        "usdt": buy_result["usdt"],

        "spent": actual_spent,

        "received": final_toman,

        "net_profit": net_profit,

        "profit_percent": profit_percent,

        "buy_fee": buy_fee,

        "sell_fee": sell_fee,

        "buy_fee_currency":
            get_fee_currency(
                buy_exchange,
                "buy"
            ),

        "sell_fee_currency":
            get_fee_currency(
                sell_exchange,
                "sell"
            ),

        "buy_unfilled_toman": (
            buy_result["unfilled_toman"]
        ),

        "sell_unfilled_usdt": (
            sell_result["unfilled_usdt"]
        ),

        "execution_ratio": execution_ratio,

        "buy_orderbook_levels":
            buy_result["used_levels"],

        "sell_orderbook_levels":
            sell_result["used_levels"],

        "fully_executable": (
            execution_ratio
            >= MIN_EXECUTION_RATIO
        ),
    }


# ============================================================
# همه مسیرها
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

            if buy_exchange == sell_exchange:
                continue

            route = calculate_route(
                buy_exchange,
                sell_exchange,
                orderbooks,
                amount_toman
            )

            if route:
                routes.append(route)

    routes.sort(
        key=lambda x: x["net_profit"],
        reverse=True
    )

    return routes


# ============================================================
# نمایش بازار
# ============================================================

def print_market_snapshot(
    orderbooks
):

    best_ask = None
    best_bid = None

    print()
    print(
        "========== قیمت‌های بازار =========="
    )

    for exchange in ENABLED_EXCHANGES:

        book = orderbooks.get(
            exchange
        )

        if not book:

            print(
                f"{exchange}: "
                "❌ Order Book دریافت نشد"
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

        if ask is not None and (
            best_ask is None
            or ask < best_ask[0]
        ):

            best_ask = (
                ask,
                exchange
            )

        if bid is not None and (
            best_bid is None
            or bid > best_bid[0]
        ):

            best_bid = (
                bid,
                exchange
            )

    print()

    if best_ask:

        print(
            f"🟢 کمترین Ask: "
            f"{best_ask[1]} → "
            f"{format_toman(best_ask[0])} تومان"
        )

    if best_bid:

        print(
            f"🔴 بیشترین Bid: "
            f"{best_bid[1]} → "
            f"{format_toman(best_bid[0])} تومان"
        )

    print(
        "===================================="
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
            "هیچ مسیر قابل محاسبه‌ای وجود ندارد."
        )

        print(
            "======================================="
        )

        return

    for index, route in enumerate(
        routes,
        start=1
    ):

        execution = (
            "کامل"
            if route["fully_executable"]
            else "ناقص"
        )

        print(
            f"{index}. "
            f"{route['buy_exchange']} → "
            f"{route['sell_exchange']} | "
            f"سود "
            f"{format_percent(route['profit_percent'])} | "
            f"خالص "
            f"{format_toman_signed(route['net_profit'])} تومان | "
            f"اجرا "
            f"{route['execution_ratio'] * 100:.1f}% "
            f"({execution})"
        )

    print(
        "======================================="
    )


# ============================================================
# تاریخچه فرصت
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

        key = (
            f"{route['buy_exchange']}_"
            f"{route['sell_exchange']}"
        )

        snapshot[key] = {
            "time": now,

            "profit_percent": (
                route["profit_percent"]
            ),

            "net_profit": (
                route["net_profit"]
            ),

            "spent": route["spent"],

            "execution_ratio": (
                route["execution_ratio"]
            ),

            "qualified": (
                route["net_profit"] > 0
                and route["profit_percent"]
                >= MIN_PROFIT_PERCENT
                and route["execution_ratio"]
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
    route_key
):

    observations = []

    for snapshot in opportunity_history:

        data = snapshot.get(
            route_key
        )

        if data:
            observations.append(data)

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
            "stability_score": 0,
        }

    positive = [
        x
        for x in observations
        if x["net_profit"] > 0
    ]

    qualified = [
        x
        for x in observations
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

    stability_score = (
        positive_ratio * 35
        + qualified_ratio * 35
        + min(
            max(
                average_profit,
                0
            ),
            5
        ) * 5
        + average_execution * 25
    )

    return {
        "observations": len(observations),
        "positive_observations": (
            len(positive)
        ),
        "qualified_observations": (
            len(qualified)
        ),
        "positive_ratio": positive_ratio,
        "qualified_ratio": qualified_ratio,
        "average_profit_percent": (
            average_profit
        ),
        "average_net_profit": (
            average_net_profit
        ),
        "average_execution_ratio": (
            average_execution
        ),
        "stability_score": stability_score,
    }


# ============================================================
# پیشنهاد تخصیص سرمایه
# ============================================================

def calculate_capital_allocation(
    routes
):

    if selected_capital_toman is None:
        return None, "capital_not_selected"

    if (
        len(opportunity_history)
        < MIN_ALLOCATION_OBSERVATIONS
    ):

        return None, "insufficient_data"

    scores = {
        exchange: 0.0
        for exchange in ENABLED_EXCHANGES
    }

    for route in routes:

        if route["net_profit"] <= 0:
            continue

        key = (
            f"{route['buy_exchange']}_"
            f"{route['sell_exchange']}"
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
            1.0
        )

        profit_factor = min(
            max(
                (
                    route["profit_percent"]
                    * 0.60
                    + history[
                        "average_profit_percent"
                    ]
                    * 0.40
                )
                / max(
                    MIN_PROFIT_PERCENT,
                    0.1
                ),
                0
            )
            / 2.0,
            1.0
        )

        route_score = (
            0.15 * observation_factor
            + 0.20 * history[
                "positive_ratio"
            ]
            + 0.30 * history[
                "qualified_ratio"
            ]
            + 0.15 * history[
                "average_execution_ratio"
            ]
            + 0.20 * profit_factor
        )

        route_score *= 1.10

        scores[
            route["buy_exchange"]
        ] += route_score * 0.60

        scores[
            route["sell_exchange"]
        ] += route_score * 0.40

    total_score = sum(
        scores.values()
    )

    if total_score <= 0:
        return None, "no_suitable_route"

    weights = {
        exchange:
            scores[exchange]
            / total_score
        for exchange in ENABLED_EXCHANGES
    }

    weights = {
        exchange: min(
            weights[exchange],
            MAX_EXCHANGE_ALLOCATION_PERCENT
        )
        for exchange in ENABLED_EXCHANGES
    }

    allocation = {
        exchange: int(
            selected_capital_toman
            * weights[exchange]
        )
        for exchange in ENABLED_EXCHANGES
    }

    return allocation, "ready"


def print_capital_allocation(
    routes
):

    allocation, status = (
        calculate_capital_allocation(
            routes
        )
    )

    print()
    print(
        "========== پیشنهاد تخصیص سرمایه =========="
    )

    if selected_capital_toman is None:

        print(
            "⚠️ هنوز موجودی از Telegram "
            "انتخاب نشده است."
        )

        print(
            "=========================================="
        )

        return

    print(
        f"💰 موجودی انتخاب‌شده: "
        f"{format_toman(selected_capital_toman)} تومان"
    )

    if status == "insufficient_data":

        print(
            f"⏳ برای تخصیص عددی حداقل "
            f"{MIN_ALLOCATION_OBSERVATIONS} "
            f"چرخه لازم است."
        )

        print(
            f"داده فعلی: "
            f"{len(opportunity_history)} چرخه"
        )

        print(
            "=========================================="
        )

        return

    if status != "ready":

        print(
            "ℹ️ فعلاً مسیر مناسب برای تخصیص وجود ندارد."
        )

        print(
            "=========================================="
        )

        return

    for exchange in ENABLED_EXCHANGES:

        amount = allocation.get(
            exchange,
            0
        )

        percent = (
            amount
            / selected_capital_toman
            * 100
        )

        print(
            f"{exchange}: "
            f"{format_toman(amount)} تومان "
            f"({percent:.1f}%)"
        )

    print(
        "⚠️ این فقط پیشنهاد تحلیلی است، نه دستور معامله."
    )

    print(
        "=========================================="
    )


# ============================================================
# آمار
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

            data = json.load(file)

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


def save_stats(stats):

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

    template = {
        "route_checks": 0,
        "positive": 0,
        "qualified": 0,
        "simulated_profit_toman": 0,
        "alerts": 0,
    }

    if today not in stats["daily"]:
        stats["daily"][today] = (
            template.copy()
        )

    if week not in stats["weekly"]:
        stats["weekly"][week] = (
            template.copy()
        )

    route_count = len(routes)

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
            and route["profit_percent"]
            >= MIN_PROFIT_PERCENT
            and route["execution_ratio"]
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

    save_stats(stats)


# ============================================================
# Telegram
# ============================================================

def send_telegram(
    message,
    reply_markup=None
):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
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
            f"⚠️ خطای تلگرام: {e}"
        )

        return False


# ============================================================
# کیبورد انتخاب موجودی
# ============================================================

def capital_keyboard():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "۵۰ میلیون",
                    "callback_data":
                        "CAPITAL:50000000"
                },
                {
                    "text": "۱۰۰ میلیون",
                    "callback_data":
                        "CAPITAL:100000000"
                },
            ],

            [
                {
                    "text": "۲۰۰ میلیون",
                    "callback_data":
                        "CAPITAL:200000000"
                },
                {
                    "text": "۵۰۰ میلیون",
                    "callback_data":
                        "CAPITAL:500000000"
                },
            ],

            [
                {
                    "text": "۱ میلیارد",
                    "callback_data":
                        "CAPITAL:1000000000"
                },
                {
                    "text": "✏️ مبلغ دلخواه",
                    "callback_data":
                        "CAPITAL:CUSTOM"
                },
            ],

            [
                {
                    "text": "📊 وضعیت",
                    "callback_data":
                        "MENU:STATUS"
                },
            ],

            [
                {
                    "text": "↩️ برگشت",
                    "callback_data":
                        "MENU:MAIN"
                },
            ],
        ]
    }


# ============================================================
# منوی اصلی
# ============================================================

def main_menu_keyboard():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "📊 وضعیت",
                    "callback_data":
                        "MENU:STATUS"
                },
            ],

            [
                {
                    "text": "💰 انتخاب موجودی",
                    "callback_data":
                        "MENU:CAPITAL"
                },
            ],
        ]
    }


# ============================================================
# کیبورد بعد از انتخاب موجودی
# ============================================================

def selected_capital_keyboard():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "📊 وضعیت",
                    "callback_data":
                        "MENU:STATUS"
                },
            ],

            [
                {
                    "text": "💰 تغییر موجودی",
                    "callback_data":
                        "MENU:CAPITAL"
                },
            ],

            [
                {
                    "text": "↩️ برگشت",
                    "callback_data":
                        "MENU:MAIN"
                },
            ],
        ]
    }


def send_main_menu():

    return send_telegram(
        "📋 منوی اصلی\n\n"
        f"💰 موجودی فعلی: "
        f"{format_toman(selected_capital_toman)} تومان",
        main_menu_keyboard()
    )


def send_capital_menu():

    return send_telegram(
        "💰 انتخاب موجودی\n\n"
        "مبلغ کل سرمایه‌ای که می‌خواهید ربات بر اساس آن "
        "محاسبات Order Book و سود را انجام دهد انتخاب کنید.\n\n"
        f"💰 موجودی فعلی: "
        f"{format_toman(selected_capital_toman)} تومان",
        capital_keyboard()
    )


# ============================================================
# پاسخ Callback
# ============================================================

def answer_callback_query(
    callback_query_id,
    text=""
):

    if (
        not TELEGRAM_BOT_TOKEN
        or not callback_query_id
    ):
        return

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
                    callback_query_id,
                "text": text,
            },
            timeout=REQUEST_TIMEOUT
        )

    except Exception:
        pass


def set_selected_capital(
    amount
):

    global selected_capital_toman

    if (
        amount is None
        or amount <= 0
    ):
        return False

    selected_capital_toman = int(
        amount
    )

    print(
        f"💰 موجودی انتخاب شد: "
        f"{format_toman(selected_capital_toman)} تومان"
    )

    return True


# ============================================================
# مدیریت پیام Telegram
# ============================================================

def handle_telegram_update(
    update
):

    global waiting_for_custom_capital

    callback = update.get(
        "callback_query"
    )

    if callback:

        callback_id = callback.get(
            "id",
            ""
        )

        data = callback.get(
            "data",
            ""
        )

        if data == "MENU:MAIN":

            waiting_for_custom_capital = (
                False
            )

            answer_callback_query(
                callback_id,
                "بازگشت"
            )

            send_main_menu()

            return

        if data == "MENU:CAPITAL":

            waiting_for_custom_capital = (
                False
            )

            answer_callback_query(
                callback_id,
                "انتخاب موجودی"
            )

            send_capital_menu()

            return

        if data == "MENU:STATUS":

            answer_callback_query(
                callback_id,
                "در حال دریافت وضعیت..."
            )

            send_current_status_message()

            return

        if data.startswith(
            "CAPITAL:"
        ):

            value = data.split(
                ":",
                1
            )[1]

            if value == "CUSTOM":

                waiting_for_custom_capital = (
                    True
                )

                answer_callback_query(
                    callback_id,
                    "مبلغ دلخواه را ارسال کنید."
                )

                send_telegram(
                    "✏️ مبلغ دلخواه را به تومان "
                    "فقط به صورت عدد بفرستید.\n\n"
                    "مثال:\n"
                    "370000000"
                )

                return

            try:

                amount = int(value)

            except Exception:

                amount = 0

            if set_selected_capital(
                amount
            ):

                waiting_for_custom_capital = (
                    False
                )

                answer_callback_query(
                    callback_id,
                    "موجودی انتخاب شد."
                )

                send_telegram(
                    "✅ موجودی انتخاب شد.\n\n"
                    f"💰 {format_toman(amount)} تومان\n\n"
                    "از این مبلغ در محاسبات ربات استفاده می‌شود.",
                    selected_capital_keyboard()
                )

            else:

                answer_callback_query(
                    callback_id,
                    "مبلغ نامعتبر است."
                )

            return

    message = update.get(
        "message"
    )

    if not message:
        return

    chat_id = str(
        message.get(
            "chat",
            {}
        ).get(
            "id",
            ""
        )
    )

    if (
        str(TELEGRAM_CHAT_ID)
        != chat_id
    ):
        return

    text = str(
        message.get(
            "text",
            ""
        )
    ).strip()

    if text in (
        "/start",
    ):

        waiting_for_custom_capital = (
            False
        )

        send_main_menu()

        return

    if text in (
        "/capital",
        "موجودی",
        "انتخاب موجودی"
    ):

        waiting_for_custom_capital = (
            False
        )

        send_capital_menu()

        return

    if text in (
        "/status",
        "وضعیت"
    ):

        send_current_status_message()

        return

    if waiting_for_custom_capital:

        normalized = normalize_digits(
            text
        )

        normalized = (
            normalized
            .replace(",", "")
            .replace("٬", "")
            .replace(" ", "")
        )

        try:

            amount = int(
                normalized
            )

        except Exception:

            amount = 0

        if amount <= 0:

            send_telegram(
                "❌ مبلغ نامعتبر است.\n\n"
                "مبلغ را فقط به تومان "
                "و به صورت عدد ارسال کنید."
            )

            return

        set_selected_capital(
            amount
        )

        waiting_for_custom_capital = (
            False
        )

        send_telegram(
            "✅ موجودی با موفقیت ثبت شد.\n\n"
            f"💰 {format_toman(amount)} تومان\n\n"
            "از این مبلغ در محاسبات ربات استفاده می‌شود.",
            selected_capital_keyboard()
        )


# ============================================================
# Telegram Polling
# ============================================================

def telegram_polling_loop():

    global telegram_update_offset

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        print(
            "⚠️ اطلاعات Telegram کامل نیست؛ "
            "کنترل Telegram فعال نشد."
        )

        return

    print(
        "📲 کنترل Telegram فعال شد."
    )

    while True:

        try:

            url = (
                "https://api.telegram.org/bot"
                f"{TELEGRAM_BOT_TOKEN}"
                "/getUpdates"
            )

            params = {
                "timeout": 20,
                "allowed_updates":
                    json.dumps(
                        [
                            "message",
                            "callback_query"
                        ]
                    ),
            }

            if (
                telegram_update_offset
                is not None
            ):

                params["offset"] = (
                    telegram_update_offset
                )

            response = SESSION.get(
                url,
                params=params,
                timeout=30
            )

            response.raise_for_status()

            data = response.json()

            if not data.get("ok"):

                time.sleep(3)

                continue

            for update in data.get(
                "result",
                []
            ):

                telegram_update_offset = (
                    update.get(
                        "update_id",
                        0
                    ) + 1
                )

                handle_telegram_update(
                    update
                )

        except Exception as e:

            print(
                f"⚠️ خطای دریافت پیام Telegram: {e}"
            )

            time.sleep(5)


def start_telegram_listener():

    thread = threading.Thread(
        target=telegram_polling_loop,
        daemon=True
    )

    thread.start()


# ============================================================
# هشدار آربیتراژ
# ============================================================

def send_arbitrage_alert(
    route,
    stats
):

    route_key = (
        f"{route['buy_exchange']}_به_"
        f"{route['sell_exchange']}"
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

    history_key = (
        f"{route['buy_exchange']}_"
        f"{route['sell_exchange']}"
    )

    history = analyze_route_history(
        history_key
    )

    message = (
        "🚨 فرصت آربیتراژ\n\n"

        f"خرید از: "
        f"{route['buy_exchange']}\n"

        f"فروش در: "
        f"{route['sell_exchange']}\n\n"

        f"💰 موجودی انتخاب‌شده: "
        f"{format_toman(selected_capital_toman)} تومان\n"

        f"💵 سود خالص: "
        f"{format_toman_signed(route['net_profit'])} تومان\n"

        f"📈 سود: "
        f"{format_percent(route['profit_percent'])}\n"

        f"📦 Order Book: "
        f"{format_orderbook_execution(route)}\n\n"

        f"💲 خرید: "
        f"{format_toman(route['spent'])} تومان "
        f"از {route['buy_exchange']} "
        f"با {route['buy_orderbook_levels']} لول Order Book\n"

        f"💲 فروش: "
        f"{route['usdt']:.1f} تتر "
        f"در {route['sell_exchange']} "
        f"با {route['sell_orderbook_levels']} لول Order Book\n\n"

        f"💳 کارمزد خرید: "
        f"{route['buy_fee'] * 100:.1f}% "
        f"({route['buy_fee_currency']})\n"

        f"💳 کارمزد فروش: "
        f"{route['sell_fee'] * 100:.1f}% "
        f"({route['sell_fee_currency']})\n\n"

        f"🔁 سابقه مسیر:\n"

        f"• مشاهده: "
        f"{history['observations']}\n"

        f"• سودده: "
        f"{history['positive_observations']}\n"

        f"• رسیدن به حد سود: "
        f"{history['qualified_observations']}\n"
    )

    if send_telegram(message):

        last_alert_time[
            route_key
        ] = current_time

        stats[
            "total_alerts"
        ] += 1

        today = now_tehran().strftime(
            "%Y-%m-%d"
        )

        week = now_tehran().strftime(
            "%Y-W%W"
        )

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

        save_stats(stats)

        return True

    return False


# ============================================================
# گزارش وضعیت Telegram
# ============================================================

REPORT_TIMES = {
    "08:00",
    "10:00",
    "12:00",
    "14:00",
    "16:00",
    "18:00",
    "20:00",
    "22:00",
}


def build_current_status_message(
    stats
):

    now = now_tehran()

    today = now.strftime(
        "%Y-%m-%d"
    )

    empty = {
        "route_checks": 0,
        "positive": 0,
        "qualified": 0,
        "simulated_profit_toman": 0,
        "alerts": 0,
    }

    daily = stats[
        "daily"
    ].get(
        today,
        empty.copy()
    )

    lines = [

        "📊 وضعیت فعلی آربیتراژ",

        "",

        "💰 موجودی:",

        (
            f"{format_toman(selected_capital_toman)} تومان"
            if selected_capital_toman is not None
            else "❌ هنوز انتخاب نشده"
        ),
    ]

    # ========================================================
    # بهترین مسیر
    # ========================================================

    if latest_routes:

        best = latest_routes[0]

        route_key = (
            f"{best['buy_exchange']}_"
            f"{best['sell_exchange']}"
        )

        history = analyze_route_history(
            route_key
        )

        lines.extend([

            "",

            "🏆 بهترین مسیر فعلی:",

            f"{best['buy_exchange']} → "
            f"{best['sell_exchange']}",

            "",

            f"💵 سود خالص: "
            f"{format_toman_signed(best['net_profit'])} تومان",

            f"📈 درصد سود: "
            f"{format_percent(best['profit_percent'])}",

            f"🎯 حد هشدار: "
            f"{MIN_PROFIT_PERCENT:.1f}%",

            f"📦 وضعیت Order Book: "
            f"{format_orderbook_execution(best)}",

            f"💰 مقدار قابل خرید با مبلغ موجودی: "
            f"{format_toman(best['spent'])} تومان",

            f"💱 مقدار USDT: "
            f"{best['usdt']:.1f} تتر",

            "",

            "💲 جزئیات خرید و فروش:",

            (
                f"• خرید {format_toman(best['spent'])} تومان "
                f"از {best['buy_exchange']} "
                f"با {best['buy_orderbook_levels']} لول Order Book"
            ),

            (
                f"• فروش {best['usdt']:.1f} تتر "
                f"در {best['sell_exchange']} "
                f"با {best['sell_orderbook_levels']} لول Order Book"
            ),

            "",

            "💳 کارمزد:",

            (
                f"• خرید: "
                f"{best['buy_fee'] * 100:.1f}% "
                f"({best['buy_fee_currency']})"
            ),

            (
                f"• فروش: "
                f"{best['sell_fee'] * 100:.1f}% "
                f"({best['sell_fee_currency']})"
            ),

            "",

            "🔁 سابقه مسیر:",

            f"• مشاهده: "
            f"{history['observations']}",

            f"• سودده: "
            f"{history['positive_observations']}",

            f"• واجد شرایط: "
            f"{history['qualified_observations']}",

            f"• میانگین سود: "
            f"{format_percent(history['average_profit_percent'])}",
        ])

        if (
            best["net_profit"] > 0
            and best["profit_percent"]
            >= MIN_PROFIT_PERCENT
            and best["execution_ratio"]
            >= MIN_EXECUTION_RATIO
        ):

            lines.append(
                "🚨 وضعیت: فرصت واجد شرایط هشدار است."
            )

        elif best["net_profit"] > 0:

            lines.append(
                "ℹ️ وضعیت: سود مثبت است، "
                "اما هنوز به حد هشدار نرسیده."
            )

        else:

            lines.append(
                "🔴 وضعیت: بهترین مسیر فعلی "
                "بعد از کارمزد سودده نیست."
            )

        # ====================================================
        # سه مسیر برتر
        # ====================================================

        lines.extend([

            "",

            "🏆 سه مسیر برتر فعلی:",
        ])

        for index, route in enumerate(
            latest_routes[:3],
            start=1
        ):

            profit_text = format_percent(
                route["profit_percent"]
            )

            net_text = format_toman_signed(
                route["net_profit"]
            )

            if route["profit_percent"] < 0:
                profit_display = (
                    f"🔴{profit_text}"
                )
            else:
                profit_display = profit_text

            if route["net_profit"] < 0:
                net_display = (
                    f"🔴{net_text} تومان"
                )
            else:
                net_display = (
                    f"{net_text} تومان"
                )

            lines.append(
                f"{index}. "
                f"{route['buy_exchange']} → "
                f"{route['sell_exchange']} | "
                f"{profit_display} | "
                f"{net_display}"
            )

    else:

        lines.extend([

            "",

            "ℹ️ فعلاً مسیر قابل محاسبه‌ای وجود ندارد.",
        ])

    # ========================================================
    # وضعیت صرافی‌ها
    # ========================================================

    lines.extend([

        "",

        "🏦 وضعیت صرافی‌ها:",
    ])

    for exchange in ENABLED_EXCHANGES:

        if exchange in latest_orderbooks:

            book = latest_orderbooks[
                exchange
            ]

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
                f"• {exchange}: ✅ "
                f"قیمت خرید {format_toman(ask)} | "
                f"قیمت فروش {format_toman(bid)}"
            )

        else:

            lines.append(
                f"• {exchange}: "
                f"❌ Order Book نامعتبر"
            )

    # ========================================================
    # آمار امروز
    # ========================================================

    lines.extend([

        "",

        "📅 آمار امروز:",

        f"• بررسی مسیر: "
        f"{daily['route_checks']}",

        f"• فرصت سودده: "
        f"{daily['positive']}",

        f"• فرصت واجد شرایط: "
        f"{daily['qualified']}",

        f"• هشدار ارسال‌شده: "
        f"{daily['alerts']}",

        f"• سود محاسبه‌شده: "
        f"{format_toman_signed(daily['simulated_profit_toman'])} تومان",

        "",

        f"🕐 زمان: "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} تهران",
    ])

    return "\n".join(lines)


# ============================================================
# ارسال وضعیت فعلی
# ============================================================

def send_current_status_message(
    stats=None
):

    if stats is None:
        stats = load_stats()

    return send_telegram(

        build_current_status_message(
            stats
        ),

        {
            "inline_keyboard": [

                [
                    {
                        "text": "💰 تغییر موجودی",
                        "callback_data":
                            "MENU:CAPITAL",
                    },
                ],

                [
                    {
                        "text": "↩️ برگشت",
                        "callback_data":
                            "MENU:MAIN",
                    },
                ],
            ]
        }
    )


# ============================================================
# گزارش دوره‌ای
# ============================================================

def send_periodic_report(
    stats
):

    global last_report_minute

    now = now_tehran()

    hour = now.hour

    current_time = now.strftime(
        "%H:%M"
    )

    if hour >= 23 or hour < 8:
        return

    if current_time not in REPORT_TIMES:
        return

    if (
        last_report_minute
        == current_time
    ):
        return

    last_report_minute = (
        current_time
    )

    send_current_status_message(
        stats
    )


# ============================================================
# پیام شروع
# ============================================================

def send_startup_message():

    message = (

        "🤖 ربات آربیتراژ شروع شد\n\n"

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

        f"💰 موجودی فعلی: "
        f"{format_toman(selected_capital_toman)} تومان\n\n"

        "📊 گزارش وضعیت: هر دو ساعت\n"

        "🌙 گزارش دوره‌ای: "
        "23:00 تا 08:00 متوقف\n"

        "⏰ چرخه گزارش از 18:00 محاسبه می‌شود."
    )

    send_telegram(
        message,
        main_menu_keyboard()
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
        "================================================"
    )

    print(
        f"💰 موجودی پیش‌فرض: "
        f"{format_toman(selected_capital_toman)} تومان"
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

            save_stats(stats)

            break

        cycle_start = time.time()

        print()

        print(
            "------------------------------------------------"
        )

        print(
            "🕐 زمان: "
            f"{now_tehran().strftime('%Y-%m-%d %H:%M:%S')} تهران"
        )

        print(
            "🔎 در حال دریافت Order Book..."
        )

        orderbooks = get_all_orderbooks()

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

            routes = calculate_all_routes(
                orderbooks,
                selected_capital_toman
            )

            latest_routes = routes

            update_opportunity_history(
                routes
            )

            print_routes(
                routes
            )

            if routes:

                best = routes[0]

                print()

                print(
                    "⭐ بهترین مسیر فعلی:"
                )

                print(
                    f"{best['buy_exchange']} → "
                    f"{best['sell_exchange']}"
                )

                print(
                    f"💰 موجودی انتخاب‌شده: "
                    f"{format_toman(selected_capital_toman)} تومان"
                )

                print(
                    f"💵 سود خالص: "
                    f"{format_toman_signed(best['net_profit'])} تومان"
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
                    f"📦 قابلیت اجرای Order Book: "
                    f"{best['execution_ratio'] * 100:.1f}%"
                )

                if (
                    best["net_profit"] > 0
                    and best["profit_percent"]
                    >= MIN_PROFIT_PERCENT
                    and best["execution_ratio"]
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

                else:

                    print(
                        "ℹ️ فعلاً فرصت واجد شرایط "
                        "برای هشدار وجود ندارد."
                    )

            print_capital_allocation(
                routes
            )

            update_stats(
                stats,
                routes
            )

        else:

            latest_routes = []

            print(
                "❌ هیچ Order Book معتبری دریافت نشد."
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
# اجرا
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
