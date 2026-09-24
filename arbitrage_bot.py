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
- حداقل سود قابل‌اعتنا: ۳۰۰,۰۰۰ تومان
- انتخاب موجودی از داخل Telegram
- انتخاب حد هشدار از داخل Telegram
- موجودی پیش‌فرض ۵۰ میلیون تومان
- حد هشدار پیش‌فرض ۱ درصد
- گزارش وضعیت هر دو ساعت
- عدم ارسال گزارش دوره‌ای از 23:00 تا 08:00
- هشدار فرصت واقعی در صورت عبور از حد سود
- آمار روزانه / هفتگی / کل
- پیشنهاد تخصیص سرمایه فقط پس از داده کافی
- نمایش سود و زیان با نشانگر وضعیت
- نمایش جزئیات خرید و فروش مناسب موبایل
- تاریخچه فرصت‌های واجد شرایط
- نمایش تاریخچه از داخل Telegram
============================================================
"""

import json
import os
import threading
import time
from datetime import datetime, timedelta
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

MIN_NET_PROFIT_TOMAN = 300_000

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
# فایل‌های ذخیره‌سازی
# ============================================================

STATS_FILE = "arbitrage_stats.json"

# تاریخچه دائمی فرصت‌های واجد شرایط
HISTORY_FILE = "arbitrage_history.json"

# حداکثر تعداد رکوردهای تاریخچه دائمی
HISTORY_LIMIT = 1000


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
waiting_for_custom_alert_threshold = False

telegram_update_offset = None

latest_orderbooks = {}
latest_routes = []

# تاریخچه تحلیلی داخل RAM
opportunity_history = []

# تاریخچه دائمی روی فایل
persistent_history = []


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
    1.20%

    منفی:
    0.03%-
    """

    if value is None:
        return "-"

    if value < 0:
        return f"{abs(value):.2f}%-"

    return f"{value:.2f}%"


def format_toman_signed(value):
    """
    مثبت:
    143,371

    منفی:
    143,371-
    """

    if value is None:
        return "-"

    number = f"{abs(value):,.0f}"

    if value < 0:
        return f"{number}-"

    return number


def format_usdt(value):
    if value is None:
        return "-"

    return f"{abs(value):,.1f}"


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
# نمایش سود / زیان
# ============================================================

def get_profit_indicator(value):

    if value is None:
        return "⚪"

    if value < 0:
        return "🔴"

    if value > 0:
        return "🟢"

    return "⚪"


def get_profit_label(value):

    if value is not None and value < 0:
        return "زیان خالص"

    if value is not None and value > 0:
        return "سود خالص"

    return "نتیجه خالص"


def get_profit_percent_label(value):

    if value is not None and value < 0:
        return "درصد زیان"

    if value is not None and value > 0:
        return "درصد سود"

    return "درصد نتیجه"


def format_profit_line(value):

    indicator = get_profit_indicator(value)
    label = get_profit_label(value)
    amount = format_toman_signed(value)

    return (
        f"{indicator} {label}: "
        f"{amount} تومان"
    )


def format_profit_percent_line(value):

    indicator = get_profit_indicator(value)
    label = get_profit_percent_label(value)

    percent = format_percent(value)

    return (
        f"{indicator} {label}: "
        f"{percent}"
    )


# ============================================================
# وضعیت Order Book
# ============================================================

