from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas as pd
import logging
import time

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Universal Edge Pro", version="0.5.0")

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD = BASE_DIR / "universal_edge_pro_prototype.html"
IST = ZoneInfo("Asia/Kolkata")

# Yahoo Finance symbols (unofficial source; may be delayed/rate-limited)
MARKETS = {
    "NIFTY 50": "^NSEI",
    "BANK NIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
}
CACHE = {}
CACHE_TTL_SECONDS = 12

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

def resolve_symbol(symbol: str = "NIFTY 50") -> tuple[str, str]:
    raw = (symbol or "NIFTY 50").strip().upper()
    if raw in MARKETS:
        return raw, MARKETS[raw]
    # Allow common Indian equity symbols, e.g. RELIANCE, TCS, INFY
    cleaned = raw.replace(".NS", "")
    if cleaned and cleaned.replace("-", "").replace("&", "").isalnum():
        return cleaned, f"{cleaned}.NS"
    raise ValueError("Unsupported symbol. Select NIFTY 50, BANK NIFTY, SENSEX or enter an NSE stock symbol.")

def get_history(symbol: str, period: str = "5d", interval: str = "15m"):
    key = (symbol, period, interval)
    now = time.time()
    cached = CACHE.get(key)
    if cached and now - cached["time"] < CACHE_TTL_SECONDS:
        return cached["data"].copy()

    data = yf.download(
        tickers=symbol,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
        timeout=15,
    )
    if data is None or data.empty:
        raise RuntimeError("Yahoo Finance returned no candles. It may be temporarily unavailable.")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise RuntimeError(f"Yahoo Finance response missing columns: {', '.join(missing)}")

    data = data.dropna(subset=required)
    if data.empty:
        raise RuntimeError("No valid OHLC candles were returned.")

    CACHE[key] = {"time": now, "data": data.copy()}
    return data

@app.get("/", response_class=HTMLResponse)
def home():
    if DASHBOARD.exists():
        return DASHBOARD.read_text(encoding="utf-8")
    return HTMLResponse(
        "<h2>Universal Edge Pro</h2><p>Dashboard HTML missing. "
        "Upload universal_edge_pro_prototype.html to the repository.</p>",
        status_code=500,
    )

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.5.0"}

@app.get("/api/status")
def status():
    return {
        "backend": "ready",
        "data_provider": "Yahoo Finance (unofficial)",
        "supported_markets": list(MARKETS.keys()),
        "stock_search": "Enter NSE ticker symbol (example: RELIANCE, TCS, INFY)",
        "angelone_configured": False,
        "live_market_data": True,
        "refresh_hint_seconds": 5,
        "note": (
            "Yahoo Finance data can be delayed, rate-limited, or unavailable. "
            "A 5-second dashboard refresh does not guarantee real-time exchange ticks."
        ),
    }

@app.get("/api/search")
def search_stocks(q: str = Query(..., min_length=1, max_length=40)):
    try:
        result = yf.Search(q, max_results=8)
        quotes = getattr(result, "quotes", []) or []
        stocks = []
        for item in quotes:
            symbol = item.get("symbol", "")
            name = item.get("shortname") or item.get("longname") or symbol
            exchange = item.get("exchange", "")
            if symbol and (symbol.endswith(".NS") or exchange in ("NSI", "NSE")):
                stocks.append({"symbol": symbol, "name": name, "exchange": exchange})
        return {"query": q, "results": stocks[:8]}
    except Exception as exc:
        logging.exception("Stock search failed")
        return JSONResponse(status_code=503, content={"detail": f"Stock search unavailable: {exc}"})

@app.get("/api/nifty")
def nifty(symbol: str = Query(default="NIFTY 50", max_length=40)):
    try:
        label, provider_symbol = resolve_symbol(symbol)
        data = get_history(provider_symbol, period="5d", interval="15m")
        last = data.iloc[-1]
        previous = data.iloc[-2] if len(data) > 1 else last
        price = float(last["Close"])
        prev_close = float(previous["Close"])
        ts = data.index[-1]
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.tz_localize("UTC")
        ts = ts.tz_convert(IST)
        return {
            "symbol": label,
            "provider_symbol": provider_symbol,
            "price": price,
            "previous_close": prev_close,
            "change": price - prev_close,
            "change_percent": ((price - prev_close) / prev_close * 100) if prev_close else 0,
            "timestamp": ts.isoformat(),
            "source": "Yahoo Finance (unofficial)",
        }
    except Exception as exc:
        logging.exception("Price request failed")
        return JSONResponse(status_code=503, content={"detail": f"Market data unavailable: {str(exc)}"})

@app.get("/api/candles")
def candles(
    symbol: str = Query(default="NIFTY 50", max_length=40),
    days: int = Query(default=5, ge=1, le=30),
    interval: str = Query(default="15m", pattern="^(5m|15m|30m|60m|1h)$"),
):
    try:
        label, provider_symbol = resolve_symbol(symbol)
        # Yahoo intraday period availability is limited. Keep requests conservative.
        period = "5d" if days <= 5 else "1mo"
        yf_interval = "60m" if interval == "1h" else interval
        data = get_history(provider_symbol, period=period, interval=yf_interval)

        rows = []
        for timestamp, row in data.iterrows():
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
            "symbol": label,
            "provider_symbol": provider_symbol,
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
