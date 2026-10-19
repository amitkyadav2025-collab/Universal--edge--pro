# Universal Edge Pro — backend starter

This is a small starter API for deploying a backend service. It does **not** connect to Angel One and does **not** provide live market data or trading signals.

## Render settings
- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

## Important
- Do not put broker API keys, passwords, OTPs, or TOTP secrets in frontend HTML or in chat.
- This starter has permissive CORS for testing only. Before production, restrict `allow_origins` to your exact dashboard domain.
- Angel One SmartAPI integration requires checking current API requirements and securely storing credentials as server-side environment variables.
- Never use demo output for trading decisions.
