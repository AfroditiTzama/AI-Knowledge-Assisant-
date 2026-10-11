from ipaddress import ip_network
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request
from starlette.responses import Response

from knowledge_assistant.bootstrap.dependencies.user import (
    get_authenticated_request,
)
from knowledge_assistant.core.config import Settings
from knowledge_assistant.domain.auth.security import hash_secret
from knowledge_assistant.domain.common.exceptions import AuthenticationError
from knowledge_assistant.infrastructure.openrouter_errors import (
    OPENROUTER_PUBLIC_ERROR,
    raise_openrouter_request_error,
)
from knowledge_assistant.presentation.middleware.client_ip import (
    resolve_client_ip,
)
from knowledge_assistant.presentation.middleware.security import (
    AuthRateLimitMiddleware,
    CSRFMiddleware,
)

TEST_JWT_KEY = "test-security-key-c69ace85271142a49f929371"


def make_request(
    path: str,
    *,
    peer: str = "203.0.113.10",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    raw_headers = [
        (name.lower().encode(), value.encode())
        for name, value in (headers or {}).items()
    ]
    if cookies:
        raw_headers.append(
            (
                b"cookie",
                "; ".join(
                    f"{name}={value}" for name, value in cookies.items()
                ).encode(),
            )
        )
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": raw_headers,
            "client": (peer, 12345),
            "server": ("testserver", 80),
        }
    )


async def successful_response(request: Request) -> Response:
    del request
    return Response(status_code=200)


def security_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret_key=TEST_JWT_KEY,
        **overrides,
    )


def test_untrusted_peer_cannot_spoof_forwarded_client_ip() -> None:
    request = make_request(
        "/auth/login",
        headers={"x-forwarded-for": "198.51.100.99"},
    )

    assert resolve_client_ip(request, ()) == "203.0.113.10"


def test_forwarded_client_ip_is_used_only_for_trusted_proxy() -> None:
    request = make_request(
        "/auth/login",
        peer="10.0.0.5",
        headers={
            "x-forwarded-for": "192.0.2.40, 198.51.100.12",
        },
    )

    assert resolve_client_ip(
        request,
        (ip_network("10.0.0.0/24"),),
    ) == "198.51.100.12"


@pytest.mark.asyncio
async def test_forwarded_header_cannot_bypass_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = security_settings(
        auth_rate_limit_requests=1,
        auth_rate_limit_window_seconds=60,
    )
    monkeypatch.setattr(
        "knowledge_assistant.presentation.middleware.security.get_settings",
        lambda: settings,
    )
    middleware = AuthRateLimitMiddleware(successful_response)

    first = await middleware.dispatch(
        make_request(
            "/auth/login",
            headers={"x-forwarded-for": "192.0.2.1"},
        ),
        successful_response,
    )
    second = await middleware.dispatch(
        make_request(
            "/auth/login",
            headers={"x-forwarded-for": "192.0.2.2"},
        ),
        successful_response,
    )

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_records_expire_and_storage_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    settings = security_settings(
        auth_rate_limit_requests=1,
        auth_rate_limit_window_seconds=10,
        auth_rate_limit_max_keys=2,
    )
    monkeypatch.setattr(
        "knowledge_assistant.presentation.middleware.security.get_settings",
        lambda: settings,
    )
    middleware = AuthRateLimitMiddleware(
        successful_response,
        clock=lambda: now,
    )

    for peer in ("192.0.2.1", "192.0.2.2", "192.0.2.3"):
        response = await middleware.dispatch(
            make_request("/auth/login", peer=peer),
            successful_response,
        )
        assert response.status_code == 200

    assert len(middleware._requests) == 2
    assert "/auth/login:192.0.2.1" not in middleware._requests

    limited = await middleware.dispatch(
        make_request("/auth/login", peer="192.0.2.3"),
        successful_response,
    )
    assert limited.status_code == 429

    now = 11.0
    expired = await middleware.dispatch(
        make_request("/auth/login", peer="192.0.2.3"),
        successful_response,
    )
    assert expired.status_code == 200
    assert len(middleware._requests) == 1


class FakeJWTTokenService:
    verified_tokens: list[str] = []
    session_id = uuid4()

    def verify_token(self, token: str) -> dict[str, str]:
        self.verified_tokens.append(token)
        if token == "expired-access":
            raise jwt.ExpiredSignatureError
        return {
            "type": "refresh",
            "sid": str(self.session_id),
        }


class FakeSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        del args


class FakeAuthRepository:
    def __init__(self, session: object) -> None:
        del session

    async def get_session(self, session_id: object) -> object:
        assert session_id == FakeJWTTokenService.session_id
        return SimpleNamespace(
            csrf_token_hash=hash_secret("csrf-token"),
            is_active=lambda: True,
        )