def format_orderbook_execution(route):

    ratio = route.get(
        "execution_ratio",
        0
    )

    if ratio >= 0.999999:
        return "📦 قابلیت اجرای کامل را دارد"

    return (
        f"📦 {ratio * 100:.0f}٪ اردربوک اجرا می‌گردد"
    )


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

    fee_usdt = (
        received_usdt
        - usdt_after_fee
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
        "fee_usdt": fee_usdt,
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

    fee_toman = (
        received_toman
        - received_after_fee
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
        "fee_toman": fee_toman,
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

        "buy_fee_amount_usdt":
            buy_result["fee_usdt"],

        "sell_fee_amount_toman":
            sell_result["fee_toman"],

        "buy_unfilled_toman":
            buy_result["unfilled_toman"],

        "sell_unfilled_usdt":
            sell_result["unfilled_usdt"],

        "execution_ratio":
            execution_ratio,

        "buy_orderbook_levels":
            buy_result["used_levels"],

        "sell_orderbook_levels":
            sell_result["used_levels"],

        "fully_executable":
            (
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
            f"قیمت خرید (Ask): {format_toman(ask)} | "
            f"قیمت فروش (Bid): {format_toman(bid)}"
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
            f"🟢 کمترین قیمت خرید: "
            f"{best_ask[1]} → "
            f"{format_toman(best_ask[0])} تومان"
        )

    if best_bid:

        print(
            f"🔴 بیشترین قیمت فروش: "
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
            f"{get_profit_label(route['net_profit'])}: "
            f"{format_toman_signed(route['net_profit'])} تومان | "
            f"{get_profit_percent_label(route['profit_percent'])}: "
            f"{format_percent(route['profit_percent'])} | "
            f"اجرا: "
            f"{route['execution_ratio'] * 100:.1f}% "
            f"({execution})"
        )

    print(
        "======================================="
    )


# ============================================================
# تاریخچه تحلیلی داخل RAM
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
                    route["net_profit"]
                    >= MIN_NET_PROFIT_TOMAN
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


# ============================================================
# تاریخچه دائمی
# ============================================================

def load_persistent_history():

    global persistent_history

    if not os.path.exists(
        HISTORY_FILE
    ):
        persistent_history = []
        return

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, list):

            persistent_history = data[
                -HISTORY_LIMIT:
            ]

        else:

            persistent_history = []

    except Exception as e:

        print(
            f"⚠️ خطا در خواندن تاریخچه: {e}"
        )

        persistent_history = []


def save_persistent_history():

    try:

        with open(
            HISTORY_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                persistent_history[
                    -HISTORY_LIMIT:
                ],
                file,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            f"⚠️ خطا در ذخیره تاریخچه: {e}"
        )


def save_history_record(
    route
):

    global persistent_history

    # فقط فرصت‌های واقعاً واجد شرایط
    if (
        route["net_profit"]
        < MIN_NET_PROFIT_TOMAN
    ):
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

    now = now_tehran()

    record = {
        "timestamp":
            now.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "date":
            now.strftime(
                "%Y-%m-%d"
            ),

        "time":
            now.strftime(
                "%H:%M:%S"
            ),

        "buy_exchange":
            route["buy_exchange"],

        "sell_exchange":
            route["sell_exchange"],

        "capital_toman":
            selected_capital_toman,

        "spent":
            route["spent"],

        "usdt":
            route["usdt"],

        "received":
            route["received"],

        "net_profit":
            route["net_profit"],

        "profit_percent":
            route["profit_percent"],

        "buy_price":
            route["buy_price"],

        "sell_price":
            route["sell_price"],

        "buy_orderbook_levels":
            route["buy_orderbook_levels"],

        "sell_orderbook_levels":
            route["sell_orderbook_levels"],

        "execution_ratio":
            route["execution_ratio"],

        "buy_fee":
            route["buy_fee"],

        "sell_fee":
            route["sell_fee"],
    }

    # جلوگیری از ثبت تکراری همان فرصت
    # در فاصله بسیار کوتاه
    if persistent_history:

        last = persistent_history[-1]

        same_route = (
            last.get("buy_exchange")
            == record["buy_exchange"]
            and
            last.get("sell_exchange")
            == record["sell_exchange"]
        )

        try:

            last_time = datetime.strptime(
                last.get(
                    "timestamp",
                    ""
                ),
                "%Y-%m-%d %H:%M:%S"
            ).replace(
                tzinfo=TEHRAN_TZ
            )

            seconds_since = (
                now - last_time
            ).total_seconds()

        except Exception:

            seconds_since = 999999

        # اگر همان مسیر در کمتر از 60 ثانیه
        # دوباره دیده شود، رکورد جدید نساز
        if (
            same_route
            and seconds_since < 60
        ):

            return False

    persistent_history.append(
        record
    )

    if (
        len(persistent_history)
        > HISTORY_LIMIT
    ):

        persistent_history = (
            persistent_history[
                -HISTORY_LIMIT:
            ]
        )

    save_persistent_history()

    return True


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
        if x["net_profit"]
        >= MIN_NET_PROFIT_TOMAN
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

        "stability_score":
            stability_score,
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

        if route["net_profit"] < MIN_NET_PROFIT_TOMAN:
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

        if route["net_profit"] >= MIN_NET_PROFIT_TOMAN:

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
            route["net_profit"]
            >= MIN_NET_PROFIT_TOMAN
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
                {
                    "text": "🎯 حد هشدار",
                    "callback_data":
                        "MENU:ALERT"
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
# کیبورد حد هشدار
# ============================================================

def alert_threshold_keyboard():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "۰.۵٪",
                    "callback_data":
                        "ALERT:0.5"
                },
                {
                    "text": "۱٪",
                    "callback_data":
                        "ALERT:1.0"
                },
                {
                    "text": "۱.۵٪",
                    "callback_data":
                        "ALERT:1.5"
                },
            ],

            [
                {
                    "text": "۲٪",
                    "callback_data":
                        "ALERT:2.0"
                },
                {
                    "text": "۳٪",
                    "callback_data":
                        "ALERT:3.0"
                },
                {
                    "text": "✏️ مقدار دلخواه",
                    "callback_data":
                        "ALERT:CUSTOM"
                },
            ],

            [
                {
                    "text": "📊 وضعیت",
                    "callback_data":
                        "MENU:STATUS"
                },

                {
                    "text": "📚 تاریخچه",
                    "callback_data":
                        "MENU:HISTORY"
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
# منوی تاریخچه
# ============================================================

def history_keyboard():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "📅 امروز",
                    "callback_data":
                        "HISTORY:TODAY"
                },
                {
                    "text": "📅 دیروز",
                    "callback_data":
                        "HISTORY:YESTERDAY"
                },
            ],

            [
                {
                    "text": "📊 ۷ روز اخیر",
                    "callback_data":
                        "HISTORY:7DAYS"
                },
                {
                    "text": "📈 آمار کامل",
                    "callback_data":
                        "HISTORY:ALL"
                },
            ],

            [
                {
                    "text": "🔄 تازه‌سازی",
                    "callback_data":
                        "MENU:HISTORY"
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

                {
                    "text": "📚 تاریخچه",
                    "callback_data":
                        "MENU:HISTORY"
                },
            ],

            [
                {
                    "text": "💰 انتخاب موجودی",
                    "callback_data":
                        "MENU:CAPITAL"
                },

                {
                    "text": "🎯 حد هشدار",
                    "callback_data":
                        "MENU:ALERT"
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

                {
                    "text": "📚 تاریخچه",
                    "callback_data":
                        "MENU:HISTORY"
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
                    "text": "🎯 تغییر حد هشدار",
                    "callback_data":
                        "MENU:ALERT"
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
        f"{format_toman(selected_capital_toman)} تومان\n"
        f"🎯 حد هشدار فعلی: "
        f"{MIN_PROFIT_PERCENT:.1f}%\n"
        f"💡 حداقل سود قابل‌اعتنا: "
        f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان",
        main_menu_keyboard()
    )


def send_capital_menu():

    return send_telegram(
        "💰 انتخاب موجودی\n\n"
        "مبلغ کل سرمایه‌ای که می‌خواهید ربات بر اساس آن "
        "محاسبات Order Book و سود را انجام دهد انتخاب کنید.\n\n"
        f"💰 موجودی فعلی: "
        f"{format_toman(selected_capital_toman)} تومان\n"
        f"🎯 حد هشدار فعلی: "
        f"{MIN_PROFIT_PERCENT:.1f}%\n"
        f"💡 حداقل سود قابل‌اعتنا: "
        f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان",
        capital_keyboard()
    )


def send_alert_threshold_menu():

    return send_telegram(
        "🎯 انتخاب حد هشدار\n\n"
        "هرگاه سود خالص مسیر به این درصد برسد یا از آن عبور کند، "
        "مسیر واجد شرایط هشدار خواهد شد.\n\n"
        f"🎯 حد هشدار فعلی: "
        f"{MIN_PROFIT_PERCENT:.1f}%\n"
        f"💡 حداقل سود خالص قابل‌اعتنا: "
        f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان",
        alert_threshold_keyboard()
    )


# ============================================================
# ساخت صفحه تاریخچه
# ============================================================

def get_history_records_today():

    today = now_tehran().date()

    result = []

    for record in persistent_history:

        try:

            record_date = datetime.strptime(
                record.get("date", ""),
                "%Y-%m-%d"
            ).date()

            if record_date == today:
                result.append(record)

        except Exception:
            continue

    return result


def get_history_records_yesterday():

    yesterday = (
        now_tehran().date()
        - timedelta(days=1)
    )

    result = []

    for record in persistent_history:

        try:

            record_date = datetime.strptime(
                record.get("date", ""),
                "%Y-%m-%d"
            ).date()

            if record_date == yesterday:
                result.append(record)

        except Exception:
            continue

    return result


def get_history_records_7days():

    today = now_tehran().date()

    start_date = (
        today
        - timedelta(days=6)
    )

    result = []

    for record in persistent_history:

        try:

            record_date = datetime.strptime(
                record.get("date", ""),
                "%Y-%m-%d"
            ).date()

            if (
                start_date
                <= record_date
                <= today
            ):
                result.append(record)

        except Exception:
            continue

    return result


def build_history_record_text(
    record
):

    profit = record.get(
        "net_profit",
        0
    )

    percent = record.get(
        "profit_percent",
        0
    )

    return (
        f"🕐 {record.get('timestamp', '-')}\n"
        f"{record.get('buy_exchange', '-')} → "
        f"{record.get('sell_exchange', '-')}\n"
        f"{format_profit_line(profit)}\n"
        f"{format_profit_percent_line(percent)}\n"
        f"💰 سرمایه: "
        f"{format_toman(record.get('capital_toman'))} تومان\n"
        f"📥 خرید: "
        f"{format_toman(record.get('buy_price'))} تومان "
        f"({record.get('buy_orderbook_levels', 0)} لول)\n"
        f"📤 فروش: "
        f"{format_toman(record.get('sell_price'))} تومان "
        f"({record.get('sell_orderbook_levels', 0)} لول)"
    )


def build_history_message(
    records,
    title
):

    lines = [
        f"📚 تاریخچه آربیتراژ",
        f"🗂 {title}",
        "",
    ]

    if not records:

        lines.extend([
            "ℹ️ هنوز فرصت واجد شرایطی در این بازه ثبت نشده است.",
            "",
            f"🎯 حد هشدار فعلی: "
            f"{MIN_PROFIT_PERCENT:.1f}%",
            f"💡 حداقل سود: "
            f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان",
        ])

        return "\n".join(lines)

    # جدیدترین موارد اول
    selected = list(
        reversed(records)
    )

    # برای جلوگیری از پیام خیلی بزرگ
    selected = selected[:15]

    for index, record in enumerate(
        selected,
        start=1
    ):

        lines.extend([
            f"#{index}",
            build_history_record_text(
                record
            ),
            "",
            "━━━━━━━━━━━━━━",
            "",
        ])

    if len(records) > 15:

        lines.extend([
            f"ℹ️ نمایش ۱۵ مورد از "
            f"{len(records)} مورد.",
            "",
        ])

    # خلاصه بازه
    total_profit = sum(
        float(
            record.get(
                "net_profit",
                0
            )
        )
        for record in records
    )

    average_percent = (
        sum(
            float(
                record.get(
                    "profit_percent",
                    0
                )
            )
            for record in records
        )
        / len(records)
    )

    lines.extend([
        "📊 خلاصه این بازه",
        "",
        f"تعداد فرصت: {len(records)}",
        f"مجموع سود ثبت‌شده: "
        f"{format_toman_signed(total_profit)} تومان",
        f"میانگین درصد: "
        f"{format_percent(average_percent)}",
    ])

    return "\n".join(lines)


def build_history_all_stats():

    lines = [
        "📈 آمار کامل تاریخچه",
        "",
    ]

    total = len(
        persistent_history
    )

    if total == 0:

        lines.extend([
            "ℹ️ هنوز تاریخچه‌ای ثبت نشده است.",
            "",
            f"🎯 حد هشدار: "
            f"{MIN_PROFIT_PERCENT:.1f}%",
        ])

        return "\n".join(lines)

    total_profit = sum(
        float(
            record.get(
                "net_profit",
                0
            )
        )
        for record in persistent_history
    )

    average_profit = (
        total_profit / total
    )

    average_percent = (
        sum(
            float(
                record.get(
                    "profit_percent",
                    0
                )
            )
            for record in persistent_history
        )
        / total
    )

    best_record = max(
        persistent_history,
        key=lambda x: float(
            x.get(
                "net_profit",
                0
            )
        )
    )

    route_counts = {}

    for record in persistent_history:

        key = (
            f"{record.get('buy_exchange', '-')}"
            f" → "
            f"{record.get('sell_exchange', '-')}"
        )

        route_counts[key] = (
            route_counts.get(key, 0)
            + 1
        )

    most_common_route = max(
        route_counts,
        key=route_counts.get
    )

    lines.extend([

        f"📌 تعداد کل فرصت‌های ثبت‌شده: "
        f"{total}",

        "",

        "💰 نتیجه ثبت‌شده:",

        f"{format_profit_line(total_profit)}",

        f"📊 میانگین سود/زیان: "
        f"{format_percent(average_percent)}",

        "",

        "🏆 بیشترین سود ثبت‌شده:",

        f"{format_toman(best_record.get('net_profit', 0))} تومان",

        f"مسیر: "
        f"{best_record.get('buy_exchange', '-')} → "
        f"{best_record.get('sell_exchange', '-')}",

        f"زمان: "
        f"{best_record.get('timestamp', '-')}",

        "",

        "🔁 پرتکرارترین مسیر:",

        f"{most_common_route}",

        f"تعداد ثبت: "
        f"{route_counts[most_common_route]}",

        "",

        f"🎯 حد هشدار فعلی: "
        f"{MIN_PROFIT_PERCENT:.1f}%",

        f"💡 حداقل سود قابل‌اعتنا: "
        f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان",

        "",

        f"📦 ظرفیت ذخیره تاریخچه: "
        f"{HISTORY_LIMIT} رکورد",

    ])

    return "\n".join(lines)


def send_history_menu():

    return send_telegram(
        "📚 تاریخچه آربیتراژ\n\n"
        f"🗃 تعداد رکورد ذخیره‌شده: "
        f"{len(persistent_history)}\n\n"
        "بازه موردنظر را انتخاب کنید:",
        history_keyboard()
    )


def send_history_today():

    records = (
        get_history_records_today()
    )

    return send_telegram(
        build_history_message(
            records,
            "امروز"
        ),
        history_keyboard()
    )


def send_history_yesterday():

    records = (
        get_history_records_yesterday()
    )

    return send_telegram(
        build_history_message(
            records,
            "دیروز"
        ),
        history_keyboard()
    )


def send_history_7days():

    records = (
        get_history_records_7days()
    )

    return send_telegram(
        build_history_message(
            records,
            "۷ روز اخیر"
        ),
        history_keyboard()
    )


def send_history_all():

    return send_telegram(
        build_history_all_stats(),
        history_keyboard()
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


def set_alert_threshold(
    value
):

    global MIN_PROFIT_PERCENT

    try:

        value = float(value)

    except Exception:

        return False

    if value <= 0:
        return False

    if value > 100:
        return False

    MIN_PROFIT_PERCENT = value

    print(
        f"🎯 حد هشدار تغییر کرد: "
        f"{MIN_PROFIT_PERCENT:.1f}%"
    )

    return True


# ============================================================
# مدیریت پیام Telegram
# ============================================================

def handle_telegram_update(
    update
):

    global waiting_for_custom_capital
    global waiting_for_custom_alert_threshold

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

            waiting_for_custom_capital = False
            waiting_for_custom_alert_threshold = False

            answer_callback_query(
                callback_id,
                "بازگشت"
            )

            send_main_menu()

            return

        if data == "MENU:CAPITAL":

            waiting_for_custom_capital = False
            waiting_for_custom_alert_threshold = False

            answer_callback_query(
                callback_id,
                "انتخاب موجودی"
            )

            send_capital_menu()

            return

        if data == "MENU:ALERT":

            waiting_for_custom_capital = False
            waiting_for_custom_alert_threshold = False

            answer_callback_query(
                callback_id,
                "انتخاب حد هشدار"
            )

            send_alert_threshold_menu()

            return

        if data == "MENU:STATUS":

            waiting_for_custom_capital = False
            waiting_for_custom_alert_threshold = False

            answer_callback_query(
                callback_id,
                "در حال دریافت وضعیت..."
            )

            send_current_status_message()

            return

        # ====================================================
        # تاریخچه
        # ====================================================

        if data == "MENU:HISTORY":

            waiting_for_custom_capital = False
            waiting_for_custom_alert_threshold = False

            answer_callback_query(
                callback_id,
                "تاریخچه"
            )

            send_history_menu()

            return

        if data == "HISTORY:TODAY":

            waiting_for_custom_capital = False
            waiting_for_custom_alert_threshold = False

            answer_callback_query(
                callback_id,
                "تاریخچه امروز"
            )

            send_history_today()

            return

        if data == "HISTORY:YESTERDAY":

            waiting_for_custom_capital = False
            waiting_for_custom_alert_threshold = False

            answer_callback_query(
                callback_id,
                "تاریخچه دیروز"
            )

            send_history_yesterday()

            return

        if data == "HISTORY:7DAYS":

            waiting_for_custom_capital = False
            waiting_for_custom_alert_threshold = False

            answer_callback_query(
                callback_id,
                "تاریخچه ۷ روز اخیر"
            )

            send_history_7days()

            return

        if data == "HISTORY:ALL":

            waiting_for_custom_capital = False
            waiting_for_custom_alert_threshold = False

            answer_callback_query(
                callback_id,
                "آمار کامل"
            )

            send_history_all()

            return

        if data.startswith(
            "CAPITAL:"
        ):

            value = data.split(
                ":",
                1
            )[1]

            if value == "CUSTOM":

                waiting_for_custom_capital = True
                waiting_for_custom_alert_threshold = False

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

                waiting_for_custom_capital = False

                answer_callback_query(
                    callback_id,
                    "موجودی انتخاب شد."
                )

                send_telegram(
                    "✅ موجودی انتخاب شد.\n\n"
                    f"💰 {format_toman(amount)} تومان\n\n"
                    f"🎯 حد هشدار فعلی: "
                    f"{MIN_PROFIT_PERCENT:.1f}%\n"
                    f"💡 حداقل سود قابل‌اعتنا: "
                    f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان\n\n"
                    "از این مبلغ در محاسبات ربات استفاده می‌شود.",
                    selected_capital_keyboard()
                )

            else:

                answer_callback_query(
                    callback_id,
                    "مبلغ نامعتبر است."
                )

            return

        if data.startswith(
            "ALERT:"
        ):

            value = data.split(
                ":",
                1
            )[1]

            if value == "CUSTOM":

                waiting_for_custom_alert_threshold = True
                waiting_for_custom_capital = False

                answer_callback_query(
                    callback_id,
                    "درصد دلخواه را ارسال کنید."
                )

                send_telegram(
                    "✏️ حد هشدار دلخواه را به درصد "
                    "ارسال کنید.\n\n"
                    "مثال:\n"
                    "1.2\n\n"
                    "یا:\n"
                    "۱.۲"
                )

                return

            try:

                threshold = float(
                    normalize_digits(value)
                )

            except Exception:

                threshold = 0

            if set_alert_threshold(
                threshold
            ):

                waiting_for_custom_alert_threshold = False

                answer_callback_query(
                    callback_id,
                    "حد هشدار تغییر کرد."
                )

                send_telegram(
                    "✅ حد هشدار تغییر کرد.\n\n"
                    f"🎯 حد هشدار جدید: "
                    f"{MIN_PROFIT_PERCENT:.1f}%\n"
                    f"💡 حداقل سود قابل‌اعتنا: "
                    f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان\n\n"
                    "از این مقدار برای تشخیص فرصت‌های واجد شرایط "
                    "و ارسال هشدار استفاده می‌شود.",
                    alert_threshold_keyboard()
                )

            else:

                answer_callback_query(
                    callback_id,
                    "حد هشدار نامعتبر است."
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

        waiting_for_custom_capital = False
        waiting_for_custom_alert_threshold = False

        send_main_menu()

        return

    if text in (
        "/capital",
        "موجودی",
        "انتخاب موجودی"
    ):

        waiting_for_custom_capital = False
        waiting_for_custom_alert_threshold = False

        send_capital_menu()

        return

    if text in (
        "/alert",
        "حد هشدار",
        "تنظیم حد هشدار"
    ):

        waiting_for_custom_capital = False
        waiting_for_custom_alert_threshold = False

        send_alert_threshold_menu()

        return

    if text in (
        "/status",
        "وضعیت"
    ):

        waiting_for_custom_capital = False
        waiting_for_custom_alert_threshold = False

        send_current_status_message()

        return

    if text in (
        "/history",
        "تاریخچه"
    ):

        waiting_for_custom_capital = False
        waiting_for_custom_alert_threshold = False

        send_history_menu()

        return

    if waiting_for_custom_alert_threshold:

        normalized = normalize_digits(
            text
        )

        normalized = (
            normalized
            .replace(",", ".")
            .replace("٬", ".")
            .replace("٫", ".")
            .replace("%", "")
            .replace("٪", "")
            .replace(" ", "")
        )

        try:

            threshold = float(
                normalized
            )

        except Exception:

            threshold = 0

        if (
            threshold <= 0
            or threshold > 100
        ):

            send_telegram(
                "❌ حد هشدار نامعتبر است.\n\n"
                "یک عدد بین ۰ و ۱۰۰ درصد ارسال کنید.\n\n"
                "مثال:\n"
                "1.2"
            )

            return

        set_alert_threshold(
            threshold
        )

        waiting_for_custom_alert_threshold = False

        send_telegram(
            "✅ حد هشدار با موفقیت ثبت شد.\n\n"
            f"🎯 حد هشدار جدید: "
            f"{MIN_PROFIT_PERCENT:.1f}%\n"
            f"💡 حداقل سود قابل‌اعتنا: "
            f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان\n\n"
            "از این مقدار برای هشدارهای ربات استفاده می‌شود.",
            alert_threshold_keyboard()
        )

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

        waiting_for_custom_capital = False

        send_telegram(
            "✅ موجودی با موفقیت ثبت شد.\n\n"
            f"💰 {format_toman(amount)} تومان\n\n"
            f"🎯 حد هشدار فعلی: "
            f"{MIN_PROFIT_PERCENT:.1f}%\n"
            f"💡 حداقل سود قابل‌اعتنا: "
            f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان\n\n"
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

    if (
        route["net_profit"]
        < MIN_NET_PROFIT_TOMAN
    ):
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

        f"🎯 حد هشدار: "
        f"{MIN_PROFIT_PERCENT:.1f}%\n"

        f"💡 حداقل سود خالص: "
        f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان\n"

        f"{format_profit_line(route['net_profit'])}\n"

        f"{format_profit_percent_line(route['profit_percent'])}\n"

        f"{format_orderbook_execution(route)}\n\n"

        f"{build_trade_details_table(route)}\n\n"

        f"💳 کارمزد خرید: "
        f"{route['buy_fee'] * 100:.1f}% "
        f"= {format_usdt(route['buy_fee_amount_usdt'])} تتر\n"

        f"💳 کارمزد فروش: "
        f"{route['sell_fee'] * 100:.1f}% "
        f"= {format_toman(route['sell_fee_amount_toman'])} تومان\n\n"

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


# ============================================================
# جزئیات خرید و فروش - مناسب موبایل
# ============================================================

def build_trade_details_table(
    route
):

    buy_exchange = route["buy_exchange"]
    sell_exchange = route["sell_exchange"]

    buy_amount = (
        f"{format_toman(route['spent'])} تومان"
    )

    sell_amount = (
        f"{format_usdt(route['usdt'])} تتر"
    )

    buy_levels = (
        f"{route['buy_orderbook_levels']} لول"
    )

    sell_levels = (
        f"{route['sell_orderbook_levels']} لول"
    )

    buy_average = (
        f"{format_toman(route['buy_price'])} تومان"
    )

    sell_average = (
        f"{format_toman(route['sell_price'])} تومان"
    )

    return (
        "📋 جزئیات خرید و فروش:\n\n"

        "📥 خرید\n"
        f"صرافی: {buy_exchange}\n"
        f"مبلغ: {buy_amount}\n"
        f"تعداد لول: {buy_levels}\n"
        f"میانگین: {buy_average}\n\n"

        "📤 فروش\n"
        f"صرافی: {sell_exchange}\n"
        f"مبلغ: {sell_amount}\n"
        f"تعداد لول: {sell_levels}\n"
        f"میانگین: {sell_average}"
    )


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
    ]

    if latest_routes:

        best = latest_routes[0]

        route_key = (
            f"{best['buy_exchange']}_"
            f"{best['sell_exchange']}"
        )

        history = analyze_route_history(
            route_key
        )

        if (
            best["net_profit"]
            >= MIN_NET_PROFIT_TOMAN
            and best["profit_percent"]
            >= MIN_PROFIT_PERCENT
            and best["execution_ratio"]
            >= MIN_EXECUTION_RATIO
        ):

            status_line = (
                "🚨 وضعیت: بهترین مسیر فعلی "
                "بعد از کارمزد سودده و واجد شرایط هشدار است."
            )

        elif (
            best["net_profit"]
            > 0
        ):

            status_line = (
                "🟡 وضعیت: بهترین مسیر فعلی "
                "سود دارد، اما هنوز به حد هشدار نرسیده."
            )

        else:

            status_line = (
                "🔴 وضعیت: بهترین مسیر فعلی "
                "پس از کارمزد زیان‌ده است."
            )

        lines.extend([

            "",

            status_line,

            "",

            "💰 موجودی:",

            (
                f"{format_toman(selected_capital_toman)} تومان"
                if selected_capital_toman is not None
                else "❌ هنوز انتخاب نشده"
            ),

            f"🎯 حد هشدار: "
            f"{MIN_PROFIT_PERCENT:.1f}%",

            f"💡 حداقل سود قابل‌اعتنا: "
            f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان",

            "",

            "🏆 بهترین مسیر فعلی:",

            f"{best['buy_exchange']} → "
            f"{best['sell_exchange']}",

            "",

            format_profit_line(
                best["net_profit"]
            ),

            format_profit_percent_line(
                best["profit_percent"]
            ),

            format_orderbook_execution(best),

            f"💰 مقدار قابل خرید با مبلغ موجودی: "
            f"{format_usdt(best['usdt'])} تتر",

            "",

            build_trade_details_table(
                best
            ),

            "",

            "💳 کارمزد:",

            (
                f"• خرید: "
                f"{best['buy_fee'] * 100:.1f}% "
                f"= {format_usdt(best['buy_fee_amount_usdt'])} تتر"
            ),

            (
                f"• فروش: "
                f"{best['sell_fee'] * 100:.1f}% "
                f"= {format_toman(best['sell_fee_amount_toman'])} تومان"
            ),

            "",

            "🔁 سابقه مسیر:",

            f"• مشاهده: "
            f"{history['observations']}",

            f"• سودده: "
            f"{history['positive_observations']}",

            f"• واجد شرایط: "
            f"{history['qualified_observations']}",

            f"• میانگین سود/زیان: "
            f"{format_percent(history['average_profit_percent'])}",

            "",

            "🏆 سه مسیر برتر فعلی:",
        ])

        for index, route in enumerate(
            latest_routes[:3],
            start=1
        ):

            lines.extend([

                "",

                f"{index}. "
                f"{route['buy_exchange']} → "
                f"{route['sell_exchange']}",

                format_profit_line(
                    route["net_profit"]
                ),

                format_profit_percent_line(
                    route["profit_percent"]
                ),

            ])

    else:

        lines.extend([

            "",

            "🔴 وضعیت: فعلاً مسیر قابل محاسبه‌ای وجود ندارد.",

            "",

            "💰 موجودی:",

            (
                f"{format_toman(selected_capital_toman)} تومان"
                if selected_capital_toman is not None
                else "❌ هنوز انتخاب نشده"
            ),

            f"🎯 حد هشدار: "
            f"{MIN_PROFIT_PERCENT:.1f}%",

            f"💡 حداقل سود قابل‌اعتنا: "
            f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان",

            "",

            "ℹ️ فعلاً مسیر قابل محاسبه‌ای وجود ندارد.",
        ])

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

            lines.extend([

                f"{exchange}:",

                (
                    f"قیمت خرید (Ask): "
                    f"{format_toman(ask)}"
                ),

                (
                    f"قیمت فروش (Bid): "
                    f"{format_toman(bid)}"
                ),

            ])

        else:

            lines.extend([

                f"{exchange}:",

                "❌ Order Book نامعتبر",

            ])

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
                    {
                        "text": "🎯 تغییر حد هشدار",
                        "callback_data":
                            "MENU:ALERT",
                    },
                ],

                [
                    {
                        "text": "📚 تاریخچه",
                        "callback_data":
                            "MENU:HISTORY",
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

        f"🎯 حد هشدار: "
        f"{format_percent(MIN_PROFIT_PERCENT)}\n"

        f"💡 حداقل سود قابل‌اعتنا: "
        f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان\n"

        f"⏱️ فاصله بررسی: "
        f"{CHECK_INTERVAL_SECONDS} ثانیه\n"

        f"💳 نوع کارمزد: "
        f"{ORDER_TYPE}\n\n"

        f"💰 موجودی فعلی: "
        f"{format_toman(selected_capital_toman)} تومان\n\n"

        "📊 گزارش وضعیت: هر دو ساعت\n"

        "🌙 گزارش دوره‌ای: "
        "23:00 تا 08:00 متوقف\n\n"

        f"📚 تاریخچه ذخیره‌شده: "
        f"{len(persistent_history)} رکورد\n\n"

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
        f"🎯 حد هشدار: "
        f"{format_percent(MIN_PROFIT_PERCENT)}"
    )

    print(
        f"💡 حداقل سود قابل‌اعتنا: "
        f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان"
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

    # ========================================================
    # بارگذاری آمار و تاریخچه
    # ========================================================

    stats = load_stats()

    load_persistent_history()

    print(
        f"📚 تاریخچه دائمی: "
        f"{len(persistent_history)} رکورد"
    )

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
            save_persistent_history()

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
                    f"🎯 حد هشدار: "
                    f"{MIN_PROFIT_PERCENT:.1f}%"
                )

                print(
                    f"💡 حداقل سود قابل‌اعتنا: "
                    f"{format_toman(MIN_NET_PROFIT_TOMAN)} تومان"
                )

                print(
                    format_profit_line(
                        best["net_profit"]
                    )
                )

                print(
                    format_profit_percent_line(
                        best["profit_percent"]
                    )
                )

                print(
                    format_orderbook_execution(best)
                )

                print(
                    f"💰 مقدار قابل خرید با مبلغ موجودی: "
                    f"{format_usdt(best['usdt'])} تتر"
                )

                print()

                print(
                    build_trade_details_table(
                        best
                    )
                )

                # ====================================================
                # ثبت تاریخچه دائمی
                # ====================================================

                history_saved = (
                    save_history_record(
                        best
                    )
                )

                if history_saved:

                    print(
                        "📚 فرصت واجد شرایط "
                        "در تاریخچه ذخیره شد."
                    )

                if (
                    best["net_profit"]
                    >= MIN_NET_PROFIT_TOMAN
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

        save_persistent_history()

    except Exception as e:

        print()

        print(
            f"❌ خطای جدی: {e}"
        )

        save_persistent_history()

        raise
