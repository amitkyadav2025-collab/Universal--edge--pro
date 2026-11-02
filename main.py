from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas as pd
import numpy as np
import logging
import time

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Universal Edge Pro",
    version="1.0.0"
)

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD = BASE_DIR / "universal_edge_pro_prototype.html"

IST = ZoneInfo("Asia/Kolkata")

MARKETS = {
    "NIFTY 50": "^NSEI",
    "BANK NIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
}

CACHE = {}
CACHE_TTL_SECONDS = 15


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# =====================================================
# SYMBOL RESOLUTION
# =====================================================

def resolve_symbol(symbol="NIFTY 50"):

    raw = (symbol or "NIFTY 50").strip().upper()

    if raw in MARKETS:
        return raw, MARKETS[raw]

    cleaned = raw.replace(".NS", "")

    if cleaned and cleaned.replace("-", "").replace("&", "").isalnum():
        return cleaned, f"{cleaned}.NS"

    raise ValueError(
        "Unsupported symbol. Select NIFTY 50, BANK NIFTY, "
        "SENSEX or enter an NSE stock symbol."
    )


# =====================================================
# MARKET DATA
# =====================================================

def get_history(symbol, period="5d", interval="15m"):

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
        timeout=15
    )

    if data is None or data.empty:
        raise RuntimeError(
            "Yahoo Finance returned no candles. "
            "Market data may be temporarily unavailable."
        )

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close"]

    missing = [c for c in required if c not in data.columns]

    if missing:
        raise RuntimeError(
            f"Missing market data columns: {missing}"
        )

    data = data.dropna(subset=required)

    if data.empty:
        raise RuntimeError("No valid candles available.")

    CACHE[key] = {
        "time": now,
        "data": data.copy()
    }

    return data


# =====================================================
# TIME CONVERSION
# =====================================================

def convert_timestamp(ts):

    if getattr(ts, "tzinfo", None) is None:
        ts = ts.tz_localize("UTC")

    return ts.tz_convert(IST).isoformat()


# =====================================================
# TECHNICAL INDICATORS
# =====================================================

def calculate_indicators(df):

    df = df.copy()

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    open_ = df["Open"]

    # EMA
    df["EMA9"] = close.ewm(span=9, adjust=False).mean()
    df["EMA21"] = close.ewm(span=21, adjust=False).mean()
    df["EMA50"] = close.ewm(span=50, adjust=False).mean()

    # RSI
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(
        span=9,
        adjust=False
    ).mean()

    # ATR
    previous_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs()
        ],
        axis=1
    ).max(axis=1)

    df["ATR"] = tr.ewm(
        span=14,
        adjust=False
    ).mean()

    # Volume average
    if "Volume" in df.columns:
        df["VOLUME_AVG"] = df["Volume"].rolling(20).mean()
    else:
        df["VOLUME_AVG"] = 0

    return df


# =====================================================
# CANDLESTICK PATTERNS
# =====================================================

def detect_patterns(df):

    df = df.copy()

    o = df["Open"]
    h = df["High"]
    l = df["Low"]
    c = df["Close"]

    body = (c - o).abs()

    candle_range = (h - l).replace(0, np.nan)

    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)

    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l

    # Doji
    df["DOJI"] = (
        body <= candle_range * 0.10
    )

    # Hammer
    df["HAMMER"] = (
        (lower_wick >= body * 2) &
        (upper_wick <= body * 0.5) &
        (candle_range > 0)
    )

    # Shooting Star
    df["SHOOTING_STAR"] = (
        (upper_wick >= body * 2) &
        (lower_wick <= body * 0.5) &
        (candle_range > 0)
    )

    # Bullish Engulfing
    previous_open = o.shift(1)
    previous_close = c.shift(1)

    df["BULLISH_ENGULFING"] = (
        (previous_close < previous_open) &
        (c > o) &
        (o <= previous_close) &
        (c >= previous_open)
    )

    # Bearish Engulfing
    df["BEARISH_ENGULFING"] = (
        (previous_close > previous_open) &
        (c < o) &
        (o >= previous_close) &
        (c <= previous_open)
    )

    return df


