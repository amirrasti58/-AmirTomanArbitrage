"""
============================================================
ARBITRAGE BOT
Wallex + BitPin + Ramzinex + Phinix + Exir + Sarrafex

USDT / TOMAN
MONITORING ONLY
NO REAL TRADES
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

MIN_PROFIT_PERCENT = 1.5
CHECK_INTERVAL_SECONDS = 10
ALERT_COOLDOWN_SECONDS = 60

MAX_RUNTIME_SECONDS = 20700

ORDER_TYPE = "taker"

MIN_EXECUTION_RATIO = 0.80

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


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
# CAPITAL
# ============================================================

CAPITAL_OPTIONS = {
    "50M": 50_000_000,
    "100M": 100_000_000,
    "200M": 200_000_000,
    "500M": 500_000_000,
    "1B": 1_000_000_000,
}

selected_capital_toman = None


# ============================================================
# STATE
# ============================================================

start_time = time.time()

last_alert_time = {}

total_checks = 0
total_alerts = 0

best_route_current = None

opportunity_history = []

MAX_HISTORY_ITEMS = 60


exchange_status = {
    "Wallex": False,
    "BitPin": False,
    "Ramzinex": False,
    "Phinix": False,
    "Exir": False,
    "Sarrafex": False,
}


# ============================================================
# FORMATTERS
# ============================================================

def format_toman(value):
    if value is None:
        return "0"

    return f"{int(round(value)):,}"


def format_toman_signed(value):
    if value is None:
        return "0"

    value = int(round(value))

    if value < 0:
        return f"{abs(value):,}-"

    return f"{value:,}"


def format_percent(value):
    if value is None:
        return "0.0%"

    value = round(float(value), 1)

    if value < 0:
        return f"{abs(value):.1f}%-"

    return f"{value:.1f}%"


def now_tehran():
    return datetime.now()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text, reply_markup=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials are not configured.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print(
            "Telegram error:",
            response.status_code,
            response.text[:300],
        )

    except Exception as exc:
        print("Telegram exception:", exc)

    return False


# ============================================================
# TELEGRAM KEYBOARDS
# ============================================================

def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📊 وضعیت",
                    "callback_data": "MENU:STATUS",
                },
                {
                    "text": "💰 انتخاب موجودی",
                    "callback_data": "MENU:CAPITAL",
                },
            ]
        ]
    }


def capital_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "50 میلیون",
                    "callback_data": "CAPITAL:50000000",
                },
                {
                    "text": "100 میلیون",
                    "callback_data": "CAPITAL:100000000",
                },
            ],
            [
                {
                    "text": "200 میلیون",
                    "callback_data": "CAPITAL:200000000",
                },
                {
                    "text": "500 میلیون",
                    "callback_data": "CAPITAL:500000000",
                },
            ],
            [
                {
                    "text": "1 میلیارد",
                    "callback_data": "CAPITAL:1000000000",
                }
            ],
            [
                {
                    "text": "↩️ برگشت",
                    "callback_data": "MENU:MAIN",
                }
            ],
        ]
    }


def status_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "💰 تغییر موجودی",
                    "callback_data": "MENU:CAPITAL",
                }
            ],
            [
                {
                    "text": "↩️ برگشت",
                    "callback_data": "MENU:MAIN",
                }
            ],
        ]
    }


# ============================================================
# TELEGRAM MENUS
# ============================================================

def send_main_menu():
    text = (
        "🤖 ربات آربیتراژ\n\n"
        "یکی از گزینه‌های زیر را انتخاب کنید:"
    )

    return send_telegram(
        text,
        main_menu_keyboard(),
    )


def send_capital_menu():
    return send_telegram(
        "💰 انتخاب موجودی\n\n"
        "مبلغ کل سرمایه‌ای که می‌خواهید ربات بر اساس آن\n"
        "محاسبات Order Book و سود را انجام دهد انتخاب کنید.\n\n",
        capital_keyboard(),
    )


def send_status_menu():
    return send_telegram(
        build_current_status_message(),
        status_keyboard(),
    )


# ============================================================
# TELEGRAM CALLBACK ANSWER
# ============================================================

def answer_callback_query(callback_query_id, text=""):
    if not TELEGRAM_BOT_TOKEN:
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    )

    try:
        requests.post(
            url,
            json={
                "callback_query_id": callback_query_id,
                "text": text,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except Exception:
        pass


def edit_telegram_message(
    chat_id,
    message_id,
    text,
    reply_markup=None,
):
    if not TELEGRAM_BOT_TOKEN:
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/editMessageText"
    )

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        return response.ok

    except Exception:
        return False


# ============================================================
# EXCHANGE ORDER BOOKS
# ============================================================

def normalize_orders(orders, side):
    result = []

    for order in orders:
        try:
            if isinstance(order, dict):
                price = (
                    order.get("price")
                    or order.get("p")
                    or order.get("rate")
                )

                volume = (
                    order.get("amount")
                    or order.get("volume")
                    or order.get("quantity")
                    or order.get("q")
                )

            elif isinstance(order, (list, tuple)):
                price = order[0]
                volume = order[1]

            else:
                continue

            price = float(price)
            volume = float(volume)

            if price <= 0 or volume <= 0:
                continue

            result.append(
                {
                    "price": price,
                    "volume": volume,
                }
            )

        except Exception:
            continue

    if side == "asks":
        result.sort(key=lambda x: x["price"])

    else:
        result.sort(
            key=lambda x: x["price"],
            reverse=True,
        )

    return result[:ORDERBOOK_LEVELS]


# ============================================================
# WALLEX
# ============================================================

def get_wallex_orderbook():
    url = "https://api.wallex.ir/v1/depth?symbol=USDTTMN"

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        result = data.get("result", data)

        asks = (
            result.get("asks", [])
            if isinstance(result, dict)
            else []
        )

        bids = (
            result.get("bids", [])
            if isinstance(result, dict)
            else []
        )

        asks = normalize_orders(asks, "asks")
        bids = normalize_orders(bids, "bids")

        if not asks or not bids:
            return None

        return {
            "exchange": "Wallex",
            "asks": asks,
            "bids": bids,
        }

    except Exception as exc:
        print("Wallex error:", exc)
        return None


# ============================================================
# BITPIN
# ============================================================

def get_bitpin_orderbook():
    urls = [
        "https://api.bitpin.market/api/v1/mth/orderbook/USDT_IRT/",
        "https://api.bitpin.org/api/v1/mth/orderbook/USDT_IRT/",
    ]

    for url in urls:
        try:
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 200:
                continue

            data = response.json()

            asks = []
            bids = []

            if isinstance(data, dict):
                asks = data.get("asks", [])
                bids = data.get("bids", [])

                if not asks:
                    asks = data.get("ask", [])

                if not bids:
                    bids = data.get("bid", [])

            asks = normalize_orders(asks, "asks")
            bids = normalize_orders(bids, "bids")

            if asks and bids:
                return {
                    "exchange": "BitPin",
                    "asks": asks,
                    "bids": bids,
                }

        except Exception as exc:
            print("BitPin error:", exc)

    return None


# ============================================================
# RAMZINEX
# ============================================================

def get_ramzinex_orderbook():
    urls = [
        (
            "https://publicapi.ramzinex.com/"
            "exchange/api/v1.0/exchange/"
            "orderbooks/11/buys_sells"
        ),
        (
            "https://publicapi.ramzinex.com/"
            "exchange/api/v1.0/exchange/"
            "orderbooks/11"
        ),
    ]

    for url in urls:
        try:
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 200:
                continue

            data = response.json()

            asks = []
            bids = []

            if isinstance(data, dict):
                asks = (
                    data.get("asks")
                    or data.get("sells")
                    or data.get("sell_orders")
                    or []
                )

                bids = (
                    data.get("bids")
                    or data.get("buys")
                    or data.get("buy_orders")
                    or []
                )

                result = data.get("data")

                if isinstance(result, dict):
                    if not asks:
                        asks = (
                            result.get("asks")
                            or result.get("sells")
                            or []
                        )

                    if not bids:
                        bids = (
                            result.get("bids")
                            or result.get("buys")
                            or []
                        )

            asks = normalize_orders(asks, "asks")
            bids = normalize_orders(bids, "bids")

            # Ramzinex pair 11 is IRR.
            # Convert IRR to Toman.
            for order in asks:
                order["price"] /= 10

            for order in bids:
                order["price"] /= 10

            if asks and bids:
                return {
                    "exchange": "Ramzinex",
                    "asks": asks,
                    "bids": bids,
                }

        except Exception as exc:
            print("Ramzinex error:", exc)

    return None


# ============================================================
# OTHER EXCHANGES
# ============================================================

def get_phinix_orderbook():
    exchange_status["Phinix"] = False
    return None


def get_exir_orderbook():
    exchange_status["Exir"] = False
    return None


def get_sarrafex_orderbook():
    exchange_status["Sarrafex"] = False
    return None


# ============================================================
# FETCH ALL ORDER BOOKS
# ============================================================

def fetch_all_orderbooks():
    books = {}

    functions = {
        "Wallex": get_wallex_orderbook,
        "BitPin": get_bitpin_orderbook,
        "Ramzinex": get_ramzinex_orderbook,
        "Phinix": get_phinix_orderbook,
        "Exir": get_exir_orderbook,
        "Sarrafex": get_sarrafex_orderbook,
    }

    for name, function in functions.items():
        try:
            book = function()

            if book:
                books[name] = book
                exchange_status[name] = True
            else:
                exchange_status[name] = False

        except Exception as exc:
            print(f"{name} error:", exc)
            exchange_status[name] = False

    return books


# ============================================================
# SIMULATE BUY
# ============================================================

def simulate_buy(asks, toman_amount):
    remaining_toman = toman_amount
    usdt_bought = 0.0
    spent_toman = 0.0

    for order in asks:
        price = order["price"]
        volume = order["volume"]

        if remaining_toman <= 0:
            break

        possible_usdt = remaining_toman / price

        buy_usdt = min(
            possible_usdt,
            volume,
        )

        cost = buy_usdt * price

        usdt_bought += buy_usdt
        spent_toman += cost
        remaining_toman -= cost

    execution_ratio = (
        spent_toman / toman_amount
        if toman_amount > 0
        else 0
    )

    return {
        "usdt": usdt_bought,
        "spent": spent_toman,
        "execution_ratio": execution_ratio,
    }


# ============================================================
# SIMULATE SELL
# ============================================================

def simulate_sell(bids, usdt_amount):
    remaining_usdt = usdt_amount
    toman_received = 0.0
    sold_usdt = 0.0

    for order in bids:
        price = order["price"]
        volume = order["volume"]

        if remaining_usdt <= 0:
            break

        sell_usdt = min(
            remaining_usdt,
            volume,
        )

        revenue = sell_usdt * price

        toman_received += revenue
        sold_usdt += sell_usdt
        remaining_usdt -= sell_usdt

    execution_ratio = (
        sold_usdt / usdt_amount
        if usdt_amount > 0
        else 0
    )

    return {
        "usdt": sold_usdt,
        "received": toman_received,
        "execution_ratio": execution_ratio,
    }


# ============================================================
# CALCULATE ROUTE
# ============================================================

def calculate_route(
    buy_exchange,
    sell_exchange,
    buy_book,
    sell_book,
    capital_toman,
):
    buy_fee = FEES[buy_exchange][ORDER_TYPE]
    sell_fee = FEES[sell_exchange][ORDER_TYPE]

    buy_result = simulate_buy(
        buy_book["asks"],
        capital_toman,
    )

    if buy_result["execution_ratio"] <= 0:
        return None

    usdt_after_buy_fee = (
        buy_result["usdt"] * (1 - buy_fee)
    )

    sell_result = simulate_sell(
        sell_book["bids"],
        usdt_after_buy_fee,
    )

    if sell_result["execution_ratio"] <= 0:
        return None

    toman_after_sell_fee = (
        sell_result["received"]
        * (1 - sell_fee)
    )

    net_profit = (
        toman_after_sell_fee
        - buy_result["spent"]
    )

    profit_percent = (
        net_profit
        / buy_result["spent"]
        * 100
        if buy_result["spent"] > 0
        else 0
    )

    execution_ratio = min(
        buy_result["execution_ratio"],
        sell_result["execution_ratio"],
    )

    return {
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,
        "buy_price": (
            buy_result["spent"]
            / buy_result["usdt"]
            if buy_result["usdt"] > 0
            else 0
        ),
        "sell_price": (
            sell_result["received"]
            / sell_result["usdt"]
            if sell_result["usdt"] > 0
            else 0
        ),
        "usdt_amount": sell_result["usdt"],
        "net_profit": net_profit,
        "profit_percent": profit_percent,
        "execution_ratio": execution_ratio,
    }


# ============================================================
# FIND BEST ROUTE
# ============================================================

def find_best_route(books, capital_toman):
    routes = []

    exchange_names = list(books.keys())

    for buy_exchange in exchange_names:
        for sell_exchange in exchange_names:

            if buy_exchange == sell_exchange:
                continue

            route = calculate_route(
                buy_exchange,
                sell_exchange,
                books[buy_exchange],
                books[sell_exchange],
                capital_toman,
            )

            if route:
                routes.append(route)

    if not routes:
        return None, []

    routes.sort(
        key=lambda x: x["profit_percent"],
        reverse=True,
    )

    return routes[0], routes


# ============================================================
# OPPORTUNITY HISTORY
# ============================================================

def update_opportunity_history(route):
    if not route:
        return

    if route["execution_ratio"] < MIN_EXECUTION_RATIO:
        return

    opportunity_history.append(
        {
            "time": datetime.now(),
            "buy_exchange": route["buy_exchange"],
            "sell_exchange": route["sell_exchange"],
            "profit": route["net_profit"],
            "profit_percent": route["profit_percent"],
            "execution_ratio": route["execution_ratio"],
        }
    )

    if len(opportunity_history) > MAX_HISTORY_ITEMS:
        del opportunity_history[
            0:
        : len(opportunity_history) - MAX_HISTORY_ITEMS
        ]


# ============================================================
# ARBITRAGE ALERT
# ============================================================

def send_arbitrage_alert(route):
    global total_alerts

    if not route:
        return False

    if route["execution_ratio"] < MIN_EXECUTION_RATIO:
        return False

    if route["net_profit"] <= 0:
        return False

    if route["profit_percent"] < MIN_PROFIT_PERCENT:
        return False

    route_key = (
        f"{route['buy_exchange']}_"
        f"{route['sell_exchange']}"
    )

    now = time.time()

    previous = last_alert_time.get(
        route_key,
        0,
    )

    if now - previous < ALERT_COOLDOWN_SECONDS:
        return False

    text = (
        "🚨 فرصت آربیتراژ\n\n"
        f"🟢 خرید: {route['buy_exchange']}\n"
        f"🔴 فروش: {route['sell_exchange']}\n\n"
        f"💵 قیمت خرید: "
        f"{format_toman(route['buy_price'])} تومان\n"
        f"💵 قیمت فروش: "
        f"{format_toman(route['sell_price'])} تومان\n\n"
        f"💰 سود خالص: "
        f"{format_toman_signed(route['net_profit'])} تومان\n"
        f"📈 سود: "
        f"{format_percent(route['profit_percent'])}\n"
        f"📦 اجرا: "
        f"{format_percent(route['execution_ratio'] * 100)}\n"
    )

    success = send_telegram(text)

    if success:
        last_alert_time[route_key] = now
        total_alerts += 1

    return success


# ============================================================
# CURRENT STATUS MESSAGE
# ============================================================

def build_current_status_message():
    now = datetime.now()

    lines = [
        "📊 وضعیت ربات آربیتراژ",
        "",
        "💰 موجودی:",
        (
            f"{format_toman(selected_capital_toman)} تومان"
            if selected_capital_toman is not None
            else "❌ هنوز انتخاب نشده"
        ),
        "",
        "🏆 بهترین مسیر فعلی:",
    ]

    if best_route_current:
        route = best_route_current

        lines.extend(
            [
                (
                    f"🟢 خرید از {route['buy_exchange']}"
                ),
                (
                    f"🔴 فروش در {route['sell_exchange']}"
                ),
                (
                    f"💵 خرید: "
                    f"{format_toman(route['buy_price'])} تومان"
                ),
                (
                    f"💵 فروش: "
                    f"{format_toman(route['sell_price'])} تومان"
                ),
                (
                    f"💰 سود خالص: "
                    f"{format_toman_signed(route['net_profit'])} تومان"
                ),
                (
                    f"📈 سود: "
                    f"{format_percent(route['profit_percent'])}"
                ),
                (
                    f"📦 اجرای سفارش: "
                    f"{format_percent(route['execution_ratio'] * 100)}"
                ),
            ]
        )

    else:
        lines.append(
            "❌ هنوز مسیر قابل محاسبه‌ای وجود ندارد."
        )

    lines.extend(
        [
            "",
            "🏦 وضعیت صرافی‌ها:",
        ]
    )

    for name, status in exchange_status.items():
        icon = "🟢" if status else "🔴"

        lines.append(
            f"{icon} {name}"
        )

    lines.extend(
        [
            "",
            "📊 آمار:",
            f"🔄 بررسی‌ها: {total_checks}",
            f"🚨 هشدارها: {total_alerts}",
            f"📚 فرصت‌های ثبت‌شده: "
            f"{len(opportunity_history)}",
            "",
            f"🎯 حد هشدار: "
            f"{MIN_PROFIT_PERCENT:.1f}%",
        ]
    )

    if best_route_current:
        distance = (
            MIN_PROFIT_PERCENT
            - best_route_current["profit_percent"]
        )

        lines.extend(
            [
                f"📉 فاصله تا حد هشدار: "
                f"{format_percent(distance)}",
            ]
        )

    lines.extend(
        [
            "",
            f"🕐 زمان: "
            f"{now.strftime('%Y-%m-%d %H:%M:%S')} تهران",
        ]
    )

    return "\n".join(lines)


# ============================================================
# STARTUP MESSAGE
# ============================================================

def send_startup_message():
    text = (
        "🤖 ربات آربیتراژ شروع شد.\n\n"
        "📡 فقط مانیتورینگ و شبیه‌سازی\n"
        "❌ معامله واقعی انجام نمی‌شود.\n\n"
        "برای انتخاب موجودی و مشاهده وضعیت "
        "از منوی زیر استفاده کنید."
    )

    send_telegram(
        text,
        main_menu_keyboard(),
    )


# ============================================================
# PERIODIC REPORT
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


last_periodic_report_key = None


def send_periodic_report():
    global last_periodic_report_key

    now = datetime.now()

    current_time = now.strftime("%H:%M")

    if current_time not in REPORT_TIMES:
        return

    report_key = now.strftime(
        "%Y-%m-%d %H:%M"
    )

    if report_key == last_periodic_report_key:
        return

    last_periodic_report_key = report_key

    send_telegram(
        build_current_status_message()
    )


# ============================================================
# TELEGRAM POLLING
# ============================================================

def handle_callback_query(callback):
    global selected_capital_toman

    callback_id = callback.get("id")
    data = callback.get("data", "")

    message = callback.get("message", {})

    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    message_id = message.get("message_id")

    if str(TELEGRAM_CHAT_ID) != chat_id:
        answer_callback_query(
            callback_id,
            "دسترسی مجاز نیست.",
        )
        return

    if data == "MENU:MAIN":
        answer_callback_query(
            callback_id,
            "منوی اصلی",
        )

        edit_telegram_message(
            chat_id,
            message_id,
            (
                "🤖 ربات آربیتراژ\n\n"
                "یکی از گزینه‌های زیر را انتخاب کنید:"
            ),
            main_menu_keyboard(),
        )

        return

    if data == "MENU:CAPITAL":
        answer_callback_query(
            callback_id,
            "انتخاب موجودی",
        )

        edit_telegram_message(
            chat_id,
            message_id,
            (
                "💰 انتخاب موجودی\n\n"
                "مبلغ کل سرمایه‌ای که می‌خواهید "
                "ربات بر اساس آن محاسبات را انجام دهد "
                "انتخاب کنید."
            ),
            capital_keyboard(),
        )

        return

    if data == "MENU:STATUS":
        answer_callback_query(
            callback_id,
            "وضعیت فعلی",
        )

        edit_telegram_message(
            chat_id,
            message_id,
            build_current_status_message(),
            status_keyboard(),
        )

        return

    if data.startswith("CAPITAL:"):
        try:
            amount = int(
                data.split(":", 1)[1]
            )

            selected_capital_toman = amount

            answer_callback_query(
                callback_id,
                "موجودی انتخاب شد.",
            )

            edit_telegram_message(
                chat_id,
                message_id,
                (
                    "✅ موجودی انتخاب شد.\n\n"
                    f"💰 {format_toman(amount)} تومان\n\n"
                    "این مبلغ از این لحظه "
                    "برای محاسبات آربیتراژ استفاده می‌شود."
                ),
                status_keyboard(),
            )

        except Exception:
            answer_callback_query(
                callback_id,
                "مقدار نامعتبر است.",
            )


def handle_telegram_message(message):
    global selected_capital_toman

    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    if str(TELEGRAM_CHAT_ID) != chat_id:
        return

    text = (
        message.get("text", "")
        .strip()
        .lower()
    )

    if text in ["/start", "/menu"]:
        send_main_menu()

    elif text == "/status":
        send_status_menu()

    elif text == "/capital":
        send_capital_menu()


def telegram_polling_loop():
    offset = None

    while True:
        try:
            url = (
                f"https://api.telegram.org/bot"
                f"{TELEGRAM_BOT_TOKEN}/getUpdates"
            )

            params = {
                "timeout": 20,
            }

            if offset is not None:
                params["offset"] = offset

            response = requests.get(
                url,
                params=params,
                timeout=30,
            )

            if not response.ok:
                time.sleep(3)
                continue

            data = response.json()

            updates = data.get(
                "result",
                [],
            )

            for update in updates:
                offset = update["update_id"] + 1

                callback = update.get(
                    "callback_query"
                )

                if callback:
                    handle_callback_query(
                        callback
                    )

                message = update.get(
                    "message"
                )

                if message:
                    handle_telegram_message(
                        message
                    )

        except Exception as exc:
            print(
                "Telegram polling error:",
                exc,
            )

            time.sleep(3)


# ============================================================
# STATUS REPORT THREAD
# ============================================================

def status_loop():
    while True:
        try:
            send_periodic_report()
        except Exception as exc:
            print(
                "Periodic report error:",
                exc,
            )

        time.sleep(30)


# ============================================================
# MAIN MONITORING LOOP
# ============================================================

def monitoring_loop():
    global total_checks
    global best_route_current

    started_at = time.time()

    while True:
        elapsed = (
            time.time()
            - started_at
        )

        if elapsed >= MAX_RUNTIME_SECONDS:
            print(
                "Safe runtime reached. "
                "Stopping before GitHub Actions limit."
            )

            send_telegram(
                "⏹️ ربات برای جلوگیری از "
                "رسیدن به محدودیت GitHub Actions "
                "به‌صورت ایمن متوقف شد."
            )

            break

        if selected_capital_toman is None:
            print(
                "Capital has not been selected yet."
            )

            time.sleep(
                CHECK_INTERVAL_SECONDS
            )

            continue

        total_checks += 1

        print()
        print("=" * 60)
        print(
            "CHECK",
            total_checks,
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        )
        print(
            "Capital:",
            format_toman(
                selected_capital_toman
            ),
        )

        books = fetch_all_orderbooks()

        print(
            "Valid order books:",
            len(books),
        )

        if len(books) >= 2:
            best_route, routes = find_best_route(
                books,
                selected_capital_toman,
            )

            best_route_current = best_route

            if best_route:
                update_opportunity_history(
                    best_route
                )

                print(
                    "Best route:",
                    best_route["buy_exchange"],
                    "->",
                    best_route["sell_exchange"],
                )

                print(
                    "Net profit:",
                    format_toman_signed(
                        best_route["net_profit"]
                    ),
                    "Toman",
                )

                print(
                    "Profit:",
                    format_percent(
                        best_route["profit_percent"]
                    ),
                )

                print(
                    "Execution:",
                    format_percent(
                        best_route["execution_ratio"]
                        * 100
                    ),
                )

                send_arbitrage_alert(
                    best_route
                )

        else:
            best_route_current = None

            print(
                "Not enough valid order books."
            )

        time.sleep(
            CHECK_INTERVAL_SECONDS
        )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("ARBITRAGE BOT STARTED")
    print("MONITORING ONLY - NO REAL TRADES")
    print("=" * 60)

    send_startup_message()

    import threading

    telegram_thread = threading.Thread(
        target=telegram_polling_loop,
        daemon=True,
    )

    telegram_thread.start()

    status_thread = threading.Thread(
        target=status_loop,
        daemon=True,
    )

    status_thread.start()

    monitoring_loop()


if __name__ == "__main__":
    main()
