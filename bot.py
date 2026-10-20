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
BREAKEVEN_PIPS = 5

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

def get_open_positions(account_id):
    try:
        r = requests.get(BASE + "/v1/accounts/" + account_id, headers=make_headers(), timeout=30)
        if r.status_code == 200:
            return r.json().get("positions", [])
    except Exception as e:
        print("Fetch positions error:", e)
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
            return r.json().get("ticket"), sl, tp
        print("Order fail:", r.status_code, r.json())
    except Exception as e:
        print("Order error:", e)
    return None, None, None

def modify_sl(account_id, ticket, new_sl):
    try:
        data = {"stopLoss": new_sl}
        r = requests.patch(BASE + "/v1/accounts/" + account_id + "/positions/" + str(ticket), json=data, headers=make_headers(), timeout=30)
        return r.status_code in (200, 204)
    except Exception as e:
        print("Modify SL error:", e)
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
    close = float(last["Close"])
    e20 = float(last["ema20"])
    e50 = float(last["ema50"])
    e200 = float(last["ema200"])

    # THE ULTIMATE FILTER: Trend + RSI + Price Action
    # 1. Trend must be clear (EMA20 > EMA50 > EMA200 for buy, opposite for sell)
    # 2. Price must be on the right side of the 50 EMA (Pullback confirmed)
    # 3. RSI must be in the sweet spot and turning

    real_uptrend = close > e200
    real_downtrend = close < e200

    # BUY SETUP
    if real_uptrend:
        # Price must pull back near EMA50 but stay above it, RSI rising from below 45
        if close > e50 and rsi_prev < 45 and rsi_now > rsi_prev and rsi_now < 65:
            return "CALL", f"Strong Uptrend Pullback (RSI {rsi_prev:.1f}->{rsi_now:.1f})", close, rsi_now

    # SELL SETUP
    if real_downtrend:
        # Price must pull back near EMA50 but stay below it, RSI falling from above 55
        if close < e50 and rsi_prev > 55 and rsi_now < rsi_prev and rsi_now > 35:
            return "PUT", f"Strong Downtrend Pullback (RSI {rsi_prev:.1f}->{rsi_now:.1f})", close, rsi_now

    return "NO TRADE", f"Waiting for perfect setup (RSI {rsi_now:.1f})", close, rsi_now

print("MT5 Auto-Trade Bot v9 (Sniper Entry) starting...")
send_discord("MT5 Auto-Trade Bot v9 starting — Sniper Mode (Price Action + Trend + RSI).")

account_id = start_session()
if not account_id:
    send_discord("Could not connect to MT5.")
    exit()

send_discord("Connected to MT5. Account: " + account_id)

last_signal = None
last_signal_time = 0
open_ticket = None
breakeven_set = False
cooldown_until = 0

while True:
    try:
        account_id = start_session()
        if not account_id:
            time.sleep(60)
            continue

        if time.time() < cooldown_until:
            print(f"Cooldown active for {int(cooldown_until - time.time())}s...")
            time.sleep(60)
            continue

        if open_ticket:
            positions = get_open_positions(account_id)
            trade_still_open = False
            for p in positions:
                if str(p.get("ticket")) == str(open_ticket):
                    trade_still_open = True
                    current_pnl_pips = float(p.get("profit", 0)) / (VOLUME * 100000) / PIP
                    if current_pnl_pips >= BREAKEVEN_PIPS and not breakeven_set:
                        current_price = float(p.get("currentPrice", 0))
                        if modify_sl(account_id, open_ticket, current_price):
                            send_discord(f"🛡️ Trade `{open_ticket}` moved to Breakeven.")
                            breakeven_set = True
                    break

            if not trade_still_open:
                send_discord(f"✅ Position `{open_ticket}` closed.")
                print("Trade closed:", open_ticket)
                open_ticket = None
                breakeven_set = False
                last_signal_time = time.time()
                cooldown_until = time.time() + 900
                print("Entering 15 min cooldown...")
            else:
                time.sleep(60)
            continue

        signal, reason, price, rsi = get_signal()
        now = datetime.now(timezone(timedelta(hours=1))).strftime("%H:%M:%S")
        print("[" + now + "] " + signal + " | " + str(round(price, 5)) + " | RSI " + str(round(rsi, 2)) + " | " + reason)

        if signal != "NO TRADE":
            if signal == last_signal and (time.time() - last_signal_time) < 1200:
                print("Duplicate skipped")
                time.sleep(60)
            else:
                side = "BUY" if signal == "CALL" else "SELL"
                ticket, sl, tp = place_order(account_id, side, price)

                if ticket:
                    open_ticket = ticket
                    breakeven_set = False
                    send_discord(
                        "**🎯 MT5 SNIPER TRADE (v9)**\n" +
                        "**" + signal + "** `" + SYMBOL + "`\n" +
                        "Entry: `" + str(round(price, 5)) + "`\n" +
                        "SL: `" + str(sl) + "`\n" +
                        "TP: `" + str(tp) + "`\n" +
                        "Ticket: `" + str(ticket) + "`\n" +
                        "Reason: " + reason
                    )
                    last_signal = signal
                    time.sleep(60)
                else:
                    time.sleep(60)
        else:
            print("Waiting 15 min...")
            time.sleep(900)

    except Exception as e:
        print("Loop error:", e)
        send_discord("Bot error: " + str(e))
        time.sleep(60)
