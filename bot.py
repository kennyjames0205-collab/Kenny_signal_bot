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

PIP = 0.0001
SL_PIPS = 5     # Tiny loss ($0.50)
TP_PIPS = 10    # Good win ($1.00)

def send_discord(msg):
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception:
        pass

def make_headers():
    return {"Authorization": "Bearer " + API_KEY, "Idempotency-Key": "idem-" + str(time.time())}

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

def get_signal():
    data = yf.download("EURUSD=X", interval="1m", period="1d", progress=False)
    if hasattr(data.columns, "get_level_values"):
        data.columns = data.columns.get_level_values(0)
    
    data["ema9"] = ta.trend.EMAIndicator(data["Close"], window=9).ema_indicator()
    data["ema21"] = ta.trend.EMAIndicator(data["Close"], window=21).ema_indicator()
    
    last = data.iloc[-1]
    close = float(last["Close"])
    e9 = float(last["ema9"])
    e21 = float(last["ema21"])

    # PURE MOMENTUM: No RSI filter.
    if e9 > e21:
        return "CALL", "Momentum BUY", close
    if e9 < e21:
        return "PUT", "Momentum SELL", close

    return "NO TRADE", "Flat", close

print("MT5 Bot v16 (Pure Action) starting...")
send_discord("🚀 MT5 Bot v16 starting — Pure Action Mode. 3 Trades allowed.")

account_id = start_session()
if not account_id:
    exit()

while True:
    try:
        account_id = start_session()
        if not account_id:
            time.sleep(60)
            continue

        # Allow up to 3 trades at the same time
        positions = get_open_positions(account_id)
        if len(positions) >= 3:
            print(f"Max 3 trades open. Waiting...")
            time.sleep(30)
            continue

        signal, reason, price = get_signal()
        now = datetime.now(timezone(timedelta(hours=1))).strftime("%H:%M:%S")
        
        if signal != "NO TRADE":
            side = "BUY" if signal == "CALL" else "SELL"
            ticket, sl, tp = place_order(account_id, side, price)

            if ticket:
                send_discord(
                    f"**⚡ MT5 ACTION TRADE (v16)**\n" +
                    f"**{signal}** `{SYMBOL}`\n" +
                    f"Entry: `{price:.5f}`\n" +
                    f"Ticket: `{ticket}`"
                )
                time.sleep(30)
        else:
            time.sleep(30)

    except Exception as e:
        print("Error:", e)
        time.sleep(60)
