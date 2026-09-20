"""
============================================================
ARBITRAGE BOT
Wallex + BitPin + Ramzinex

Order Book
Fees
Net Profit
Telegram Alerts
Single-run mode (designed to be triggered on a schedule by GitHub Actions cron)
============================================================
"""

import os
from datetime import datetime

import requests


# ============================================================
# SETTINGS
# ============================================================

REQUEST_TIMEOUT = 15

# تعداد لایه‌های Order Book
ORDERBOOK_LEVELS = 20

# مبلغ شبیه‌سازی معامله
TRADE_AMOUNT_TOMAN = 50_000_000

# حداقل درصد سود خالص برای ارسال هشدار
MIN_PROFIT_PERCENT = float(
    os.environ.get("MIN_SPREAD_PERCENT", "0.5")
)


# ============================================================
# TELEGRAM SETTINGS
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# ============================================================
# EXCHANGE FEES
# ============================================================

EXCHANGE_FEES = {
    "Wallex": {"maker": 0.0025, "taker": 0.0030},
    "BitPin": {"maker": 0.0002, "taker": 0.0005},
    "Ramzinex": {"maker": 0.0020, "taker": 0.0025},
}

# برای آربیتراژ سریع
ORDER_TYPE = "taker"


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_float(value):
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def extract_price(order):
    if isinstance(order, dict):
        return safe_float(order.get("price") or order.get("rate"))
    if isinstance(order, (list, tuple)) and len(order) > 0:
        return safe_float(order[0])
    return None


def extract_volume(order):
    if isinstance(order, dict):
        return safe_float(
            order.get("quantity")
            or order.get("amount")
            or order.get("volume")
            or order.get("qty")
        )
    if isinstance(order, (list, tuple)) and len(order) > 1:
        return safe_float(order[1])
    return None


def normalize_orders(orders, side):
    normalized = []

    if not isinstance(orders, list):
        return normalized

    for order in orders:
        price = extract_price(order)
        volume = extract_volume(order)

        if price is not None and volume is not None and price > 0 and volume > 0:
            normalized.append({"price": price, "volume": volume})

    if side == "ask":
        normalized.sort(key=lambda x: x["price"])
    elif side == "bid":
        normalized.sort(key=lambda x: x["price"], reverse=True)

    return normalized[:ORDERBOOK_LEVELS]


def create_market_data(exchange, asks, bids):
    return {
        "exchange": exchange,
        "asks": asks,
        "bids": bids,
        "timestamp": datetime.now().isoformat(),
    }


def get_exchange_fee(exchange):
    exchange_data = EXCHANGE_FEES.get(exchange)
    if not exchange_data:
        return 0.0
    return exchange_data.get(ORDER_TYPE, 0.0)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(text):
    print()
    print("=" * 60)
    print("TELEGRAM")
    print("=" * 60)

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM ERROR: BOT TOKEN IS EMPTY")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM ERROR: CHAT ID IS EMPTY")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=REQUEST_TIMEOUT,
        )
        print(f"HTTP STATUS: {response.status_code}")
        response.raise_for_status()
        data = response.json()

        if data.get("ok"):
            print("TELEGRAM SUCCESS: MESSAGE SENT")
            return True

        print(f"TELEGRAM ERROR: {data}")
        return False

    except Exception as e:
        print(f"TELEGRAM EXCEPTION: {e}")
        return False


# ============================================================
# WALLEX
# ============================================================

def get_wallex_market_data():
    try:
        url = "https://api.wallex.ir/v1/depth?symbol=USDTTMN"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        result = data.get("result", {})
        asks_raw = result.get("ask", [])
        bids_raw = result.get("bid", [])

        asks = normalize_orders(asks_raw, "ask")
        bids = normalize_orders(bids_raw, "bid")

        if not asks or not bids:
            print("ERROR | Wallex Order Book not found")
            return None

        return create_market_data("Wallex", asks, bids)

    except Exception as e:
        print(f"ERROR | Wallex | {e}")
        return None


