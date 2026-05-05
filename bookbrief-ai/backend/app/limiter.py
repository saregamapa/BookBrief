"""Rate-limiting configuration for BookBrief AI.

Uses slowapi (a Starlette-compatible wrapper around limits/ratelimit).

Usage in a router:
    from app.limiter import limiter, rate_auth, rate_api

    @router.post("/login")
    @rate_auth          # strict — brute-force protection
    async def login(request: Request, ...): ...

    @router.get("/summaries")
    @rate_api           # standard authenticated API calls
    async def list_summaries(request: Request, ...): ...

The `limiter` instance must also be added to the FastAPI app via
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
Both are wired in main.py already.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# ── Limiter instance ────────────────────────────────────────────────────────
# key_func: identifies the "caller" — IP address for all requests.
# For authenticated endpoints you could swap in a user-id extractor, but
# IP is fine here because most limits are per-IP on auth endpoints.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],  # global fallback
)

# ── Named limit presets ─────────────────────────────────────────────────────
# Apply these as decorators ABOVE the route function, BELOW @router.post/get.
# Each is a partial — slowapi resolves them lazily so the string form is fine.

# Auth endpoints: login, register, password-reset — prevent brute force
rate_auth = limiter.limit("10 per minute")

# Summarise / AI endpoints — expensive; throttle hard
rate_ai = limiter.limit("5 per minute; 30 per hour")

# Standard read/write API — authenticated CRUD, search, etc.
rate_api = limiter.limit("60 per minute")

# Stripe webhook — Stripe replays, be generous; DoS is handled upstream
rate_webhook = limiter.limit("120 per minute")

# Health-check / status — called by uptime monitors every 30 s
rate_health = limiter.limit("10 per second")
