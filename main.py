import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pyotp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from SmartApi import SmartConnect

app = FastAPI(title="Universal Edge Pro", version="0.3.0")

BASE_DIR = Path(file).resolve().parent
DASHBOARD = BASE_DIR / "universal_edge_pro_prototype.html"
TZ = ZoneInfo("Asia/Kolkata")

app.add_middleware(
CORSMiddleware,
allow_origins=[""],
allow_credentials=False,
allow_methods=["GET"],
allow_headers=[""],
)

def get_client():
api_key = os.getenv("ANGELONE_API_KEY")
client_code = os.getenv("ANGELONE_CLIENT_CODE")
pin = os.getenv("ANGELONE_PIN")
totp_secret = os.getenv("ANGELONE_TOTP_SECRET")

if not all([api_key, client_code, pin, totp_secret]):
    raise HTTPException(
        status_code=503,
        detail="Angel One credentials are not configured in Render."
    )

try:
    client = SmartConnect(api_key=api_key)
    otp = pyotp.TOTP(totp_secret).now()
    result = client.generateSession(client_code, pin, otp)

    if not result or not result.get("status"):
        raise HTTPException(
            status_code=502,
            detail="Angel One login failed. Check credentials and API access."
        )

    return client
except HTTPException:
    raise
except Exception:
    raise HTTPException(
        status_code=502,
        detail="Could not connect to Angel One. Check configuration and logs."
    )

@app.get("/")
def root():
if DASHBOARD.exists():
return FileResponse(DASHBOARD, media_type="text/html")
return {
"status": "error",
"message": "Dashboard HTML file not found."
}

@app.get("/health")
def health():
return {"ok": True, "time": datetime.now(TZ).isoformat()}

@app.get("/api/status")
def api_status():
configured = all(os.getenv(key) for key in [
"ANGELONE_API_KEY",
"ANGELONE_CLIENT_CODE",
"ANGELONE_PIN",
"ANGELONE_TOTP_SECRET",
])
return {
"backend": "ready",
"angelone_configured": configured,
"live_market_data": "not_tested",
"message": (
"Credentials configured; test a market endpoint."
if configured else
"Add Angel One credentials in Render Environment."
),
}

@app.get("/api/nifty")
def nifty_ltp():
client = get_client()
try:
result = client.ltpData("NSE", "Nifty 50", "99926000")
if not result or not result.get("status"):
raise HTTPException(
status_code=502,
detail="Angel One did not return Nifty 50 LTP."
)
return {
"symbol": "NIFTY 50",
"data": result.get("data"),
"source": "Angel One SmartAPI",
}
except HTTPException:
raise
except Exception:
raise HTTPException(
status_code=502,
detail="Nifty 50 quote request failed."
)
finally:
try:
client.terminateSession(os.getenv("ANGELONE_CLIENT_CODE"))
except Exception:
pass

@app.get("/api/candles")
def nifty_candles(days: int = 5):
if days < 1 or days > 30:
raise HTTPException(status_code=400, detail="days must be 1 to 30")

client = get_client()
now = datetime.now(TZ)
start = now - timedelta(days=days)

params = {
    "exchange": "NSE",
    "symboltoken": "99926000",
    "interval": "FIFTEEN_MINUTE",
    "fromdate": start.strftime("%Y-%m-%d %H:%M"),
    "todate": now.strftime("%Y-%m-%d %H:%M"),
}

try:
    result = client.getCandleData(params)
    if not result or not result.get("status"):
        raise HTTPException(
            status_code=502,
            detail="Historical candle request failed."
        )
    return {
        "symbol": "NIFTY 50",
        "interval": "15-minute",
        "candles": result.get("data", []),
        "source": "Angel One SmartAPI",
    }
except HTTPException:
    raise
except Exception:
    raise HTTPException(
        status_code=502,
        detail="Could not retrieve Nifty 50 candles."
    )
finally:
    try:
        client.terminateSession(os.getenv("ANGELONE_CLIENT_CODE"))
    except Exception:
        pass
