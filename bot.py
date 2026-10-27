import os
import time
import requests
from datetime import datetime, timezone, timedelta

TICKERALL_KEY = os.environ.get("TICKERALL_API_KEY")
MT5_ACCOUNT = int(os.environ.get("MT5_ACCOUNT", "0"))
MT5_SERVER = os.environ.get("MT5_SERVER")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD")
DISCORD_WEBHOOK = os.environ.get("WEBHOOK")

TWELVEDATA_KEY = "ab9054239e1c440f82ae43d470fc80dc"

SYMBOL = "EURUSDm"
VOLUME = 0.01
BASE = "https://api.tickerall.com"

PIP = 0.0001
SL_PIPS = 5
TP_PIPS = 10

def send_discord(msg):
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception:
        pass

def make_headers():
    return {"Authorization": "Bearer " + TICKERALL_KEY, "Idempotency-Key": "idem-" + str(time.time())}

def start_session():
    data = {"broker": "mt5", "server": MT5_SERVER, "account": MT5_ACCOUNT, "password": MT5_PASSWORD, "terminalType": "MOBILE"}
    try:
        r = requests.post(BASE + "/v1/sessions", json=data, headers=make_headers(), timeout=15)
        if r.status_code in (200, 201):
            return r.json().get("accountId")
    except Exception:
        pass
    return None

def get_open_positions(account_id):
    try:
        r = requests.get(BASE + "/v1/accounts/" + account_id, headers=make_headers(), timeout=15)
        if r.status_code == 200:
            return r.json().get("positions", [])
    except Exception:
        pass
    return []

def place_order(account_id, side, entry_price):
    if side == "BUY":
        sl = round(entry_price - (SL_PIPS * PIP), 5)
        tp = round(entry_price + (TP_PIPS * PIP), 5)
    else:
        sl = round(entry_price + (SL_PIPS * PIP), 5)
        tp = round(entry_price - (TP_PIPS * PIP), 5)

    data = {"type": "market", "symbol": SYMBOL, "side": side, "volume": VOLUME, "stopLoss": sl, "takeProfit": tp}
    try:
        r = requests.post(BASE + "/v1/accounts/" + account_id + "/orders", json=data, headers=make_headers(), timeout=15)
        if r.status_code in (200, 201):
            return r.json().get("ticket"), sl, tp
    except Exception:
        pass
    return None, None, None

def calculate_ema(prices, period):
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def get_signal():
    url = f"https://api.twelvedata.com/time_series?symbol=EUR/USD&interval=1min&outputsize=30&apikey={TWELVEDATA_KEY}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if "values" not in data:
            return "NO TRADE", "API Limit or Error", 0
            
        closes = [float(candle["close"]) for candle in reversed(data["values"])]
        
        e9 = calculate_ema(closes, 9)
        e21 = calculate_ema(closes, 21)
        close = closes[-1]
        
        if e9 > e21:
            return "CALL", f"Momentum BUY", close
        if e9 < e21:
            return "PUT", f"Momentum SELL", close
            
    except Exception as e:
        print("Fetch error:", e)
        return "NO TRADE", "Network Error", 0

print("MT5 Bot v19.1 (No Spam) starting...")
send_discord("🪶 MT5 Bot v19.1 starting — No Spam. Max 2 trades.")

account_id = start_session()
if not account_id:
    print("Failed to start session.")
    exit()

while True:
    try:
        account_id = start_session()
        if not account_id:
            time.sleep(60)
            continue

        positions = get_open_positions(account_id)
        
        # --- THE FIX: Added time.sleep here ---
        if len(positions) >= 2:
            print("Max trades open. Waiting 60 seconds...")
            time.sleep(60)
            continue
        # --------------------------------------

        signal, reason, price = get_signal()
        now = datetime.now(timezone(timedelta(hours=1))).strftime("%H:%M:%S")
        print(f"[{now}] {signal} | {reason} | Price: {price}")

        if signal != "NO TRADE" and price > 0:
            side = "BUY" if signal == "CALL" else "SELL"
            ticket, sl, tp = place_order(account_id, side, price)
            if ticket:
                send_discord(f"⚡ **Action Trade**\n**{signal}** `{SYMBOL}`\nEntry: `{price:.5f}`\nTicket: `{ticket}`")
                time.sleep(300)
        else:
            time.sleep(60)

    except Exception as e:
        print("Error:", e)
        time.sleep(60)