# =====================================================
# SUPPORT AND RESISTANCE
# =====================================================

def calculate_support_resistance(df, window=20):

    recent = df.tail(window)

    support = float(recent["Low"].min())

    resistance = float(recent["High"].max())

    return {
        "support": round(support, 2),
        "resistance": round(resistance, 2)
    }


# =====================================================
# TREND ANALYSIS
# =====================================================

def get_trend(df):

    if len(df) < 50:
        return "WAIT"

    last = df.iloc[-1]

    ema9 = last["EMA9"]
    ema21 = last["EMA21"]
    ema50 = last["EMA50"]

    if ema9 > ema21 > ema50:
        return "BULLISH"

    if ema9 < ema21 < ema50:
        return "BEARISH"

    return "SIDEWAYS"


# =====================================================
# BUY / SELL SIGNAL ENGINE
# =====================================================

def generate_signals(df):

    df = calculate_indicators(df)

    df = detect_patterns(df)

    df["SIGNAL"] = "WAIT"

    df["TARGET1"] = np.nan
    df["TARGET2"] = np.nan
    df["STOPLOSS"] = np.nan

    df["REASON"] = ""

    resistance = df["High"].rolling(20).max().shift(1)

    support = df["Low"].rolling(20).min().shift(1)

    bullish_trend = (
        (df["EMA9"] > df["EMA21"]) &
        (df["EMA21"] > df["EMA50"])
    )

    bearish_trend = (
        (df["EMA9"] < df["EMA21"]) &
        (df["EMA21"] < df["EMA50"])
    )

    bullish_momentum = (
        (df["RSI"] > 50) &
        (df["MACD"] > df["MACD_SIGNAL"])
    )

    bearish_momentum = (
        (df["RSI"] < 50) &
        (df["MACD"] < df["MACD_SIGNAL"])
    )

    # Breakout
    breakout = (
        (df["Close"] > resistance) &
        bullish_trend &
        bullish_momentum
    )

    # Breakdown
    breakdown = (
        (df["Close"] < support) &
        bearish_trend &
        bearish_momentum
    )

    # Bullish candle patterns
    bullish_pattern = (
        df["HAMMER"] |
        df["BULLISH_ENGULFING"]
    )

    # Bearish candle patterns
    bearish_pattern = (
        df["SHOOTING_STAR"] |
        df["BEARISH_ENGULFING"]
    )

    # Entry conditions
    buy_condition = (
        bullish_trend &
        bullish_momentum &
        bullish_pattern
    ) | breakout

    sell_condition = (
        bearish_trend &
        bearish_momentum &
        bearish_pattern
    ) | breakdown

    df.loc[buy_condition, "SIGNAL"] = "BUY"

    df.loc[sell_condition, "SIGNAL"] = "SELL"

    df.loc[breakout, "REASON"] = "BREAKOUT"

    df.loc[breakdown, "REASON"] = "BREAKDOWN"

    df.loc[
        buy_condition & ~breakout,
        "REASON"
    ] = "BULLISH PATTERN"

    df.loc[
        sell_condition & ~breakdown,
        "REASON"
    ] = "BEARISH PATTERN"

    # Targets and stop loss
    atr = df["ATR"]

    buy_mask = df["SIGNAL"] == "BUY"

    sell_mask = df["SIGNAL"] == "SELL"

    df.loc[buy_mask, "TARGET1"] = (
        df.loc[buy_mask, "Close"] + atr[buy_mask] * 1.5
    )

    df.loc[buy_mask, "TARGET2"] = (
        df.loc[buy_mask, "Close"] + atr[buy_mask] * 2.5
    )

    df.loc[buy_mask, "STOPLOSS"] = (
        df.loc[buy_mask, "Close"] - atr[buy_mask] * 1.2
    )

    df.loc[sell_mask, "TARGET1"] = (
        df.loc[sell_mask, "Close"] - atr[sell_mask] * 1.5
    )

    df.loc[sell_mask, "TARGET2"] = (
        df.loc[sell_mask, "Close"] - atr[sell_mask] * 2.5
    )

    df.loc[sell_mask, "STOPLOSS"] = (
        df.loc[sell_mask, "Close"] + atr[sell_mask] * 1.2
    )

    return df