# ============================================================
# BITPIN
# ============================================================

def get_bitpin_orderbook():
    candidate_urls = [
        "https://api.bitpin.market/v1/mth/orderbook/USDT_IRT/",
        "https://api.bitpin.market/api/v1/mth/orderbook/USDT_IRT/",
        "https://api.bitpin.org/api/v1/mth/orderbook/USDT_IRT/",
    ]

    last_error = None

    for url in candidate_urls:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict):
                return data

        except Exception as e:
            last_error = e

    print(f"ERROR | BitPin | {last_error}")
    return None


def get_bitpin_market_data():
    try:
        data = get_bitpin_orderbook()

        if not isinstance(data, dict):
            return None

        asks_raw = data.get("asks") or data.get("sell") or data.get("sells") or []
        bids_raw = data.get("bids") or data.get("buy") or data.get("buys") or []

        asks = normalize_orders(asks_raw, "ask")
        bids = normalize_orders(bids_raw, "bid")

        if not asks or not bids:
            print("ERROR | BitPin Order Book incomplete")
            return None

        return create_market_data("BitPin", asks, bids)

    except Exception as e:
        print(f"ERROR | BitPin | {e}")
        return None


# ============================================================
# RAMZINEX
# ============================================================

def get_ramzinex_pairs():
    try:
        url = "https://publicapi.ramzinex.com/exchange/api/v1.0/exchange/pairs"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            return data.get("data", [])
        if isinstance(data, list):
            return data
        return []

    except Exception as e:
        print(f"ERROR | Ramzinex pairs | {e}")
        return []


def get_ramzinex_usdt_pair():
    pairs = get_ramzinex_pairs()

    for pair in pairs:
        if not isinstance(pair, dict):
            continue

        base = pair.get("base_currency_symbol")
        quote = pair.get("quote_currency_symbol")

        if isinstance(base, dict):
            base = base.get("en") or base.get("symbol") or ""
        if isinstance(quote, dict):
            quote = quote.get("en") or quote.get("symbol") or ""

        base = str(base).upper()
        quote = str(quote).upper()

        if base == "USDT" and quote in ("IRT", "IRR", "TMN", "TOMAN"):
            return pair

    return None


def get_ramzinex_orderbook(pair_id):
    candidate_urls = [
        f"https://publicapi.ramzinex.com/exchange/api/v1.0/exchange/orderbooks/{pair_id}/buys_sells",
        f"https://publicapi.ramzinex.com/exchange/api/v1.0/exchange/orderbooks/{pair_id}",
    ]

    for url in candidate_urls:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception:
            continue

    return None


def get_ramzinex_market_data():
    try:
        pair = get_ramzinex_usdt_pair()

        if not pair:
            print("ERROR | Ramzinex USDT market not found")
            return None

        pair_id = pair.get("id") or pair.get("pair_id")

        if pair_id is None:
            print("ERROR | Ramzinex Pair ID not found")
            return None

        data = get_ramzinex_orderbook(pair_id)

        if not isinstance(data, dict):
            print("ERROR | Ramzinex Order Book not received")
            return None

        payload = data.get("data", data)

        asks_raw = payload.get("sells") or payload.get("asks") or payload.get("sell") or []
        bids_raw = payload.get("buys") or payload.get("bids") or payload.get("buy") or []

        asks = normalize_orders(asks_raw, "ask")
        bids = normalize_orders(bids_raw, "bid")

        if not asks or not bids:
            print("ERROR | Ramzinex Order Book incomplete")
            return None

        quote = pair.get("quote_currency_symbol", "")
        if isinstance(quote, dict):
            quote = quote.get("en", "")
        quote = str(quote).upper()

        # تبدیل ریال به تومان
        if quote == "IRR":
            for order in asks:
                order["price"] /= 10
            for order in bids:
                order["price"] /= 10

        return create_market_data("Ramzinex", asks, bids)

    except Exception as e:
        print(f"ERROR | Ramzinex | {e}")
        return None


