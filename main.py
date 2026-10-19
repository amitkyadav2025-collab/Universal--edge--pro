import os
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="Universal Edge Pro", version="0.2.0")

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD = BASE_DIR / "universal_edge_pro_prototype.html"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
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
    return {
        "ok": True,
        "time_utc": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/status")
def api_status():
    return {
        "backend": "ready",
        "angelone_configured": bool(os.getenv("ANGELONE_API_KEY")),
        "live_market_data": False,
        "note": "Live Angel One integration is not implemented yet."
    }