# =====================================================
# HOME DASHBOARD
# =====================================================

@app.get("/", response_class=HTMLResponse)
def home():

    if DASHBOARD.exists():

        return DASHBOARD.read_text(encoding="utf-8")

    return HTMLResponse(
        "<h2>Universal Edge Pro</h2>"
        "<p>Dashboard HTML missing.</p>",
        status_code=500
    )


# =====================================================
# HEALTH
# =====================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "version": "1.0.0"
    }


# =====================================================
# STATUS
# =====================================================

@app.get("/api/status")
def status():

    return {
        "backend": "ready",
        "version": "1.0.0",
        "data_provider": "Yahoo Finance",
        "supported_markets": list(MARKETS.keys()),
        "stock_search": "NSE symbols supported",
        "angelone_configured": False,
        "live_market_data": True,
        "signals_enabled": True,
        "historical_signals": True,
        "refresh_hint_seconds": 15,
        "note": (
            "Yahoo Finance data may be delayed or unavailable. "
            "Signals are algorithmic estimates, not guaranteed predictions."
        )
    }


# =====================================================
# STOCK SEARCH
# =====================================================

@app.get("/api/search")
def search_stocks(
    q: str = Query(..., min_length=1, max_length=40)
):

    try:

        result = yf.Search(
            q,
            max_results=8
        )

        quotes = getattr(result, "quotes", []) or []

        stocks = []

        for item in quotes:

            symbol = item.get("symbol", "")

            name = (
                item.get("shortname") or
                item.get("longname") or
                symbol
            )

            exchange = item.get("exchange", "")

            if symbol and (
                symbol.endswith(".NS") or
                exchange in ("NSI", "NSE")
            ):

                stocks.append({
                    "symbol": symbol,
                    "name": name,
                    "exchange": exchange
                })

        return {
            "query": q,
            "results": stocks[:8]
        }

    except Exception as exc:

        logging.exception("Stock search failed")

        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Stock search unavailable: {exc}"
            }
        )


# =====================================================
# LIVE PRICE
# =====================================================

@app.get("/api/nifty")
def nifty(
    symbol: str = Query(
        default="NIFTY 50",
        max_length=40
    )
):

    try:

        label, provider_symbol = resolve_symbol(symbol)

        data = get_history(
            provider_symbol,
            period="5d",
            interval="15m"
        )

        last = data.iloc[-1]

        previous = (
            data.iloc[-2]
            if len(data) > 1
            else last
        )

        price = float(last["Close"])

        prev_close = float(previous["Close"])

        ts = convert_timestamp(data.index[-1])

        return {
            "symbol": label,
            "provider_symbol": provider_symbol,
            "price": price,
            "previous_close": prev_close,
            "change": price - prev_close,
            "change_percent": (
                (price - prev_close) /
                prev_close * 100
            ) if prev_close else 0,
            "timestamp": ts,
            "source": "Yahoo Finance"
        }

    except Exception as exc:

        logging.exception("Price request failed")

        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Market data unavailable: {str(exc)}"
            }
        )


# =====================================================
# CANDLESTICK DATA
# =====================================================