# ============================================================
# BUY SIMULATION
# ============================================================

def simulate_buy_with_toman(asks, toman_amount):
    remaining_toman = float(toman_amount)

    total_usdt = 0.0
    total_spent = 0.0
    levels_used = 0

    for order in asks:
        if remaining_toman <= 0:
            break

        price = order["price"]
        available_usdt = order["volume"]
        full_cost = price * available_usdt

        if remaining_toman >= full_cost:
            total_usdt += available_usdt
            total_spent += full_cost
            remaining_toman -= full_cost
            levels_used += 1
        else:
            usdt_to_buy = remaining_toman / price
            total_usdt += usdt_to_buy
            total_spent += remaining_toman
            remaining_toman = 0
            levels_used += 1
            break

    if total_usdt <= 0:
        return None

    average_price = total_spent / total_usdt

    return {
        "spent_toman": total_spent,
        "remaining_toman": remaining_toman,
        "usdt_bought": total_usdt,
        "average_price": average_price,
        "levels_used": levels_used,
        "fully_filled": remaining_toman < 1,
    }


# ============================================================
# SELL SIMULATION
# ============================================================

def simulate_sell_usdt(bids, usdt_amount):
    remaining_usdt = float(usdt_amount)

    total_toman = 0.0
    total_usdt_sold = 0.0
    levels_used = 0

    for order in bids:
        if remaining_usdt <= 0:
            break

        price = order["price"]
        available_usdt = order["volume"]

        if remaining_usdt >= available_usdt:
            total_usdt_sold += available_usdt
            total_toman += available_usdt * price
            remaining_usdt -= available_usdt
            levels_used += 1
        else:
            total_usdt_sold += remaining_usdt
            total_toman += remaining_usdt * price
            remaining_usdt = 0
            levels_used += 1
            break

    if total_usdt_sold <= 0:
        return None

    average_price = total_toman / total_usdt_sold

    return {
        "received_toman": total_toman,
        "remaining_usdt": remaining_usdt,
        "average_price": average_price,
        "levels_used": levels_used,
        "fully_filled": remaining_usdt < 0.000001,
    }


# ============================================================
# ARBITRAGE CALCULATION
# ============================================================

def calculate_arbitrage(buy_market, sell_market):
    buy_exchange = buy_market["exchange"]
    sell_exchange = sell_market["exchange"]

    buy_fee_rate = get_exchange_fee(buy_exchange)
    sell_fee_rate = get_exchange_fee(sell_exchange)

    buy_result = simulate_buy_with_toman(buy_market["asks"], TRADE_AMOUNT_TOMAN)

    if not buy_result or not buy_result["fully_filled"]:
        return None

    invested_toman = buy_result["spent_toman"]
    usdt_amount = buy_result["usdt_bought"]

    buy_fee_toman = invested_toman * buy_fee_rate
    total_buy_cost = invested_toman + buy_fee_toman

    sell_result = simulate_sell_usdt(sell_market["bids"], usdt_amount)

    if not sell_result or not sell_result["fully_filled"]:
        return None

    gross_received_toman = sell_result["received_toman"]
    sell_fee_toman = gross_received_toman * sell_fee_rate
    net_received_toman = gross_received_toman - sell_fee_toman

    total_fees = buy_fee_toman + sell_fee_toman
    net_profit = net_received_toman - total_buy_cost
    net_profit_percent = (net_profit / total_buy_cost) * 100

    return {
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,
        "invested_toman": invested_toman,
        "usdt_amount": usdt_amount,
        "buy_average_price": buy_result["average_price"],
        "sell_average_price": sell_result["average_price"],
        "total_fees": total_fees,
        "net_profit": net_profit,
        "net_profit_percent": net_profit_percent,
    }


# ============================================================
# PRINT RANKING
# ============================================================

