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
