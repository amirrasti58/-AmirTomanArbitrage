"""
============================================================
ARBITRAGE BOT
Wallex + BitPin + Ramzinex + Nobitex + Exir + Sarrafex

USDT / TOMAN
Order Book / Fees / Net Profit / Telegram Alerts
Continuous Monitoring

NO AUTOMATIC TRADING
NO WITHDRAWAL
NO DEPOSIT
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
# ============================================================

EXCHANGE_FEES = {

    "Wallex": {
        "maker": float(os.environ.get(
            "WALLEX_MAKER_FEE", "0.0025"
        )),
        "taker": float(os.environ.get(
            "WALLEX_TAKER_FEE", "0.0030"
        )),
    },

    "BitPin": {
        "maker": float(os.environ.get(
            "BITPIN_MAKER_FEE", "0.0002"
        )),
        "taker": float(os.environ.get(
            "BITPIN_TAKER_FEE", "0.0005"
        )),
    },

    "Ramzinex": {
        "maker": float(os.environ.get(
            "RAMZINEX_MAKER_FEE", "0.0020"
        )),
        "taker": float(os.environ.get(
            "RAMZINEX_TAKER_FEE", "0.0025"
        )),
    },

    "Nobitex": {
        "maker": float(os.environ.get(
            "NOBITEX_MAKER_FEE", "0.0020"
        )),
        "taker": float(os.environ.get(
            "NOBITEX_TAKER_FEE", "0.0025"
        )),
    },

    "Exir": {
        "maker": float(os.environ.get(
            "EXIR_MAKER_FEE", "0.0030"
        )),
        "taker": float(os.environ.get(
            "EXIR_TAKER_FEE", "0.0030"
        )),
    },

    "Sarrafex": {
        "maker": float(os.environ.get(
            "SARRAFEX_MAKER_FEE", "0.0030"
        )),
        "taker": float(os.environ.get(
            "SARRAFEX_TAKER_FEE", "0.0030"
        )),
    },
}


# ============================================================
# ALERT COOLDOWN
# ============================================================

last_alert_time = {}


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "ArbitrageBot/1.0"
})


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_price(order):
    if isinstance(order, dict):
        return safe_float(
            order.get("price")
            or order.get("rate")
            or order.get("p")
        )

    if isinstance(order, (list, tuple)):
        if len(order) >= 1:
            return safe_float(order[0])

    return 0.0


def extract_volume(order):
    if isinstance(order, dict):
        return safe_float(
            order.get("volume")
            or order.get("quantity")
            or order.get("amount")
            or order.get("qty")
            or order.get("q")
        )

    if isinstance(order, (list, tuple)):
        if len(order) >= 2:
            return safe_float(order[1])

    return 0.0


def normalize_orders(orders, reverse=False):
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
            "volume": volume
        })

    result.sort(
        key=lambda x: x["price"],
        reverse=reverse
    )

    return result[:ORDERBOOK_LEVELS]


# ============================================================
# MARKET DATA OBJECT
# ============================================================

def create_market_data(name, asks, bids):

    asks = normalize_orders(
        asks,
        reverse=False
    )

    bids = normalize_orders(
        bids,
        reverse=True
    )

    if not asks or not bids:
        return None

    return {
        "exchange": name,
        "asks": asks,
        "bids": bids,
        "timestamp": time.time()
    }


# ============================================================
# FEES
# ============================================================

def get_exchange_fee(exchange_name):

    exchange = EXCHANGE_FEES.get(exchange_name)

    if not exchange:
        return 0.0

    if ORDER_TYPE == "maker":
        return exchange["maker"]

    return exchange["taker"]


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(message):

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM ERROR: BOT TOKEN NOT SET")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM ERROR: CHAT ID NOT SET")
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:

        response = SESSION.post(
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT
        )

        print(
            f"TELEGRAM HTTP STATUS: "
            f"{response.status_code}"
        )

        if response.ok:

            print(
                "TELEGRAM SUCCESS: MESSAGE SENT"
            )

            return True

        print(
            "TELEGRAM ERROR:",
            response.text[:500]
        )

    except Exception as exc:

        print(
            "TELEGRAM ERROR:",
            str(exc)
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

    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        result = data.get("result", data)

        asks = result.get("ask", [])
        bids = result.get("bid", [])

        return create_market_data(
            "Wallex",
            asks,
            bids
        )

    except Exception as exc:

        print(
            "ERROR | Wallex |",
            str(exc)
        )

        return None


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
        )
    ]

    for url in urls:

        try:

            response = SESSION.get(
                url,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            data = response.json()

            asks = data.get("asks", [])
            bids = data.get("bids", [])

            market = create_market_data(
                "BitPin",
                asks,
                bids
            )

            if market:
                return market

        except Exception:
            continue

    print(
        "ERROR | BitPin | "
        "all known endpoints failed"
    )

    return None


# ============================================================
# RAMZINEX
# ============================================================

def get_ramzinex_market_data():

    pairs_url = (
        "https://publicapi.ramzinex.com/"
        "exchange/api/v1.0/exchange/pairs"
    )

    try:

        response = SESSION.get(
            pairs_url,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        pairs = data

        if isinstance(data, dict):

            pairs = (
                data.get("data")
                or data.get("result")
                or data.get("pairs")
                or []
            )

        selected_pair = None

        if isinstance(pairs, list):

            for pair in pairs:

                if not isinstance(pair, dict):
                    continue

                text = str(pair).upper()

                if (
                    "USDT" in text
                    and (
                        "IRT" in text
                        or "IRR" in text
                        or "TMN" in text
                        or "TOMAN" in text
                    )
                ):

                    selected_pair = pair
                    break

        if not selected_pair:
            raise Exception(
                "USDT/IRT pair not found"
            )

        pair_id = (
            selected_pair.get("id")
            or selected_pair.get("pair_id")
            or selected_pair.get("pairId")
        )

        if pair_id is None:
            raise Exception(
                "Ramzinex pair ID not found"
            )

        quote_text = str(selected_pair).upper()

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
            )
        ]

        for url in urls:

            try:

                response = SESSION.get(
                    url,
                    timeout=REQUEST_TIMEOUT
                )

                response.raise_for_status()

                book = response.json()

                if isinstance(book, dict):

                    asks = (
                        book.get("asks")
                        or book.get("sells")
                        or []
                    )

                    bids = (
                        book.get("bids")
                        or book.get("buys")
                        or []
                    )

                else:
                    continue

                market = create_market_data(
                    "Ramzinex",
                    asks,
                    bids
                )

                if not market:
                    continue

                # Convert Rial to Toman
                # only if the selected quote is IRR.
                if "IRR" in quote_text:

                    for order in market["asks"]:
                        order["price"] /= 10

                    for order in market["bids"]:
                        order["price"] /= 10

                return market

            except Exception:
                continue

        raise Exception(
            "Ramzinex orderbook endpoints failed"
        )

    except Exception as exc:

        print(
            "ERROR | Ramzinex |",
            str(exc)
        )

        return None


# ============================================================
# NOBITEX
# ============================================================

def get_nobitex_market_data():

    url = (
        "https://api.nobitex.ir/"
        "v3/orderbook/USDTIRT"
    )

    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        asks = data.get("asks", [])
        bids = data.get("bids", [])

        market = create_market_data(
            "Nobitex",
            asks,
            bids
        )

        if not market:
            raise Exception(
                "Nobitex returned empty orderbook"
            )

        return market

    except Exception as exc:

        print(
            "WARNING | Nobitex unavailable |",
            str(exc)
        )

        return None


# ============================================================
# EXIR
# ============================================================

def get_exir_symbol():

    url = (
        "https://api.exir.io/v2/constants"
    )

    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        text = str(data).lower()

        candidates = [
            "usdt-irt",
            "usdt_irt",
            "usdtirt",
            "usdt/irt"
        ]

        for symbol in candidates:

            if symbol in text:
                return symbol

        return "usdt-irt"

    except Exception:

        return "usdt-irt"


def get_exir_market_data():

    symbol = get_exir_symbol()

    url = (
        "https://api.exir.io/v2/orderbook"
    )

    params = {
        "symbol": symbol
    }

    try:

        response = SESSION.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        asks = data.get("asks", [])
        bids = data.get("bids", [])

        market = create_market_data(
            "Exir",
            asks,
            bids
        )

        if not market:
            raise Exception(
                "Exir returned empty orderbook"
            )

        return market

    except Exception as exc:

        print(
            "ERROR | Exir |",
            str(exc)
        )

        return None


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

    try:

        response = SESSION.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        books = data.get(
            "value",
            []
        )

        selected_book = None

        if isinstance(books, list):

            for book in books:

                if not isinstance(book, dict):
                    continue

                pair = str(
                    book.get("pair", "")
                ).upper().replace(" ", "")

                if pair in (
                    "USDT/IRT",
                    "USDTIRT"
                ):

                    selected_book = book
                    break

        # If the filter is ignored by the API,
        # search the returned books again.
        if selected_book is None:

            if isinstance(books, list):

                for book in books:

                    if not isinstance(book, dict):
                        continue

                    pair = str(
                        book.get("pair", "")
                    ).upper().replace(" ", "")

                    if (
                        "USDT" in pair
                        and "IRT" in pair
                    ):

                        selected_book = book
                        break

        if selected_book is None:

            raise Exception(
                "USDT/IRT orderbook not found"
            )

        asks = selected_book.get(
            "asks",
            []
        )

        bids = selected_book.get(
            "bids",
            []
        )

        market = create_market_data(
            "Sarrafex",
            asks,
            bids
        )

        if not market:
            raise Exception(
                "Sarrafex returned empty orderbook"
            )

        return market

    except Exception as exc:

        print(
            "ERROR | Sarrafex |",
            str(exc)
        )

        return None


# ============================================================
# SIMULATE BUY
# ============================================================

def simulate_buy(
    asks,
    toman_amount,
    fee_rate
):

    remaining_toman = toman_amount
    total_usdt = 0.0
    total_cost = 0.0

    for order in asks:

        price = order["price"]
        volume = order["volume"]

        if price <= 0 or volume <= 0:
            continue

        max_cost = price * volume

        spend = min(
            remaining_toman,
            max_cost
        )

        usdt = spend / price

        total_usdt += usdt
        total_cost += spend

        remaining_toman -= spend

        if remaining_toman <= 1:
            break

    if total_usdt <= 0:
        return None

    if remaining_toman > 1:
        return None

    fee = total_cost * fee_rate

    total_cost_with_fee = (
        total_cost + fee
    )

    return {
        "usdt": total_usdt,
        "cost": total_cost,
        "fee": fee,
        "total_cost": total_cost_with_fee
    }


# ============================================================
# SIMULATE SELL
# ============================================================

def simulate_sell(
    bids,
    usdt_amount,
    fee_rate
):

    remaining_usdt = usdt_amount
    total_revenue = 0.0

    for order in bids:

        price = order["price"]
        volume = order["volume"]

        if price <= 0 or volume <= 0:
            continue

        sell_amount = min(
            remaining_usdt,
            volume
        )

        revenue = (
            sell_amount * price
        )

        total_revenue += revenue

        remaining_usdt -= sell_amount

        if remaining_usdt <= 1e-8:
            break

    if total_revenue <= 0:
        return None

    if remaining_usdt > 1e-8:
        return None

    fee = total_revenue * fee_rate

    net_revenue = (
        total_revenue - fee
    )

    return {
        "revenue": total_revenue,
        "fee": fee,
        "net_revenue": net_revenue
    }


# ============================================================
# CALCULATE ARBITRAGE
# ============================================================

def calculate_arbitrage(
    buy_market,
    sell_market
):

    buy_exchange = buy_market["exchange"]
    sell_exchange = sell_market["exchange"]

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

    total_cost = buy_result[
        "total_cost"
    ]

    net_revenue = sell_result[
        "net_revenue"
    ]

    net_profit = (
        net_revenue - total_cost
    )

    profit_percent = (
        net_profit
        / total_cost
        * 100
    )

    total_fees = (
        buy_result["fee"]
        + sell_result["fee"]
    )

    return {
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,
        "usdt_amount": buy_result["usdt"],
        "total_cost": total_cost,
        "net_revenue": net_revenue,
        "buy_fee": buy_result["fee"],
        "sell_fee": sell_result["fee"],
        "fees": total_fees,
        "net_profit": net_profit,
        "profit_percent": profit_percent
    }


# ============================================================
# FETCH ALL EXCHANGES
# ============================================================

def fetch_all_markets():

    fetchers = [
        get_wallex_market_data,
        get_bitpin_market_data,
        get_ramzinex_market_data,
        get_nobitex_market_data,
        get_exir_market_data,
        get_sarrafex_market_data
    ]

    markets = {}

    for fetcher in fetchers:

        try:

            market = fetcher()

            if market:

                exchange = market[
                    "exchange"
                ]

                markets[exchange] = market

                print(
                    f"SUCCESS | {exchange} | "
                    f"ASKS={len(market['asks'])} | "
                    f"BIDS={len(market['bids'])}"
                )

            else:

                print(
                    "WARNING | Exchange skipped"
                )

        except Exception as exc:

            print(
                "WARNING | Exchange fetch failed |",
                str(exc)
            )

    return markets


# ============================================================
# BUILD ROUTES
# ============================================================

def calculate_all_routes(markets):

    exchanges = list(
        markets.keys()
    )

    results = []

    for buy_exchange in exchanges:

        for sell_exchange in exchanges:

            if buy_exchange == sell_exchange:
                continue

            result = calculate_arbitrage(
                markets[buy_exchange],
                markets[sell_exchange]
            )

            if result:

                results.append(result)

    results.sort(
        key=lambda x: x["net_profit"],
        reverse=True
    )

    return results


# ============================================================
# TELEGRAM ALERT
# ============================================================

def send_arbitrage_alert(result):

    route = (
        f"{result['buy_exchange']}"
        f" -> "
        f"{result['sell_exchange']}"
    )

    now = time.time()

    previous = last_alert_time.get(
        route,
        0
    )

    if (
        now - previous
        < ALERT_COOLDOWN_SECONDS
    ):
        return

    last_alert_time[route] = now

    message = (
        "🚨 ARBITRAGE OPPORTUNITY\n"
        "\n"
        f"BUY: {result['buy_exchange']}\n"
        f"SELL: {result['sell_exchange']}\n"
        "\n"
        f"TRADE AMOUNT: "
        f"{TRADE_AMOUNT_TOMAN:,.0f} TOMAN\n"
        f"USDT: "
        f"{result['usdt_amount']:.6f}\n"
        "\n"
        f"NET PROFIT: "
        f"{result['net_profit']:,.0f} TOMAN\n"
        f"NET PROFIT: "
        f"{result['profit_percent']:.3f}%\n"
        "\n"
        f"TOTAL FEES: "
        f"{result['fees']:,.0f} TOMAN\n"
        f"BUY FEE: "
        f"{result['buy_fee']:,.0f} TOMAN\n"
        f"SELL FEE: "
        f"{result['sell_fee']:,.0f} TOMAN\n"
        "\n"
        f"THRESHOLD: "
        f"{MIN_PROFIT_PERCENT:.2f}%\n"
        "\n"
        "⚠️ MONITORING ALERT ONLY"
    )

    send_telegram_message(
        message
    )


# ============================================================
# PRINT RANKING
# ============================================================

def print_ranking(results):

    print("=" * 66)
    print(
        "ARBITRAGE RANKING - AFTER FEES"
    )
    print("=" * 66)

    if not results:

        print(
            "NO VALID ROUTES"
        )

        return

    for index, result in enumerate(
        results,
        start=1
    ):

        status = (
            "PROFIT"
            if result["net_profit"] > 0
            else "LOSS"
        )

        print(
            f"#{index} | {status}"
        )

        print(
            f"ROUTE: "
            f"{result['buy_exchange']} "
            f"-> "
            f"{result['sell_exchange']}"
        )

        print(
            f"NET PROFIT: "
            f"{result['net_profit']:,.0f} TOMAN"
        )

        print(
            f"NET PROFIT %: "
            f"{result['profit_percent']:.4f}%"
        )

        print(
            f"FEES: "
            f"{result['fees']:,.0f} TOMAN"
        )

        print("-" * 66)


# ============================================================
# ONE ARBITRAGE CYCLE
# ============================================================

def run_arbitrage_cycle(
    cycle_number
):

    print(
        f"MONITORING CYCLE #{cycle_number}"
    )

    print("=" * 66)

    print(
        "CHECK:",
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print("=" * 66)

    markets = fetch_all_markets()

    available_count = len(markets)

    print(
        f"AVAILABLE EXCHANGES: "
        f"{available_count}"
    )

    if available_count < 2:

        print(
            "WARNING | "
            "Less than 2 exchanges available"
        )

        return

    route_count = (
        available_count
        * (available_count - 1)
    )

    print(
        f"AVAILABLE ROUTES: "
        f"{route_count}"
    )

    results = calculate_all_routes(
        markets
    )

    print_ranking(results)

    opportunity_found = False

    for result in results:

        if (
            result["net_profit"] > 0
            and
            result["profit_percent"]
            >= MIN_PROFIT_PERCENT
        ):

            opportunity_found = True

            send_arbitrage_alert(
                result
            )

    if not opportunity_found:

        print(
            "NO OPPORTUNITY ABOVE "
            "TELEGRAM THRESHOLD"
        )

    print(
        f"NEXT CHECK IN "
        f"{CHECK_INTERVAL_SECONDS} SECONDS"
    )


# ============================================================
# CONTINUOUS MONITORING
# ============================================================

def run_continuous_monitoring():

    start_time = time.time()

    cycle_number = 1

    while True:

        elapsed = (
            time.time()
            - start_time
        )

        if elapsed >= MAX_RUNTIME_SECONDS:

            print("=" * 66)

            print(
                "MAX RUNTIME REACHED"
            )

            print(
                "STOPPING SAFELY"
            )

            print("=" * 66)

            return

        try:

            run_arbitrage_cycle(
                cycle_number
            )

        except KeyboardInterrupt:

            print(
                "STOPPED BY USER"
            )

            return

        except Exception as exc:

            print(
                "CYCLE ERROR:",
                str(exc)
            )

        cycle_number += 1

        remaining = (
            MAX_RUNTIME_SECONDS
            - (
                time.time()
                - start_time
            )
        )

        if remaining <= 0:
            return

        sleep_time = min(
            CHECK_INTERVAL_SECONDS,
            int(remaining)
        )

        if sleep_time > 0:
            time.sleep(
                sleep_time
            )


# ============================================================
# STARTUP MESSAGE
# ============================================================

def print_startup():

    print("=" * 66)
    print("ARBITRAGE BOT")
    print("=" * 66)

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
        "ROUTES PER CYCLE: 30 "
        "(when all 6 exchanges are available)"
    )

    print(
        f"TRADE AMOUNT: "
        f"{TRADE_AMOUNT_TOMAN:,.0f} TOMAN"
    )

    print(
        f"MIN PROFIT: "
        f"{MIN_PROFIT_PERCENT}%"
    )

    print(
        f"CHECK INTERVAL: "
        f"{CHECK_INTERVAL_SECONDS} seconds"
    )

    print(
        f"ORDER TYPE: "
        f"{ORDER_TYPE.upper()}"
    )

    print("=" * 66)
    print("EXCHANGE FEES")
    print("-" * 66)

    for exchange, fees in (
        EXCHANGE_FEES.items()
    ):

        print(
            f"{exchange}: "
            f"Maker={fees['maker'] * 100:.4f}% | "
            f"Taker={fees['taker'] * 100:.4f}%"
        )

    print("=" * 66)


# ============================================================
# MAIN
# ============================================================

def main():

    print_startup()

    print("=" * 66)
    print("TELEGRAM")
    print("=" * 66)

    startup_message = (
        "🤖 ARBITRAGE BOT STARTED\n"
        "\n"
        "Exchanges:\n"
        "Wallex\n"
        "BitPin\n"
        "Ramzinex\n"
        "Nobitex\n"
        "Exir\n"
        "Sarrafex\n"
        "\n"
        "Market: USDT/TOMAN\n"
        f"Trade Amount: "
        f"{TRADE_AMOUNT_TOMAN:,.0f} TOMAN\n"
        f"Minimum Profit: "
        f"{MIN_PROFIT_PERCENT:.2f}%\n"
        f"Order Type: "
        f"{ORDER_TYPE.upper()}\n"
        "\n"
        "Monitoring only."
    )

    send_telegram_message(
        startup_message
    )

    print("=" * 66)
    print(
        "CONTINUOUS ARBITRAGE MONITORING"
    )
    print("=" * 66)

    print(
        f"CHECK INTERVAL: "
        f"{CHECK_INTERVAL_SECONDS} seconds"
    )

    print(
        f"MAX RUNTIME: "
        f"{MAX_RUNTIME_SECONDS / 3600:.2f} hours"
    )

    print(
        f"TRADE AMOUNT: "
        f"{TRADE_AMOUNT_TOMAN:,.0f} TOMAN"
    )

    print(
        f"MIN PROFIT: "
        f"{MIN_PROFIT_PERCENT}%"
    )

    print(
        f"ALERT COOLDOWN: "
        f"{ALERT_COOLDOWN_SECONDS} seconds"
    )

    print(
        "EXCHANGES: "
        "Wallex + BitPin + Ramzinex + "
        "Nobitex + Exir + Sarrafex"
    )

    print(
        "ROUTES PER CYCLE: 30"
    )

    print("=" * 66)

    run_continuous_monitoring()


if __name__ == "__main__":
    main()
