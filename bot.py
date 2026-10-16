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

# Pip sizes for EURUSD (Exness 5-digit)
PIP = 0.0001
SL_PIPS = 10      # Stop-loss distance
TP_PIPS = 15      # Take-profit distance

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

def get_current_price(account_id):
    try:
        r = requests.get(BASE + "/v1/accounts/" + account_id + "/symbols",
                         headers=make_headers(), timeout=30)
        if r.status_code == 200:
            data = r.json()
            for s in data.get("symbols", []):
                if s.upper().startswith("EURUSD"):
                    return None
    except Exception as e:
        print("Price fetch error:", e)
    return None

def place_order(account_id, side, entry_price):
    # Calculate SL and TP based on side
    if side == "BUY":
        sl = round(entry_price - (SL_PIPS * PIP), 5)
        tp = round(entry_price + (TP_PIPS * PIP), 5)
    else:  # SELL
        sl = round(entry_price + (SL_PIPS * PIP), 5)
        tp = round(entry_price - (TP_PIPS * PIP), 5)

    data = {
        "type": "market",
        "symbol": SYMBOL,
        "side": side,
        "volume": VOLUME,
        "stopLoss": sl,
        "takeProfit": tp
    }
    try:
        r = requests.post(BASE + "/v1/accounts/" + account_id + "/orders",
                          json=data, headers=make_headers(), timeout=30)
        if r.status_code in (200, 201):
            return r.json().get("ticket"), sl, tp
        print("Order fail:", r.status_code, r.json())
    except Exception as e:
        print("Order error:", e)
    return None, None, None

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
    data["ema50"] = ta.trend.EMAIndicator(data["Close"], window=50).ema_indicator()
    data["ema200"] = ta.trend.EMAIndicator(data["Close"], window=200).ema_indicator()

    last = data.iloc[-1]
    prev = data.iloc[-2]
    rsi_now = float(last["rsi"])
    rsi_prev = float(prev["rsi"])
    e50 = float(last["ema50"])
    e200 = float(last["ema200"])
    price = float(last["Close"])

    real_uptrend = price > e200
    real_downtrend = price < e200

    if real_downtrend and rsi_now > 64 and rsi_now < rsi_prev:
        return "PUT", "Downtrend + overbought drop", price, rsi_now
    if real_downtrend and e50 < e200 and rsi_prev > 55 and rsi_now < rsi_prev and rsi_now > 35:
        return "PUT", "Downtrend + RSI falling", price, rsi_now
    if real_uptrend and rsi_now < 36 and rsi_now > rsi_prev:
        return "CALL", "Uptrend + oversold bounce", price, rsi_now
    if real_uptrend and e50 > e200 and rsi_prev < 45 and rsi_now > rsi_prev and rsi_now < 65:
        return "CALL", "Uptrend + RSI rising", price, rsi_now

    return "NO TRADE", "No setup with trend (RSI " + str(round(rsi_now, 1)) + ")", price, rsi_now

print("MT5 Auto-Trade Bot v7 (trend + SL/TP) starting...")
send_discord("MT5 Auto-Trade Bot v7 starting — with stop-loss + take-profit")

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
            time.sleep(300)
            continue

        signal, reason, price, rsi = get_signal()
        now = datetime.now(timezone(timedelta(hours=1))).strftime("%H:%M:%S")
        print("[" + now + "] " + signal + " | " + str(round(price, 5)) + " | RSI " + str(round(rsi, 2)))

        if signal != "NO TRADE":
            if signal == last_signal and (time.time() - last_signal_time) < 1200:
                print("Duplicate skipped")
            else:
                side = "BUY" if signal == "CALL" else "SELL"
                ticket, sl, tp = place_order(account_id, side, price)

                if ticket:
                    send_discord(
                        "**MT5 AUTO-TRADE (v7)**\n" +
                        "**" + signal + "** `" + SYMBOL + "`\n" +
                        "Entry: `" + str(round(price, 5)) + "`\n" +
                        "SL: `" + str(sl) + "` (10 pips)\n" +
                        "TP: `" + str(tp) + "` (15 pips)\n" +
                        "RSI: `" + str(round(rsi, 2)) + "`\n" +
                        "Ticket: `" + str(ticket) + "`\n" +
                        "Reason: " + reason + "\n" +
                        "Time: " + now
                    )
                    last_signal = signal
                    last_signal_time = time.time()
                    print("Order:", side, "ticket", ticket, "SL", sl, "TP", tp)

                    time.sleep(900)

                    account_id = start_session()
                    if account_id:
                        close_position(account_id, ticket)
                        send_discord("Position `" + str(ticket) + "` closed (or hit SL/TP).")
                        print("Closed", ticket)
                    continue

        print("Waiting 15 min...")
        time.sleep(900)

    except Exception as e:
        print("Loop error:", e)
        send_discord("Bot error: " + str(e))
        time.sleep(60)
