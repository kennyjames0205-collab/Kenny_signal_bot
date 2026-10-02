import yfinance as yf
import ta
import requests
import time
from datetime import datetime, timezone, timedelta

WEBHOOK = "https://discord.com/api/webhooks/1554026595134999709/hFnRH4FpaNJFFU-6DJmnbJYN_ecurCaSepyo5-_EOF4lYz3k9oVHHU6O6DeTVhoxWt4G"

def send_to_discord(msg):
    try:
        requests.post(WEBHOOK, json={"content": msg})
    except Exception as e:
        print("Discord error:", e)

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
    signal = "NO TRADE"
    reason = "Waiting for setup"
    uptrend = e20 > e50 > e200
    downtrend = e20 < e50 < e200
    if rsi_now > 64 and rsi_now < rsi_prev:
        signal = "🔴 PUT (DOWN)"
        reason = f"Overbought drop (RSI {rsi_prev:.1f} to {rsi_now:.1f})"
    elif rsi_now < 36 and rsi_now > rsi_prev:
        signal = "🟢 CALL (UP)"
        reason = f"Oversold bounce (RSI {rsi_prev:.1f} to {rsi_now:.1f})"
    elif uptrend and rsi_prev < 45 and rsi_now > rsi_prev and rsi_now < 65:
        signal = "🟢 CALL (UP)"
        reason = f"Uptrend + RSI rising ({rsi_prev:.1f} to {rsi_now:.1f})"
    elif downtrend and rsi_prev > 55 and rsi_now < rsi_prev and rsi_now > 35:
        signal = "🔴 PUT (DOWN)"
        reason = f"Downtrend + RSI falling ({rsi_prev:.1f} to {rsi_now:.1f})"
    else:
        reason = f"No clear setup (RSI {rsi_now:.1f})"
    return signal, reason, price, rsi_now

print("Signal bot started (cloud mode).")

while True:
    try:
        signal, reason, price, rsi = get_signal()
        now = datetime.now(timezone(timedelta(hours=1))).strftime("%H:%M:%S")
        print(f"[{now}] {signal} | Price: {price:.5f} | RSI: {rsi:.2f}")
        msg = (
            f"**EUR/USD M15**\n"
            f"**{signal}**\n"
            f"Price: `{price:.5f}`\n"
            f"RSI: `{rsi:.2f}`\n"
            f"Reason: {reason}\n"
            f"Time: {now}"
        )
        send_to_discord(msg)
        print("Waiting 15 minutes...\n")
        time.sleep(900)
    except Exception as e:
        print("Error:", e)
        time.sleep(60)
