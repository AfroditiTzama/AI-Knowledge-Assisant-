from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
import pytest

from knowledge_assistant.application.users.services.account_security import (
    AccountSecurityService,
    RequestMetadata,
)
from knowledge_assistant.core.config import Settings
from knowledge_assistant.domain.auth.token_service import TokenService
from knowledge_assistant.domain.common.exceptions import AuthenticationError
from knowledge_assistant.domain.common.value_objects.email import Email
from knowledge_assistant.domain.notifications.email_delivery import (
    EmailDelivery,
    EmailMessage,
)
from knowledge_assistant.domain.security.password_hasher import PasswordHasher
from knowledge_assistant.domain.users.entities import User
from knowledge_assistant.presentation.api.v1.schemas.auth import (
    ActionDispatchResponse,
)


class FakeUsers:
    def __init__(self, user: User) -> None:
        self.user = user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.user if self.user.id == user_id else None

    async def get_by_email(self, email: Email) -> User | None:
        return self.user if str(self.user.email) == str(email) else None

    async def exists_by_email(self, email: Email) -> bool:
        return await self.get_by_email(email) is not None

    async def add(self, user: User) -> None:
        self.user = user

    async def update(self, user: User) -> None:
        self.user = user

    async def delete(self, user_id: UUID) -> None:
        del user_id


class FakeAuth:
    def __init__(self) -> None:
        self.sessions = {}
        self.action_tokens = {}
        self.events = []
        self.login_states = {}

    async def add_session(self, session) -> None:
        self.sessions[session.id] = session

    async def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def update_session(self, session) -> None:
        self.sessions[session.id] = session

    async def list_active_sessions(self, user_id):
        return [
            session
            for session in self.sessions.values()
            if session.user_id == user_id and session.is_active()
        ]

    async def revoke_session(self, session_id) -> None:
        session = self.sessions.get(session_id)
        if session is not None:
            session.revoked_at = datetime.now(UTC)

    async def revoke_all_sessions(
        self,
        user_id,
        *,
        except_session_id=None,
    ) -> None:
        for session in self.sessions.values():
            if session.user_id == user_id and session.id != except_session_id:
                session.revoked_at = datetime.now(UTC)

    async def add_action_token(self, token) -> None:
        self.action_tokens[token.token_hash] = token

    async def get_active_action_token(self, *, token_hash, purpose):
        token = self.action_tokens.get(token_hash)
        if token and token.purpose == purpose and token.is_active():
            return token
        return None

    async def mark_action_token_used(self, token_id) -> None:
        for token in self.action_tokens.values():
            if token.id == token_id:
                token.used_at = datetime.now(UTC)

    async def invalidate_action_tokens(self, *, user_id, purpose) -> None:
        for token in self.action_tokens.values():
            if token.user_id == user_id and token.purpose == purpose:
                token.used_at = datetime.now(UTC)

    async def add_security_event(self, event) -> None:
        self.events.append(event)

    async def list_security_events(self, user_id, *, limit=50):
        return [
            event for event in self.events if event.user_id == user_id
        ][-limit:]

    async def get_login_security_state(self, key_hash):
        return self.login_states.get(key_hash)

    async def upsert_login_security_state(self, state) -> None:
        self.login_states[state.key_hash] = state

    async def clear_login_security_state(self, key_hash) -> None:
        self.login_states.pop(key_hash, None)


class FakeHasher(PasswordHasher):
    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, hashed_password: str, password: str) -> bool:
        return hashed_password == f"hashed:{password}"


class FakeTokens(TokenService):
    secret = "test-secret-key-that-is-long-enough-for-jwt-signing"

    def create_token(
        self,
        subject,
        expires_delta,
        additional_claims=None,
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": subject,
            "iat": now,
            "exp": now + expires_delta,
            **(additional_claims or {}),
        }
        return jwt.encode(payload, self.secret, algorithm="HS256")

    def verify_token(self, token: str):
        return jwt.decode(token, self.secret, algorithms=["HS256"])


class FakeEmailDelivery(EmailDelivery):
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)


