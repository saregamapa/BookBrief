"""Custom middleware for BookBrief AI.

Includes:
- RequestIDMiddleware: generates / echoes X-Request-ID for tracing
- SecurityHeadersMiddleware: adds OWASP-recommended HTTP security headers
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Paths that serve HTML pages (need CSP); everything else can be stricter.
_HTML_CONTENT_TYPES = {"text/html"}

# API path prefixes whose responses should never be cached by browsers / proxies.
_NO_CACHE_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/summaries",
    "/api/v1/stripe",
    "/api/v1/user",
    # Legacy (no-version) paths kept for safety during transition
    "/auth",
    "/summaries",
    "/stripe",
    "/user",
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Echo (or generate) an X-Request-ID header on every request/response.

    If the caller supplies an ``X-Request-ID`` header we echo it back unchanged
    so distributed-tracing systems can correlate upstream and downstream spans.
    Otherwise we generate a random UUID v4 and attach it.  The ID is also
    stored in ``request.state.request_id`` so routers and background tasks can
    include it in structured log lines.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects HTTP security headers on every response.

    Headers applied:
        X-Content-Type-Options    : prevents MIME-type sniffing
        X-Frame-Options           : prevents clickjacking
        X-XSS-Protection          : legacy XSS filter (belt-and-suspenders)
        Referrer-Policy           : limits referrer leakage
        Permissions-Policy        : disables dangerous browser features
        Content-Security-Policy   : restricts resource origins for HTML pages
        Strict-Transport-Security : HSTS for HTTPS deployments (set by Render)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        # Always-on headers
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )

        # HSTS — only sent over HTTPS; Render terminates TLS so forward-proxied
        # requests are effectively HTTPS in production.
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )

        # CSP — allow Tailwind CDN, Google Fonts, and same-origin scripts/styles.
        # Tighten further once Tailwind is bundled locally.
        content_type = response.headers.get("content-type", "")
        if any(ct in content_type for ct in _HTML_CONTENT_TYPES):
            response.headers.setdefault(
                "Content-Security-Policy",
                (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
                    "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com; "
                    "font-src 'self' https://fonts.gstatic.com data:; "
                    "img-src 'self' data: https:; "
                    "media-src 'self' data: https: blob:; "
                    "connect-src 'self'; "
                    "frame-src 'self' https: data: blob:; "
                    "frame-ancestors 'none'; "
                    "base-uri 'self'; "
                    "form-action 'self' https://checkout.stripe.com;"
                ),
            )

        # Prevent caching of authenticated API responses
        if request.url.path.startswith(_NO_CACHE_PREFIXES):
            response.headers.setdefault(
                "Cache-Control", "no-store, no-cache, must-revalidate, private"
            )

        return response
