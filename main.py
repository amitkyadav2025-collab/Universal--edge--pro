import os
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Universal Edge Pro API", version="0.1.0")

# Prototype API only. No broker credentials are used or accepted in browser code.
# Restrict CORS to your published dashboard domain before production use.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with your exact dashboard origin for production.
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "service": "Universal Edge Pro API",
        "status": "running",
        "live_market_data": False,
        "message": "Starter backend only; not connected to Angel One or live prices."
    }

@app.get("/health")
def health():
    return {"ok": True, "time_utc": datetime.now(timezone.utc).isoformat()}

@app.get("/api/status")
def api_status():
    # Deliberately does not pretend to provide live data.
    configured = bool(os.getenv("ANGELONE_API_KEY"))
    return {
        "backend": "ready",
        "angelone_configured": configured,
        "live_market_data": False,
        "note": "Angel One integration is not implemented in this starter."
    }
