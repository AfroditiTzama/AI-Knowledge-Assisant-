import asyncio
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from uuid import UUID

import jwt
from fastapi import status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from knowledge_assistant.core.config import get_settings
from knowledge_assistant.domain.auth.security import secrets_match
from knowledge_assistant.infrastructure.auth.jwt_token_service import (
    JWTTokenService,
)
from knowledge_assistant.infrastructure.database.repositories.auth_repository import (
    SQLAlchemyAuthRepository,
)
from knowledge_assistant.infrastructure.database.session import (
    AsyncSessionFactory,
)
from knowledge_assistant.presentation.middleware.client_ip import (
    resolve_client_ip,
)


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    _LIMITED_PATHS = {
        "/auth/login",
        "/auth/register",
        "/auth/password-reset/request",
        "/auth/password-reset/confirm",
        "/auth/email-verification/request",
    }

    def __init__(
        self,
        app,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(app)
        settings = get_settings()
        self._limit = settings.auth_rate_limit_requests
        self._window = settings.auth_rate_limit_window_seconds
        self._max_keys = settings.auth_rate_limit_max_keys
        self._trusted_proxy_networks = settings.trusted_proxy_networks
        self._clock = clock
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path not in self._LIMITED_PATHS:
            return await call_next(request)

        client_ip = resolve_client_ip(
            request,
            self._trusted_proxy_networks,
        )
        key = f"{request.url.path}:{client_ip}"
        now = self._clock()

        async with self._lock:
            self._prune_expired(now)
            bucket = self._requests.get(key)
            if bucket is None:
                if len(self._requests) >= self._max_keys:
                    self._requests.popitem(last=False)
                bucket = deque()
                self._requests[key] = bucket
            else:
                self._requests.move_to_end(key)

            while bucket and now - bucket[0] >= self._window:
                bucket.popleft()
            if len(bucket) >= self._limit:
                retry_after = max(
                    1,
                    int(self._window - (now - bucket[0])),
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": (
                            "Too many requests. Please wait before trying again."
                        )
                    },
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

        return await call_next(request)

    def _prune_expired(self, now: float) -> None:
        expired_keys = [
            key
            for key, bucket in self._requests.items()
            if not bucket or now - bucket[-1] >= self._window
        ]
        for key in expired_keys:
            del self._requests[key]


class CSRFMiddleware(BaseHTTPMiddleware):
    _SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    _EXEMPT_PATHS = {
        "/auth/login",
        "/auth/register",
        "/auth/password-reset/request",
        "/auth/password-reset/confirm",
        "/auth/email-verification/confirm",
    }
    _REFRESH_CSRF_PATHS = {"/auth/refresh", "/auth/logout"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if (
            request.method in self._SAFE_METHODS
            or request.url.path in self._EXEMPT_PATHS
        ):
            return await call_next(request)

        settings = get_settings()
        access_token = request.cookies.get(settings.access_cookie_name)
        refresh_token = request.cookies.get(settings.refresh_cookie_name)
        use_refresh_token = (
            request.url.path in self._REFRESH_CSRF_PATHS
            and refresh_token is not None
        )
        if not use_refresh_token and self._has_bearer_credentials(request):
            return await call_next(request)

        cookie_token = refresh_token if use_refresh_token else access_token
        if not cookie_token:
            return await call_next(request)

        csrf_token = request.headers.get("x-csrf-token")
        if not csrf_token:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "CSRF token was not provided."},
            )

        try:
            payload = JWTTokenService().verify_token(cookie_token)
            expected_type = "refresh" if use_refresh_token else "access"
            if payload.get("type") != expected_type:
                raise ValueError("unexpected token type")
            session_id = UUID(str(payload.get("sid")))
        except (jwt.PyJWTError, ValueError, TypeError):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Session token is invalid or expired."},
            )

        async with AsyncSessionFactory() as session:
            repository = SQLAlchemyAuthRepository(session)
            auth_session = await repository.get_session(session_id)

        if (
            auth_session is None
            or not auth_session.is_active()
            or not secrets_match(
                csrf_token,
                auth_session.csrf_token_hash,
            )
        ):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "CSRF token is invalid."},
            )

        return await call_next(request)

    @staticmethod
    def _has_bearer_credentials(request: Request) -> bool:
        authorization = request.headers.get("authorization", "")
        scheme, separator, credentials = authorization.partition(" ")
        return (
            bool(separator)
            and scheme.casefold() == "bearer"
            and bool(credentials.strip())
        )