def print_ranking(results):
    print()
    print("=" * 65)
    print("ARBITRAGE RANKING - AFTER FEES")
    print("=" * 65)

    for index, result in enumerate(results, start=1):
        status = "PROFIT" if result["net_profit"] > 0 else "LOSS"

        print()
        print(f"#{index} | {status}")
        print(f"ROUTE: {result['buy_exchange']} -> {result['sell_exchange']}")
        print(f"NET PROFIT: {result['net_profit']:,.0f} TOMAN")
        print(f"NET PROFIT %: {result['net_profit_percent']:.4f}%")

    print()
    print("=" * 65)


# ============================================================
# BUILD TELEGRAM MESSAGE
# ============================================================

def build_telegram_message(result):
    lines = [
        "🚨 ARBITRAGE OPPORTUNITY",
        "",
        f"🟢 BUY: {result['buy_exchange']}",
        f"🔴 SELL: {result['sell_exchange']}",
        "",
        f"💰 Investment: {result['invested_toman']:,.0f} تومان",
        f"💵 USDT: {result['usdt_amount']:,.4f}",
        "",
        f"📈 Buy Avg: {result['buy_average_price']:,.0f}",
        f"📉 Sell Avg: {result['sell_average_price']:,.0f}",
        "",
        f"💸 Fees: {result['total_fees']:,.0f} تومان",
        "",
        f"🔥 NET PROFIT: {result['net_profit']:,.0f} تومان",
        f"📊 PROFIT: {result['net_profit_percent']:.4f}%",
    ]

    return "\n".join(lines)


# ============================================================
# ONE ARBITRAGE CHECK (این تابع دقیقاً یک‌بار در هر اجرای Workflow صدا زده می‌شود)
# ============================================================

def run_arbitrage_cycle():
    print()
    print("=" * 65)
    print(f"CHECK: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    fetchers = [
        get_wallex_market_data,
        get_bitpin_market_data,
        get_ramzinex_market_data,
    ]

    markets = []

    for fetcher in fetchers:
        market = fetcher()

        if market:
            markets.append(market)
            print(
                f"SUCCESS | {market['exchange']} | "
                f"ASKS={len(market['asks'])} | BIDS={len(market['bids'])}"
            )
        else:
            print("FAILED | Exchange data not received")

    if len(markets) < 2:
        print("ERROR | کمتر از دو صرافی در دسترس است")
        return

    results = []

    for buy_market in markets:
        for sell_market in markets:
            if buy_market["exchange"] == sell_market["exchange"]:
                continue

            result = calculate_arbitrage(buy_market, sell_market)

            if result:
                results.append(result)

    results.sort(key=lambda x: x["net_profit"], reverse=True)

    if not results:
        print("NO EXECUTABLE ARBITRAGE ROUTES FOUND")
        return

    print_ranking(results)

    profitable_results = [
        result
        for result in results
        if result["net_profit"] > 0 and result["net_profit_percent"] >= MIN_PROFIT_PERCENT
    ]

    if not profitable_results:
        print("NO OPPORTUNITY ABOVE TELEGRAM THRESHOLD")
        return

    for result in profitable_results:
        route = f"{result['buy_exchange']}_TO_{result['sell_exchange']}"
        message = build_telegram_message(result)

        print(f"SENDING TELEGRAM ALERT | {route}")
        send_telegram_message(message)


# ============================================================
# MAIN
# ============================================================

def main():
    print()
    print("=" * 65)
    print("ARBITRAGE BOT - SINGLE RUN")
    print("=" * 65)
    print(f"TRADE AMOUNT: {TRADE_AMOUNT_TOMAN:,.0f} TOMAN")
    print(f"MIN PROFIT: {MIN_PROFIT_PERCENT}%")

    run_arbitrage_cycle()

    print()
    print("=" * 65)
    print("RUN FINISHED")
    print("=" * 65)


if __name__ == "__main__":
    main()
