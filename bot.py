import os
import time
import requests
import yfinance as yf
import ta
from datetime import datetime, timezone, timedelta

API_KEY = os.environ.get("TICKERALL_API_KEY")
MT5_ACCOUNT = int(os.environ.get("MT5_ACCOUNT", "0"))
MT5_SERVER = os.environ.get("MT5_SERVER")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD")
DISCORD_WEBHOOK = os.environ.get("WEBHOOK")

SYMBOL = "EURUSDm"
VOLUME = 0.01
BASE = "https://api.tickerall.com"

def send_discord(msg):
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg})
    except Exception as e:
        print("Discord error:", e)

def make_headers():
    return {
        "Authorization": "Bearer " + API_KEY,
        "Idempotency-Key": "idem-" + str(time.time())
    }

def start_session():
    data = {
        "broker": "mt5",
        "server": MT5_SERVER,
        "account": MT5_ACCOUNT,
        "password": MT5_PASSWORD,
        "terminalType": "MOBILE"
    }
    try:
        r = requests.post(BASE + "/v1/sessions", json=data, headers=make_headers(), timeout=30)
        if r.status_code in (200, 201):
            return r.json().get("accountId")
        print("Session fail:", r.status_code, r.json())
    except Exception as e:
        print("Session error:", e)
    return None

def place_order(account_id, side):
    data = {"type": "market", "symbol": SYMBOL, "side": side, "volume": VOLUME}
    try:
        r = requests.post(BASE + "/v1/accounts/" + account_id + "/orders",
                          json=data, headers=make_headers(), timeout=30)
        if r.status_code in (200, 201):
            return r.json().get("ticket")
        print("Order fail:", r.status_code, r.json())
    except Exception as e:
        print("Order error:", e)
    return None

def close_position(account_id, ticket):
    try:
        r = requests.delete(BASE + "/v1/accounts/" + account_id + "/positions/" + str(ticket),
                            headers=make_headers(), timeout=30)
        return r.status_code in (200, 204)
    except Exception as e:
        print("Close error:", e)
    return False

def get_signal():
    data = yf.download("EURUSD=X", interval="15m", period="5d", progress=False)
    if hasattr(data.columns, "get_level_values"):
        data.columns = data.columns.get_level_values(0)
    data["rsi"] = ta.momentum.RSIIndicator(data["Close"], window=14).rsi()
    data["ema20"] = ta.trend.EMAIndicator(data["Close"], window=20).ema_indicator()
    data["ema50"] = ta.trend.EMAIndicator(data["Close"], window=50).ema_indicator()
    data["ema200"] = ta.trend.EMAIndicator(data["Close"], window=200).ema_indicator()

    last = data.iloc[-1]
    prev = data.iloc[-2]
    rsi_now = float(last["rsi"])
    rsi_prev = float(prev["rsi"])
    e20 = float(last["ema20"])
    e50 = float(last["ema50"])
    e200 = float(last["ema200"])
    price = float(last["Close"])

    uptrend = e20 > e50 > e200
    downtrend = e20 < e50 < e200

    if rsi_now > 64 and rsi_now < rsi_prev:
        return "PUT", "Overbought drop (RSI " + str(round(rsi_prev, 1)) + " -> " + str(round(rsi_now, 1)) + ")", price, rsi_now
    if rsi_now < 36 and rsi_now > rsi_prev:
        return "CALL", "Oversold bounce (RSI " + str(round(rsi_prev, 1)) + " -> " + str(round(rsi_now, 1)) + ")", price, rsi_now
    if uptrend and rsi_prev < 45 and rsi_now > rsi_prev and rsi_now < 65:
        return "CALL", "Uptrend + RSI rising", price, rsi_now
    if downtrend and rsi_prev > 55 and rsi_now < rsi_prev and rsi_now > 35:
        return "PUT", "Downtrend + RSI falling", price, rsi_now

    return "NO TRADE", "No setup (RSI " + str(round(rsi_now, 1)) + ")", price, rsi_now

print("MT5 Auto-Trade Bot v5 starting...")
send_discord("MT5 Auto-Trade Bot v5 starting...")

account_id = start_session()
if not account_id:
    send_discord("Could not connect to MT5. Check Railway variables.")
    print("Fatal: no session")
    exit()

send_discord("Connected to MT5. Account: " + account_id)
print("Connected. Account ID:", account_id)

last_signal = None
last_signal_time = 0

while True:
    try:
        account_id = start_session()
        if not account_id:
            print("Session refresh failed")
            time.sleep(300)
            continue

        signal, reason, price, rsi = get_signal()
        now = datetime.now(timezone(timedelta(hours=1))).strftime("%H:%M:%S")
        print("[" + now + "] " + signal + " | " + str(price) + " | RSI " + str(round(rsi, 2)))

        if signal != "NO TRADE":
            if signal == last_signal and (time.time() - last_signal_time) < 1200:
                print("Duplicate signal - skipped")
            else:
                side = "BUY" if signal == "CALL" else "SELL"
                ticket = place_order(account_id, side)

                if ticket:
                    send_discord(
                        "**MT5 AUTO-TRADE**\n" +
                        "**" + signal + "** `" + SYMBOL + "`\n" +
                        "Entry: `" + str(round(price, 5)) + "`\n" +
                        "RSI: `" + str(round(rsi, 2)) + "`\n" +
                        "Ticket: `" + str(ticket) + "`\n" +
                        "Reason: " + reason + "\n" +
                        "Time: " + now
                    )
                    last_signal = signal
                    last_signal_time = time.time()
                    print("Order placed:", side, "ticket", ticket)

                    time.sleep(900)

                    account_id = start_session()
                    if account_id and close_position(account_id, ticket):
                        send_discord("Position `" + str(ticket) + "` closed on MT5.")
                        print("Closed", ticket)
                    else:
                        send_discord("Could not auto-close `" + str(ticket) + "`. Close manually.")
                    continue

        print("Waiting 15 min...")
        time.sleep(900)

    except Exception as e:
        print("Loop error:", e)
        send_discord("Bot error: " + str(e))
        time.sleep(60)
