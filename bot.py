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
SL_PIPS = 10
TP_PIPS = 15
TIME_LIMIT_MINUTES = 15

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
    data = {"broker": "mt5", "server": MT5_SERVER, "account": MT5_ACCOUNT, "password": MT5_PASSWORD, "terminalType": "MOBILE"}
    try:
        r = requests.post(BASE + "/v1/sessions", json=data, headers=make_headers(), timeout=30)
        if r.status_code in (200, 201):
            return r.json().get("accountId")
    except Exception as e:
        print("Session error:", e)
    return None

def get_open_positions(account_id):
    try:
        r = requests.get(BASE + "/v1/accounts/" + account_id, headers=make_headers(), timeout=30)
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
        r = requests.post(BASE + "/v1/accounts/" + account_id + "/orders", json=data, headers=make_headers(), timeout=30)
        if r.status_code in (200, 201):
            return r.json().get("ticket")
    except Exception as e:
        pass
    return None

def close_position(account_id, ticket):
    try:
        r = requests.delete(BASE + "/v1/accounts/" + account_id + "/positions/" + str(ticket), headers=make_headers(), timeout=30)
        return r.status_code in (200, 204)
    except Exception as e:
        return False

def get_signal():
    # Fetch H1 data for Trend
    data_h1 = yf.download("EURUSD=X", interval="1h", period="1mo", progress=False)
    if hasattr(data_h1.columns, "get_level_values"):
        data_h1.columns = data_h1.columns.get_level_values(0)
    data_h1["ema50"] = ta.trend.EMAIndicator(data_h1["Close"], window=50).ema_indicator()
    data_h1["ema200"] = ta.trend.EMAIndicator(data_h1["Close"], window=200).ema_indicator()
    h1_trend_up = float(data_h1["ema50"].iloc[-1]) > float(data_h1["ema200"].iloc[-1])
    h1_trend_down = float(data_h1["ema50"].iloc[-1]) < float(data_h1["ema200"].iloc[-1])

    # Fetch M15 data for Entry
    data_m15 = yf.download("EURUSD=X", interval="15m", period="5d", progress=False)
    if hasattr(data_m15.columns, "get_level_values"):
        data_m15.columns = data_m15.columns.get_level_values(0)
    
    data_m15["rsi"] = ta.momentum.RSIIndicator(data_m15["Close"], window=14).rsi()
    
    last = data_m15.iloc[-1]
    rsi_now = float(last["rsi"])
    close = float(last["Close"])

    # THE 70% LOGIC
    # If H1 is UP, only buy when M15 RSI is below 40 (discount)
    if h1_trend_up and rsi_now < 40:
        return "CALL", f"H1 Uptrend + M15 Oversold (RSI {rsi_now:.1f})", close
    
    # If H1 is DOWN, only sell when M15 RSI is above 60 (premium)
    if h1_trend_down and rsi_now > 60:
        return "PUT", f"H1 Downtrend + M15 Overbought (RSI {rsi_now:.1f})", close

    return "NO TRADE", f"Waiting for H1/M15 alignment (RSI {rsi_now:.1f})", close

print("MT5 Bot v12 (70% Strike Rate Mode) starting...")
send_discord("🚀 MT5 Bot v12 starting — H1 Trend + M15 Entry. Target: 70% Win Rate.")

account_id = start_session()
if not account_id:
    exit()

open_ticket = None
trade_start_time = 0
last_signal_time = 0

while True:
    try:
        account_id = start_session()
        if not account_id:
            time.sleep(60)
            continue

        # Manage open trade
        if open_ticket:
            positions = get_open_positions(account_id)
            still_open = any(str(p.get("ticket")) == str(open_ticket) for p in positions)
            
            if not still_open:
                send_discord(f"✅ Trade `{open_ticket}` closed (Hit SL/TP).")
                open_ticket = None
                last_signal_time = time.time()
                time.sleep(60)
                continue

            # 15 Minute Time Limit
            if time.time() - trade_start_time > (TIME_LIMIT_MINUTES * 60):
                if close_position(account_id, open_ticket):
                    send_discord(f"⏱️ Trade `{open_ticket}` closed by 15-min timer.")
                    open_ticket = None
                    last_signal_time = time.time()
                time.sleep(60)
                continue
                
            time.sleep(30)
            continue

        # Look for new trade
        if time.time() - last_signal_time < 900: # 15 min cooldown between trades
            time.sleep(60)
            continue

        signal, reason, price = get_signal()
        now = datetime.now(timezone(timedelta(hours=1))).strftime("%H:%M:%S")
        print(f"[{now}] {signal} | {price:.5f} | {reason}")

        if signal != "NO TRADE":
            side = "BUY" if signal == "CALL" else "SELL"
            ticket = place_order(account_id, side, price)

            if ticket:
                open_ticket = ticket
                trade_start_time = time.time()
                send_discord(
                    f"**🚀 MT5 TRADE (v12)**\n" +
                    f"**{signal}** `{SYMBOL}`\n" +
                    f"Entry: `{price:.5f}`\n" +
                    f"Ticket: `{ticket}`\n" +
                    f"Reason: {reason}"
                )
                time.sleep(60)
            else:
                time.sleep(60)
        else:
            time.sleep(300) # Check every 5 mins

    except Exception as e:
        print("Error:", e)
        time.sleep(60)