def build_service() -> tuple[
    AccountSecurityService,
    User,
    FakeAuth,
    FakeEmailDelivery,
]:
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        email=Email("person@example.com"),
        hashed_password="hashed:Password123",
        full_name="Test Person",
        is_active=True,
        is_verified=False,
        auth_version=1,
        preferred_language="en",
        theme_preference="system",
        assistant_behavior="balanced",
        created_at=now,
        updated_at=now,
        email_verified_at=None,
    )
    auth = FakeAuth()
    email_delivery = FakeEmailDelivery()
    service = AccountSecurityService(
        users=FakeUsers(user),
        auth=auth,
        password_hasher=FakeHasher(),
        token_service=FakeTokens(),
        email_delivery=email_delivery,
        settings=Settings(
            jwt_secret_key="test-signing-key-2f5e932ac1744cc98959190c",
            app_debug=True,
        ),
    )
    return service, user, auth, email_delivery


@pytest.mark.asyncio
async def test_login_and_refresh_rotate_session_token() -> None:
    service, user, auth, _ = build_service()
    metadata = RequestMetadata("127.0.0.1", "pytest")

    login = await service.login(
        email=str(user.email),
        password="Password123",
        metadata=metadata,
    )
    refresh = await service.refresh(
        refresh_token=login.tokens.refresh_token,
        metadata=metadata,
    )

    assert refresh.tokens.refresh_token != login.tokens.refresh_token
    assert len(auth.sessions) == 1
    assert refresh.tokens.session_id == login.tokens.session_id


@pytest.mark.asyncio
async def test_password_change_invalidates_previous_auth_version() -> None:
    service, user, _, _ = build_service()
    metadata = RequestMetadata("127.0.0.1", "pytest")
    login = await service.login(
        email=str(user.email),
        password="Password123",
        metadata=metadata,
    )

    changed = await service.change_password(
        user=user,
        current_password="Password123",
        new_password="NewPassword456",
        metadata=metadata,
    )

    assert changed.user.auth_version == 2
    with pytest.raises(AuthenticationError):
        await service.authenticate_access_token(login.tokens.access_token)


@pytest.mark.asyncio
async def test_login_is_locked_after_repeated_failures() -> None:
    service, user, _, _ = build_service()
    metadata = RequestMetadata("127.0.0.1", "pytest")

    for _ in range(5):
        with pytest.raises(AuthenticationError):
            await service.login(
                email=str(user.email),
                password="wrong-password",
                metadata=metadata,
            )

    with pytest.raises(AuthenticationError, match="Too many"):
        await service.login(
            email=str(user.email),
            password="Password123",
            metadata=metadata,
        )


@pytest.mark.asyncio
async def test_password_reset_does_not_expose_token_or_account_status() -> None:
    service, user, _, email_delivery = build_service()
    metadata = RequestMetadata("127.0.0.1", "pytest")

    existing_account = await service.request_password_reset(
        email=str(user.email),
        metadata=metadata,
    )
    unknown_account = await service.request_password_reset(
        email="unknown@example.com",
        metadata=metadata,
    )

    assert existing_account == unknown_account
    assert existing_account.delivery == "accepted"
    assert not hasattr(existing_account, "debug_token")
    assert len(email_delivery.messages) == 1
    assert "/reset-password?token=" in email_delivery.messages[0].text_body


@pytest.mark.asyncio
async def test_email_verification_keeps_outbox_link_private() -> None:
    service, user, _, email_delivery = build_service()

    result = await service.request_email_verification(
        user=user,
        metadata=RequestMetadata("127.0.0.1", "pytest"),
    )

    assert result.delivery == "outbox"
    assert not hasattr(result, "debug_token")
    assert len(email_delivery.messages) == 1
    assert "/verify-email?token=" in email_delivery.messages[0].text_body


def test_action_dispatch_response_has_no_token_field() -> None:
    response = ActionDispatchResponse.model_validate(
        {
            "message": "Instructions have been prepared.",
            "delivery": "accepted",
            "debug_token": "must-not-be-serialized",
        }
    )

    assert response.model_dump() == {
        "message": "Instructions have been prepared.",
        "delivery": "accepted",
    }
