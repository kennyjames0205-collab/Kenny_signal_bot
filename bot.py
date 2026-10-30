import os
import time
import requests
from datetime import datetime, timezone
from tickerall import Tickerall

# --- CONFIGURATION ---
TICKERALL_KEY = os.environ.get("TICKERALL_KEY")
MT5_ACCOUNT = int(os.environ.get("MT5_ACCOUNT", 0))
MT5_SERVER = os.environ.get("MT5_SERVER")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD")
DISCORD_WEBHOOK = os.environ.get("WEBHOOK_URL")

# Full TwelveData Key
TWELVEDATA_KEY = "ab9054239e1c440f82ae43d470fc80dc"

SYMBOL = "EURUSDm"
VOLUME = 0.01

PIP = 0.0001
SL_PIPS = 5
TP_PIPS = 10
RESISTANCE_BUFFER = 0.00020 # 2 pips

def send_discord(msg):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg})
    except Exception:
        pass

# Initialize the official TickerAll client
client = Tickerall(api_key=TICKERALL_KEY)

def start_session():
    try:
        session = client.sessions.start(
            broker="mt5",
            server=MT5_SERVER,
            account=MT5_ACCOUNT,
            password=MT5_PASSWORD
        )
        print(f"✅ Connected to MT5! Account ID: {session.account_id}")
        return session.account_id
    except Exception as e:
        print(f"❌ TICKERALL ERROR: {e}")
        return None

def place_order(account_id, side, entry_price, volume):
    if side == "BUY":
        sl = round(entry_price - (SL_PIPS * PIP), 5)
        tp = round(entry_price + (TP_PIPS * PIP), 5)
    else:
        sl = round(entry_price + (SL_PIPS * PIP), 5)
        tp = round(entry_price - (TP_PIPS * PIP), 5)

    try:
        order = client.orders.place(
            account_id,
            type="market",
            symbol=SYMBOL,
            side=side,
            volume=volume,
            stop_loss=sl,
            take_profit=tp
        )
        return order.ticket, sl, tp
    except Exception as e:
        print(f"Order error: {e}")
        return None, None, None

def calculate_ema(prices, period):
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def get_signal():
    # We need 30 candles to calculate EMA 21 and look for recent highs/lows
    url = f"https://api.twelvedata.com/time_series?symbol=EUR/USD&interval=1min&outputsize=30&apikey={TWELVEDATA_KEY}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        
        if "values" not in data:
            print(f"🚨 TWELVEDATA RAW ERROR: {data}")
            return "NO TRADE", "API Limit or Error", None
        
        # We extract both close prices (for EMA) and high/low prices (for Support/Resistance)
        closes = [float(v["close"]) for v in data["values"]][::-1]
        highs = [float(v["high"]) for v in data["values"]][::-1]
        lows = [float(v["low"]) for v in data["values"]][::-1]
        
        ema_fast = calculate_ema(closes, 9)
        ema_slow = calculate_ema(closes, 21)
        
        current_price = closes[-1]
        
        # Find the highest and lowest price of the last 20 candles
        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])

        # --- V23 RESISTANCE & SUPPORT LOGIC ---
        
        # 1. BUY Signal (EMA cross UP)
        if ema_fast > ema_slow:
            # Check if we are too close to the ceiling (Resistance)
            if current_price >= (recent_high - RESISTANCE_BUFFER):
                return "NO TRADE", "Blocked: Too close to Resistance", current_price
            return "CALL", "Momentum BUY", current_price
            
        # 2. SELL Signal (EMA cross DOWN)
        elif ema_fast < ema_slow:
            # Check if we are too close to the floor (Support)
            if current_price <= (recent_low + RESISTANCE_BUFFER):
                return "NO TRADE", "Blocked: Too close to Support", current_price
            return "PUT", "Momentum SELL", current_price
            
        return "NO TRADE", "No EMA Cross", None
    except Exception as e:
        return "NO TRADE", f"Error: {e}", None

# --- MAIN LOOP ---
def main():
    print("Starting Kenny Signal Bot v23...")
    account_id = None
    last_trade_time = 0
    
    while True:
        try:
            if not account_id:
                account_id = start_session()
                if not account_id:
                    print("Failed to start TickerAll session. Retrying in 10s...")
                    time.sleep(10)
                    continue

            # --- SESSION & LONDON FAKEOUT FILTER ---
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
            
            # 3. Cooldown (Wait at least 15 minutes between trades)
            if time.time() - last_trade_time < 900:
                print("Cooldown active (15 mins). Waiting 60 seconds...")
                time.sleep(60)
                continue

            # Get Signal
            signal, reason, price = get_signal()
            now_str = now_utc.strftime("%H:%M:%S")
            print(f"[{now_str}] {signal} | {reason} | Price: {price}")

            if signal != "NO TRADE" and price:
                side = "BUY" if signal == "CALL" else "SELL"
                ticket, sl, tp = place_order(account_id, side, price, VOLUME)
                
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
