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
SL_PIPS = 5    # Tiny loss ($0.50)
TP_PIPS = 5    # Quick win ($0.50)

def send_discord(msg):
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception as e:
        pass

def make_headers():
    return {
        "Authorization": "Bearer " + API_KEY,
        "Idempotency-Key": "idem-" + str(time.time())
    }

def start_session():
    data = {"broker": "mt5", "server": MT5_SERVER, "account": MT5_ACCOUNT, "password": MT5_PASSWORD, "terminalType": "MOBILE"}
    try:
        r = requests.post(BASE + "/v1/sessions", json=data, headers=make_headers(), timeout=15)
        if r.status_code in (200, 201):
            return r.json().get("accountId")
    except Exception as e:
        pass
    return None

def get_open_positions(account_id):
    try:
        r = requests.get(BASE + "/v1/accounts/" + account_id, headers=make_headers(), timeout=15)
        if r.status_code == 200:
            return r.json().get("positions", [])
    except Exception as e:
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
    except Exception as e:
        pass
    return None, None, None

def get_signal():
    # 5-Minute Chart for Scalping
    data = yf.download("EURUSD=X", interval="5m", period="1d", progress=False)
    if hasattr(data.columns, "get_level_values"):
        data.columns = data.columns.get_level_values(0)
    
    data["rsi"] = ta.momentum.RSIIndicator(data["Close"], window=14).rsi()
    data["ema9"] = ta.trend.EMAIndicator(data["Close"], window=9).ema_indicator()
    data["ema21"] = ta.trend.EMAIndicator(data["Close"], window=21).ema_indicator()
    
    last = data.iloc[-1]
    prev = data.iloc[-2]
    rsi_now = float(last["rsi"])
    close = float(last["Close"])
    e9 = float(last["ema9"])
    e21 = float(last["ema21"])
    prev_e9 = float(prev["ema9"])
    prev_e21 = float(prev["ema21"])

    # Scalping Logic: EMA Crossover + RSI Momentum
    if prev_e9 < prev_e21 and e9 > e21 and rsi_now > 50:
        return "CALL", f"Bullish Crossover (RSI {rsi_now:.1f})", close
    if prev_e9 > prev_e21 and e9 < e21 and rsi_now < 50:
        return "PUT", f"Bearish Crossover (RSI {rsi_now:.1f})", close

    return "NO TRADE", f"Waiting for cross (RSI {rsi_now:.1f})", close

print("MT5 Bot v14 (Micro-Scalper) starting...")
send_discord("⚡ MT5 Bot v14 starting — Scalping Mode.")

account_id = start_session()
if not account_id:
    exit()

open_ticket = None
last_signal_time = 0

while True:
    try:
        account_id = start_session()
        if not account_id:
            time.sleep(60)
            continue

        if open_ticket:
            positions = get_open_positions(account_id)
            still_open = any(str(p.get("ticket")) == str(open_ticket) for p in positions)
            if not still_open:
                send_discord(f"✅ Trade `{open_ticket}` closed.")
                open_ticket = None
                last_signal_time = time.time()
            time.sleep(30)
            continue

        # Short cooldown (5 mins) to allow more trades
        if time.time() - last_signal_time < 300:
            time.sleep(30)
            continue

        signal, reason, price = get_signal()
        now = datetime.now(timezone(timedelta(hours=1))).strftime("%H:%M:%S")
        print(f"[{now}] {signal} | {price:.5f} | {reason}")

        if signal != "NO TRADE":
            side = "BUY" if signal == "CALL" else "SELL"
            ticket, sl, tp = place_order(account_id, side, price)

            if ticket:
                open_ticket = ticket
                send_discord(
                    f"**⚡ MT5 SCALP TRADE (v14)**\n" +
                    f"**{signal}** `{SYMBOL}`\n" +
                    f"Entry: `{price:.5f}`\n" +
                    f"SL: `{sl}`\n" +
                    f"TP: `{tp}`\n" +
                    f"Ticket: `{ticket}`"
                )
                time.sleep(30)
        else:
            time.sleep(60)

    except Exception as e:
        print("Error:", e)
        time.sleep(60)