@app.get("/api/candles")
def candles(
    symbol: str = Query(
        default="NIFTY 50",
        max_length=40
    ),

    days: int = Query(
        default=5,
        ge=1,
        le=30
    ),

    interval: str = Query(
        default="15m",
        pattern="^(5m|15m|30m|60m|1h)$"
    )
):

    try:

        label, provider_symbol = resolve_symbol(symbol)

        period = "5d" if days <= 5 else "1mo"

        yf_interval = (
            "60m"
            if interval == "1h"
            else interval
        )

        data = get_history(
            provider_symbol,
            period=period,
            interval=yf_interval
        )

        rows = []

        for timestamp, row in data.iterrows():

            rows.append([
                convert_timestamp(timestamp),
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"])
            ])

        return {
            "symbol": label,
            "provider_symbol": provider_symbol,
            "interval": interval,
            "candles": rows,
            "count": len(rows),
            "source": "Yahoo Finance",
            "last_timestamp": (
                rows[-1][0]
                if rows
                else None
            )
        }

    except Exception as exc:

        logging.exception("Candle request failed")

        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Candles unavailable: {str(exc)}"
            }
        )


# =====================================================
# HISTORICAL BUY / SELL SIGNALS
# =====================================================

@app.get("/api/signals")
def signals(
    symbol: str = Query(
        default="NIFTY 50",
        max_length=40
    ),

    interval: str = Query(
        default="5m",
        pattern="^(5m|15m|30m|60m|1h)$"
    ),

    days: int = Query(
        default=5,
        ge=1,
        le=30
    )
):

    try:

        label, provider_symbol = resolve_symbol(symbol)

        period = "5d" if days <= 5 else "1mo"

        yf_interval = (
            "60m"
            if interval == "1h"
            else interval
        )

        data = get_history(
            provider_symbol,
            period=period,
            interval=yf_interval
        )

        df = generate_signals(data)

        rows = []

        for timestamp, row in df.iterrows():

            signal = row["SIGNAL"]

            if signal not in ("BUY", "SELL"):
                continue

            rows.append({

                "time": convert_timestamp(timestamp),

                "price": round(
                    float(row["Close"]),
                    2
                ),

                "signal": signal,

                "reason": str(row["REASON"]),

                "target1": (
                    round(float(row["TARGET1"]), 2)
                    if pd.notna(row["TARGET1"])
                    else None
                ),

                "target2": (
                    round(float(row["TARGET2"]), 2)
                    if pd.notna(row["TARGET2"])
                    else None
                ),

                "stoploss": (
                    round(float(row["STOPLOSS"]), 2)
                    if pd.notna(row["STOPLOSS"])
                    else None
                )

                })

        last = df.iloc[-1]

        sr = calculate_support_resistance(df)

        return {

            "symbol": label,

            "interval": interval,

            "count": len(rows),

            "signals": rows,

            "latest_signal": (
                rows[-1]
                if rows
                else None
            ),

            "current_price": round(
                float(last["Close"]),
                2
            ),

            "trend": get_trend(df),

            "support": sr["support"],

            "resistance": sr["resistance"],

            "rsi": (
                round(float(last["RSI"]), 2)
                if pd.notna(last["RSI"])
                else None
            ),

            "source": "Yahoo Finance",

            "note": (
                "Algorithmic signals for educational purposes. "
                "Not guaranteed trading recommendations."
            )

        }

    except Exception as exc:

        logging.exception("Signal generation failed")

        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Signals unavailable: {str(exc)}"
            }
        )


# =====================================================
# MULTI-TIMEFRAME TREND
# =====================================================

@app.get("/api/trend")
def multi_timeframe_trend(
    symbol: str = Query(
        default="NIFTY 50",
        max_length=40
    )
):

    try:

        label, provider_symbol = resolve_symbol(symbol)

        results = {}

        timeframes = {
            "5M": "5m",
            "15M": "15m",
            "1H": "60m"
        }

        for name, interval in timeframes.items():

            data = get_history(
                provider_symbol,
                period="5d",
                interval=interval
            )

            df = calculate_indicators(data)

            results[name] = get_trend(df)

        return {

            "symbol": label,

            "timeframes": results,

            "note": (
                "Multi-timeframe trend analysis. "
                "Confirm signals independently."
            )

        }

    except Exception as exc:

        logging.exception("Trend request failed")

        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Trend unavailable: {str(exc)}"
            }
        )


# =====================================================
# RUN
# =====================================================

# Render uses its configured start command:
# uvicorn main:app --host 0.0.0.0 --port $PORT