def configure_csrf_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> Settings:
    settings = security_settings()
    FakeJWTTokenService.verified_tokens = []
    monkeypatch.setattr(
        "knowledge_assistant.presentation.middleware.security.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "knowledge_assistant.presentation.middleware.security.JWTTokenService",
        FakeJWTTokenService,
    )
    monkeypatch.setattr(
        "knowledge_assistant.presentation.middleware.security.AsyncSessionFactory",
        FakeSessionContext,
    )
    monkeypatch.setattr(
        "knowledge_assistant.presentation.middleware.security.SQLAlchemyAuthRepository",
        FakeAuthRepository,
    )
    return settings


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/auth/refresh", "/auth/logout"])
async def test_refresh_and_logout_require_csrf(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configure_csrf_fakes(monkeypatch)
    middleware = CSRFMiddleware(successful_response)
    request = make_request(
        path,
        cookies={settings.refresh_cookie_name: "refresh-token"},
    )

    response = await middleware.dispatch(request, successful_response)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_refresh_uses_refresh_cookie_when_access_token_is_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configure_csrf_fakes(monkeypatch)
    middleware = CSRFMiddleware(successful_response)
    request = make_request(
        "/auth/refresh",
        headers={"x-csrf-token": "csrf-token"},
        cookies={
            settings.access_cookie_name: "expired-access",
            settings.refresh_cookie_name: "refresh-token",
        },
    )

    response = await middleware.dispatch(request, successful_response)

    assert response.status_code == 200
    assert FakeJWTTokenService.verified_tokens == ["refresh-token"]


@pytest.mark.asyncio
async def test_invalid_authorization_header_does_not_bypass_cookie_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configure_csrf_fakes(monkeypatch)
    middleware = CSRFMiddleware(successful_response)
    request = make_request(
        "/auth/profile",
        headers={"authorization": "Basic attacker-controlled"},
        cookies={settings.access_cookie_name: "access-token"},
    )

    response = await middleware.dispatch(request, successful_response)

    assert response.status_code == 403
    assert FakeJWTTokenService.verified_tokens == []


@pytest.mark.asyncio
async def test_bearer_header_does_not_bypass_refresh_cookie_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configure_csrf_fakes(monkeypatch)
    middleware = CSRFMiddleware(successful_response)
    request = make_request(
        "/auth/refresh",
        headers={"authorization": "Bearer invalid-bearer"},
        cookies={settings.refresh_cookie_name: "refresh-token"},
    )

    response = await middleware.dispatch(request, successful_response)

    assert response.status_code == 403
    assert FakeJWTTokenService.verified_tokens == []


class RecordingAuthenticationService:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def authenticate_access_token(self, token: str):
        self.tokens.append(token)
        if token == "invalid-bearer":
            raise AuthenticationError("Invalid session token.")
        return object(), SimpleNamespace(id=uuid4())


@pytest.mark.asyncio
async def test_bearer_credentials_take_precedence_over_cookie() -> None:
    service = RecordingAuthenticationService()
    request = make_request(
        "/auth/profile",
        headers={"authorization": "Bearer bearer-token"},
        cookies={"knowledge_ai_access": "cookie-token"},
    )

    authenticated = await get_authenticated_request(
        request,
        HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="bearer-token",
        ),
        service,
    )

    assert service.tokens == ["bearer-token"]
    assert authenticated.token_source == "bearer"


@pytest.mark.asyncio
async def test_invalid_bearer_does_not_fall_back_to_cookie() -> None:
    service = RecordingAuthenticationService()
    request = make_request(
        "/auth/profile",
        headers={"authorization": "Bearer invalid-bearer"},
        cookies={"knowledge_ai_access": "cookie-token"},
    )

    with pytest.raises(AuthenticationError):
        await get_authenticated_request(
            request,
            HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials="invalid-bearer",
            ),
            service,
        )

    assert service.tokens == ["invalid-bearer"]


def test_openrouter_errors_are_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = httpx.Request(
        "POST",
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"authorization": "Bearer provider-secret"},
        content=b'{"private":"request-payload"}',
    )
    response = httpx.Response(
        401,
        request=request,
        headers={"x-request-id": "safe-request-id"},
        text="provider-secret raw-response request-payload",
    )
    error = httpx.HTTPStatusError(
        "upstream rejected request",
        request=request,
        response=response,
    )

    with pytest.raises(RuntimeError) as raised:
        raise_openrouter_request_error(
            error,
            operation="answer generation",
        )

    public_message = str(raised.value)
    log_output = caplog.text
    assert public_message == OPENROUTER_PUBLIC_ERROR
    for secret in (
        "provider-secret",
        "raw-response",
        "request-payload",
    ):
        assert secret not in public_message
        assert secret not in log_output
    assert "status 401" in log_output
    assert "safe-request-id" in log_output
