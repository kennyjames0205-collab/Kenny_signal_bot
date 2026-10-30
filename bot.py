import os
import time
import requests
from datetime import datetime, timezone

# --- CONFIGURATION ---
TICKERALL_KEY = os.environ.get("TICKERALL_KEY")
MT5_ACCOUNT = int(os.environ.get("MT5_ACCOUNT", 0))
MT5_SERVER = os.environ.get("MT5_SERVER")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD")
DISCORD_WEBHOOK = os.environ.get("WEBHOOK_URL")

# PASTE YOUR FULL TWELVEDATA KEY HERE INSIDE THE QUOTES
TWELVEDATA_KEY = "ab9054239e1c440f82ae43..." 

SYMBOL = "EURUSDm"
VOLUME = 0.01
BASE = "https://api.tickerall.com"

PIP = 0.0001
SL_PIPS = 5
TP_PIPS = 10

def send_discord(msg):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg})
    except Exception:
        pass

def make_headers():
    return {"Authorization": "Bearer " + str(TICKERALL_KEY)}

def start_session():
    data = {"broker": "mt5", "server": MT5_SERVER, "account": MT5_ACCOUNT, "password": MT5_PASSWORD}
    try:
        r = requests.post(BASE + "/v1/session", json=data, headers=make_headers())
        
        # --- NEW DEBUGGING LOGIC ---
        if r.status_code in (200, 201):
            return r.json().get("session_id")
        else:
            # This will print the exact error from TickerAll to Railway logs
            print(f"❌ TICKERALL ERROR: Status {r.status_code} | Message: {r.text}")
            return None
        # ---------------------------
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return None

def place_order(account_id, side, entry_price, volume):
    if side == "BUY":
        sl = round(entry_price - (SL_PIPS * PIP), 5)
        tp = round(entry_price + (TP_PIPS * PIP), 5)
    else:
        sl = round(entry_price + (SL_PIPS * PIP), 5)
        tp = round(entry_price - (TP_PIPS * PIP), 5)

    data = {"type": "market", "symbol": SYMBOL, "side": side, "volume": volume, "sl": sl, "tp": tp}
    try:
        r = requests.post(BASE + "/v1/account/" + str(account_id) + "/order", json=data, headers=make_headers())
        if r.status_code in (200, 201):
            return r.json().get("ticket"), sl, tp
        else:
            print("Order failed:", r.status_code, r.text)
    except Exception as e:
        print("Order error:", e)
    return None, None, None

def calculate_ema(prices, period):
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def get_signal():
    # Fetching 5min candles to reduce noise
    url = f"https://api.twelvedata.com/time_series?symbol={SYMBOL}&interval=5min&outputsize=50&apikey={TWELVEDATA_KEY}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if "values" not in data:
            return "NO TRADE", "API Limit or Error", None
        
        prices = [float(v["close"]) for v in data["values"]][::-1]
        
        ema_fast = calculate_ema(prices, 9)
        ema_slow = calculate_ema(prices, 21)
        
        current_price = prices[-1]
        
        if ema_fast > ema_slow:
            return "CALL", "Momentum BUY", current_price
        elif ema_fast < ema_slow:
            return "PUT", "Momentum SELL", current_price
            
        return "NO TRADE", "No EMA Cross", None
    except Exception as e:
        return "NO TRADE", f"Error: {e}", None

# --- MAIN LOOP ---
def main():
    print("Starting Kenny Signal Bot v22...")
    session_id = None
    last_trade_time = 0
    
    while True:
        try:
            if not session_id:
                session_id = start_session()
                if not session_id:
                    print("Failed to start TickerAll session. Retrying...")
                    time.sleep(10)
                    continue

            # --- V22 SESSION & LONDON FAKEOUT FILTER ---
            now_utc = datetime.now(timezone.utc)
            current_hour = now_utc.hour
            current_minute = now_utc.minute

            # 1. Overall Session Filter (8:00 AM to 5:00 PM UTC)
            if current_hour < 8 or current_hour >= 17:
                print(f"[{current_hour:02d}:{current_minute:02d}] Outside main session. Sleeping...")
                time.sleep(300)
                continue

            # 2. The London Fakeout Block (08:00 AM to 09:30 AM UTC)
            if current_hour == 8 or (current_hour == 9 and current_minute < 30):
                print(f"[{current_hour:02d}:{current_minute:02d}] LONDON FAKEOUT TRAP. Bot paused.")
                time.sleep(60)
                continue
            # -------------------------------------------

            # 3. Cooldown (Wait at least 5 minutes between trades)
            if time.time() - last_trade_time < 300:
                print("Cooldown active. Waiting 60 seconds...")
                time.sleep(60)
                continue

            # Get Signal
            signal, reason, price = get_signal()
            now_str = now_utc.strftime("%H:%M:%S")
            print(f"[{now_str}] {signal} | {reason} | Price: {price}")

            if signal != "NO TRADE" and price:
                side = "BUY" if signal == "CALL" else "SELL"
                ticket, sl, tp = place_order(MT5_ACCOUNT, side, price, VOLUME)
                
                if ticket:
                    send_discord(f"⚡ **Action Taken:** {side} {SYMBOL}\nPrice: {price}\nSL: {sl} | TP: {tp}")
                    last_trade_time = time.time()
                    time.sleep(60)
                else:
                    time.sleep(60)
            else:
                time.sleep(60)

        except Exception as e:
            print("Main Loop Error:", e)
            time.sleep(60)

if __name__ == "__main__":
    main()
