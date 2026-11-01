from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Universal Edge Pro", version="0.4.0")

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD = BASE_DIR / "universal_edge_pro_prototype.html"
SYMBOL = "^NSEI"  # Yahoo Finance symbol for NIFTY 50
IST = ZoneInfo("Asia/Kolkata")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

def get_nifty_history(period="5d", interval="15m"):
    """Fetch unofficial Yahoo Finance NIFTY 50 candles. No API key required."""
    data = yf.download(
        tickers=SYMBOL,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
        timeout=15,
    )
    if data is None or data.empty:
        raise RuntimeError("Yahoo Finance returned no candles. It may be temporarily unavailable.")
    # yfinance sometimes returns MultiIndex columns even for a single ticker
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    return data

@app.get("/", response_class=HTMLResponse)
def home():
    if DASHBOARD.exists():
        return DASHBOARD.read_text(encoding="utf-8")
    return HTMLResponse(
        "<h2>Universal Edge Pro</h2>"
        "<p>Dashboard HTML file is missing. Upload "
        "universal_edge_pro_prototype.html to the repository.</p>",
        status_code=500,
    )

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.4.0"}

@app.get("/api/status")
def status():
    return {
        "backend": "ready",
        "data_provider": "Yahoo Finance",
        "symbol": SYMBOL,
        "angelone_configured": False,
        "live_market_data": True,
        "note": (
            "Yahoo Finance is an unofficial source; data may be delayed, "
            "rate-limited, or temporarily unavailable. Verify timestamps."
        ),
    }

@app.get("/api/nifty")
def nifty():
    try:
        data = get_nifty_history(period="5d", interval="15m")
        last = data.iloc[-1]
        previous = data.iloc[-2] if len(data) > 1 else last
        price = float(last["Close"])
        prev_close = float(previous["Close"])
        return {
            "symbol": "NIFTY 50",
            "provider_symbol": SYMBOL,
            "price": price,
            "previous_close": prev_close,
            "change": price - prev_close,
            "change_percent": ((price - prev_close) / prev_close * 100) if prev_close else 0,
            "timestamp": str(data.index[-1]),
            "source": "Yahoo Finance (unofficial)",
        }
    except Exception as exc:
        logging.exception("Nifty price request failed")
        return JSONResponse(
            status_code=503,
            content={"detail": f"Yahoo Finance data unavailable: {str(exc)}"},
        )

@app.get("/api/candles")
def candles(
    days: int = Query(default=5, ge=1, le=30),
    interval: str = Query(default="15m", pattern="^(5m|15m|30m|60m|1h)$"),
):
    # Yahoo Finance intraday history is limited; keep requests conservative.
    period = "5d" if days <= 5 else "1mo"
    yf_interval = "60m" if interval == "1h" else interval
    try:
        data = get_nifty_history(period=period, interval=yf_interval)
        rows = []
        for timestamp, row in data.iterrows():
            # Return ISO timestamp and numeric OHLC; existing dashboard accepts this.
            ts = timestamp
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.tz_localize("UTC")
            ts = ts.tz_convert(IST)
            rows.append([
                ts.isoformat(),
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
            ])
        return {
            "symbol": "NIFTY 50",
            "interval": interval,
            "candles": rows,
            "count": len(rows),
            "source": "Yahoo Finance (unofficial)",
            "last_timestamp": rows[-1][0] if rows else None,
        }
    except Exception as exc:
        logging.exception("Candle request failed")
        return JSONResponse(
            status_code=503,
            content={"detail": f"Yahoo Finance candles unavailable: {str(exc)}"},
        )
