import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt

from knowledge_assistant.core.config import Settings
from knowledge_assistant.domain.auth.entities import (
    AccountActionToken,
    AuthSession,
    LoginSecurityState,
    SecurityEvent,
)
from knowledge_assistant.domain.auth.repository import AuthRepository
from knowledge_assistant.domain.auth.security import hash_secret, secrets_match
from knowledge_assistant.domain.auth.token_service import TokenService
from knowledge_assistant.domain.common.exceptions import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from knowledge_assistant.domain.common.value_objects.email import Email
from knowledge_assistant.domain.documents.file_storage import FileStorage
from knowledge_assistant.domain.documents.repository import DocumentRepository
from knowledge_assistant.domain.notifications.email_delivery import (
    EmailDelivery,
    EmailMessage,
)
from knowledge_assistant.domain.security.password_hasher import PasswordHasher
from knowledge_assistant.domain.users.entities import User
from knowledge_assistant.domain.users.repository import UserRepository
from knowledge_assistant.domain.vector_store.store import VectorStore


RESET_PASSWORD_PURPOSE = "password_reset"
VERIFY_EMAIL_PURPOSE = "email_verification"


@dataclass(frozen=True, slots=True)
class RequestMetadata:
    ip_address: str
    user_agent: str


@dataclass(frozen=True, slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_in: int
    refresh_expires_in: int
    session_id: UUID


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    user: User
    tokens: SessionTokens


@dataclass(frozen=True, slots=True)
class ActionDispatchResult:
    delivery: str


class AccountSecurityService:
    def __init__(
        self,
        *,
        users: UserRepository,
        auth: AuthRepository,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        email_delivery: EmailDelivery,
        documents: DocumentRepository | None = None,
        file_storage: FileStorage | None = None,
        vector_store: VectorStore | None = None,
        settings: Settings,
    ) -> None:
        self._users = users
        self._auth = auth
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._email_delivery = email_delivery
        self._documents = documents
        self._file_storage = file_storage
        self._vector_store = vector_store
        self._settings = settings

    async def login(
        self,
        *,
        email: str,
        password: str,
        metadata: RequestMetadata,
    ) -> AuthenticationResult:
        normalized_email = Email(email)
        key_hash = hash_secret(
            f"{normalized_email}|{metadata.ip_address}"
        )
        now = datetime.now(UTC)
        state = await self._auth.get_login_security_state(key_hash)

        if state is not None and self._is_future(state.locked_until, now):
            await self._audit(
                user_id=None,
                event_type="LOGIN_BLOCKED",
                metadata=metadata,
                details={"email": str(normalized_email)},
            )
            raise RateLimitError(
                "Too many failed sign-in attempts. Try again later."
            )

        if state is not None and self._login_state_is_stale(state, now):
            await self._auth.clear_login_security_state(key_hash)
            state = None

        user = await self._users.get_by_email(normalized_email)
        password_is_valid = bool(
            user
            and self._password_hasher.verify(
                user.hashed_password,
                password,
            )
        )

        if user is None or not password_is_valid:
            await self._record_failed_login(
                key_hash=key_hash,
                state=state,
                metadata=metadata,
                email=str(normalized_email),
                now=now,
            )
            raise AuthenticationError("Invalid email or password.")

        if not user.is_active:
            raise AuthenticationError("Your account is inactive.")

        await self._auth.clear_login_security_state(key_hash)
        tokens = await self._create_session(user, metadata)
        await self._audit(
            user_id=user.id,
            event_type="LOGIN_SUCCESS",
            metadata=metadata,
            details={"session_id": str(tokens.session_id)},
        )
        return AuthenticationResult(user=user, tokens=tokens)

    async def refresh(
        self,
        *,
        refresh_token: str,
        metadata: RequestMetadata,
    ) -> AuthenticationResult:
        payload = self._verify_typed_token(refresh_token, "refresh")
        session_id = self._payload_uuid(payload, "sid")
        user_id = self._payload_uuid(payload, "sub")
        session = await self._auth.get_session(session_id)
        now = datetime.now(UTC)

        if (
            session is None
            or session.user_id != user_id
            or not session.is_active(now)
            or not secrets_match(
                refresh_token,
                session.refresh_token_hash,
            )
        ):
            raise AuthenticationError("Refresh session is no longer valid.")

        user = await self._users.get_by_id(user_id)
        self._validate_user_token_version(user, payload)
        assert user is not None

        tokens = self._build_tokens(
            user=user,
            session_id=session.id,
            now=now,
        )
        session.refresh_token_hash = hash_secret(tokens.refresh_token)
        session.csrf_token_hash = hash_secret(tokens.csrf_token)
        session.expires_at = now + timedelta(
            days=self._settings.refresh_token_expire_days
        )
        session.last_used_at = now
        session.user_agent = metadata.user_agent
        session.ip_address = metadata.ip_address
        await self._auth.update_session(session)
        await self._audit(
            user_id=user.id,
            event_type="TOKEN_REFRESHED",
            metadata=metadata,
            details={"session_id": str(session.id)},
        )
        return AuthenticationResult(user=user, tokens=tokens)

    async def authenticate_access_token(
        self,
        token: str,
    ) -> tuple[User, AuthSession]:
        payload = self._verify_typed_token(token, "access")
        session_id = self._payload_uuid(payload, "sid")
        user_id = self._payload_uuid(payload, "sub")
        session = await self._auth.get_session(session_id)

        if session is None or session.user_id != user_id or not session.is_active():
            raise AuthenticationError("Your session is no longer active.")

        user = await self._users.get_by_id(user_id)
        self._validate_user_token_version(user, payload)
        assert user is not None
        return user, session

    async def verify_csrf(
        self,
        *,
        session_id: UUID,
        csrf_token: str,
    ) -> None:
        session = await self._auth.get_session(session_id)
        if (
            session is None
            or not session.is_active()
            or not secrets_match(csrf_token, session.csrf_token_hash)
        ):
            raise AuthorizationError("Invalid CSRF token.")

    async def revoke_refresh_token(
        self,
        *,
        refresh_token: str | None,
        metadata: RequestMetadata,
    ) -> None:
        session_id: UUID | None = None
        user_id: UUID | None = None
        if refresh_token:
            try:
                payload = self._verify_typed_token(
                    refresh_token,
                    "refresh",
                )
                session_id = self._payload_uuid(payload, "sid")
                user_id = self._payload_uuid(payload, "sub")
            except AuthenticationError:
                session_id = None
                user_id = None
        await self.logout(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata,
        )

    async def logout(
        self,
        *,
        session_id: UUID | None,
        user_id: UUID | None,
        metadata: RequestMetadata,
    ) -> None:
        if session_id is not None:
            await self._auth.revoke_session(session_id)
        await self._audit(
            user_id=user_id,
            event_type="LOGOUT",
            metadata=metadata,
            details={
                "session_id": str(session_id) if session_id else None,
            },
        )

    async def logout_all(
        self,
        *,
        user: User,
        metadata: RequestMetadata,
    ) -> None:
        await self._auth.revoke_all_sessions(user.id)
        await self._audit(
            user_id=user.id,
            event_type="LOGOUT_ALL",
            metadata=metadata,
        )

    async def list_sessions(
        self,
        user_id: UUID,
    ) -> list[AuthSession]:
        return await self._auth.list_active_sessions(user_id)

    async def revoke_session(
        self,
        *,
        user: User,
        session_id: UUID,
        current_session_id: UUID,
        metadata: RequestMetadata,
    ) -> None:
        session = await self._auth.get_session(session_id)
        if session is None or session.user_id != user.id:
            raise NotFoundError("Session was not found.")
        if session_id == current_session_id:
            raise ValidationError(
                "Use Sign out to end your current session."
            )
        await self._auth.revoke_session(session_id)
        await self._audit(
            user_id=user.id,
            event_type="SESSION_REVOKED",
            metadata=metadata,
            details={"session_id": str(session_id)},
        )

    async def update_profile(
        self,
        *,
        user: User,
        full_name: str,
        preferred_language: str,
        theme_preference: str,
        assistant_behavior: str,
        metadata: RequestMetadata,
    ) -> User:
        user.update_profile(
            full_name=full_name,
            preferred_language=preferred_language,
            theme_preference=theme_preference,
            assistant_behavior=assistant_behavior,
            now=datetime.now(UTC),
        )
        await self._users.update(user)
        await self._audit(
            user_id=user.id,
            event_type="PROFILE_UPDATED",
            metadata=metadata,
            details={
                "preferred_language": user.preferred_language,
                "theme_preference": user.theme_preference,
                "assistant_behavior": user.assistant_behavior,
            },
        )
        return user

    async def change_password(
        self,
        *,
        user: User,
        current_password: str,
        new_password: str,
        metadata: RequestMetadata,
    ) -> AuthenticationResult:
        if not self._password_hasher.verify(
            user.hashed_password,
            current_password,
        ):
            raise AuthenticationError("Current password is incorrect.")
        self._validate_new_password(new_password)
        if self._password_hasher.verify(user.hashed_password, new_password):
            raise ValidationError(
                "New password must be different from the current password."
            )

        user.change_password(
            self._password_hasher.hash(new_password),
            datetime.now(UTC),
        )
        await self._users.update(user)
        await self._auth.revoke_all_sessions(user.id)
        tokens = await self._create_session(user, metadata)
        await self._audit(
            user_id=user.id,
            event_type="PASSWORD_CHANGED",
            metadata=metadata,
            details={"session_id": str(tokens.session_id)},
        )
        return AuthenticationResult(user=user, tokens=tokens)

    async def request_password_reset(
        self,
        *,
        email: str,
        metadata: RequestMetadata,
    ) -> ActionDispatchResult:
        normalized = Email(email)
        user = await self._users.get_by_email(normalized)
        if user is None or not user.is_active:
            return ActionDispatchResult(delivery="accepted")

        raw_token = await self._create_action_token(
            user_id=user.id,
            purpose=RESET_PASSWORD_PURPOSE,
        )
        link = (
            f"{self._settings.frontend_base_url.rstrip('/')}"
            f"/reset-password?token={raw_token}"
        )
        await self._email_delivery.send(
            EmailMessage(
                recipient=str(user.email),
                subject="Reset your Knowledge AI password",
                text_body=(
                    "A password reset was requested for your account.\n\n"
                    f"Open this link to continue:\n{link}\n\n"
                    "The link expires soon. If you did not request this, "
                    "you can ignore this message."
                ),
            )
        )
        await self._audit(
            user_id=user.id,
            event_type="PASSWORD_RESET_REQUESTED",
            metadata=metadata,
        )
        return ActionDispatchResult(delivery="accepted")

    async def confirm_password_reset(
        self,
        *,
        token: str,
        new_password: str,
        metadata: RequestMetadata,
    ) -> None:
        self._validate_new_password(new_password)
        action = await self._auth.get_active_action_token(
            token_hash=hash_secret(token),
            purpose=RESET_PASSWORD_PURPOSE,
        )
        if action is None:
            raise AuthenticationError(
                "Password reset token is invalid or expired."
            )
        user = await self._users.get_by_id(action.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account is not available.")

        user.change_password(
            self._password_hasher.hash(new_password),
            datetime.now(UTC),
        )
        await self._users.update(user)
        await self._auth.mark_action_token_used(action.id)
        await self._auth.revoke_all_sessions(user.id)
        await self._audit(
            user_id=user.id,
            event_type="PASSWORD_RESET_COMPLETED",
            metadata=metadata,
        )

    async def request_email_verification(
        self,
        *,
        user: User,
        metadata: RequestMetadata,
    ) -> ActionDispatchResult:
        if user.is_verified:
            raise ValidationError("Email address is already verified.")
        raw_token = await self._create_action_token(
            user_id=user.id,
            purpose=VERIFY_EMAIL_PURPOSE,
        )
        link = (
            f"{self._settings.frontend_base_url.rstrip('/')}"
            f"/verify-email?token={raw_token}"
        )
        await self._email_delivery.send(
            EmailMessage(
                recipient=str(user.email),
                subject="Verify your Knowledge AI email",
                text_body=(
                    "Verify your email address to secure your account.\n\n"
                    f"Open this link:\n{link}\n\n"
                    "The link expires soon."
                ),
            )
        )
        await self._audit(
            user_id=user.id,
            event_type="EMAIL_VERIFICATION_REQUESTED",
            metadata=metadata,
        )
        return ActionDispatchResult(
            delivery=self._settings.mail_delivery_mode,
        )

    async def confirm_email_verification(
        self,
        *,
        token: str,
        metadata: RequestMetadata,
    ) -> User:
        action = await self._auth.get_active_action_token(
            token_hash=hash_secret(token),
            purpose=VERIFY_EMAIL_PURPOSE,
        )
        if action is None:
            raise AuthenticationError(
                "Email verification token is invalid or expired."
            )
        user = await self._users.get_by_id(action.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account is not available.")
        if not user.is_verified:
            user.verify_email(datetime.now(UTC))
            await self._users.update(user)
        await self._auth.mark_action_token_used(action.id)
        await self._audit(
            user_id=user.id,
            event_type="EMAIL_VERIFIED",
            metadata=metadata,
        )
        return user

    async def list_security_events(
        self,
        user_id: UUID,
    ) -> list[SecurityEvent]:
        return await self._auth.list_security_events(user_id, limit=50)

    async def delete_account(
        self,
        *,
        user: User,
        password: str,
        confirmation: str,
        metadata: RequestMetadata,
    ) -> None:
        if confirmation != "DELETE":
            raise ValidationError("Type DELETE to confirm account deletion.")
        if not self._password_hasher.verify(
            user.hashed_password,
            password,
        ):
            raise AuthenticationError("Password is incorrect.")

        if (
            self._documents is None
            or self._file_storage is None
            or self._vector_store is None
        ):
            raise RuntimeError(
                "Account deletion dependencies are not configured."
            )

        documents = await self._documents.list_by_owner_id(user.id)
        for document in documents:
            await self._vector_store.delete_document_records(
                owner_id=user.id,
                document_id=document.id,
            )
            await self._file_storage.delete(document.storage_path)
            await self._documents.delete(document.id)

        await self._audit(
            user_id=user.id,
            event_type="ACCOUNT_DELETED",
            metadata=metadata,
        )
        await self._users.delete(user.id)

    async def _create_session(
        self,
        user: User,
        metadata: RequestMetadata,
    ) -> SessionTokens:
        now = datetime.now(UTC)
        session_id = uuid4()
        tokens = self._build_tokens(
            user=user,
            session_id=session_id,
            now=now,
        )
        await self._auth.add_session(
            AuthSession(
                id=session_id,
                user_id=user.id,
                refresh_token_hash=hash_secret(tokens.refresh_token),
                csrf_token_hash=hash_secret(tokens.csrf_token),
                expires_at=now
                + timedelta(days=self._settings.refresh_token_expire_days),
                created_at=now,
                last_used_at=now,
                user_agent=metadata.user_agent,
                ip_address=metadata.ip_address,
            )
        )
        return tokens

    def _build_tokens(
        self,
        *,
        user: User,
        session_id: UUID,
        now: datetime,
    ) -> SessionTokens:
        access_seconds = self._settings.access_token_expire_minutes * 60
        refresh_seconds = self._settings.refresh_token_expire_days * 86400
        common = {
            "sid": str(session_id),
            "ver": user.auth_version,
        }
        access_token = self._token_service.create_token(
            subject=str(user.id),
            expires_delta=timedelta(seconds=access_seconds),
            additional_claims={
                **common,
                "type": "access",
                "jti": uuid4().hex,
            },
        )
        refresh_token = self._token_service.create_token(
            subject=str(user.id),
            expires_delta=timedelta(seconds=refresh_seconds),
            additional_claims={
                **common,
                "type": "refresh",
                "jti": uuid4().hex,
            },
        )
        return SessionTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            csrf_token=secrets.token_urlsafe(32),
            access_expires_in=access_seconds,
            refresh_expires_in=refresh_seconds,
            session_id=session_id,
        )

    async def _create_action_token(
        self,
        *,
        user_id: UUID,
        purpose: str,
    ) -> str:
        await self._auth.invalidate_action_tokens(
            user_id=user_id,
            purpose=purpose,
        )
        now = datetime.now(UTC)
        raw_token = secrets.token_urlsafe(32)
        await self._auth.add_action_token(
            AccountActionToken(
                id=uuid4(),
                user_id=user_id,
                purpose=purpose,
                token_hash=hash_secret(raw_token),
                expires_at=now
                + timedelta(
                    minutes=self._settings.account_action_token_expire_minutes
                ),
                created_at=now,
            )
        )
        return raw_token

    async def _record_failed_login(
        self,
        *,
        key_hash: str,
        state: LoginSecurityState | None,
        metadata: RequestMetadata,
        email: str,
        now: datetime,
    ) -> None:
        failed_attempts = 1 if state is None else state.failed_attempts + 1
        first_failed_at = (
            now if state is None or state.first_failed_at is None
            else state.first_failed_at
        )
        locked_until = None
        if failed_attempts >= self._settings.login_max_failed_attempts:
            locked_until = now + timedelta(
                minutes=self._settings.login_lock_minutes
            )
        await self._auth.upsert_login_security_state(
            LoginSecurityState(
                key_hash=key_hash,
                failed_attempts=failed_attempts,
                first_failed_at=first_failed_at,
                locked_until=locked_until,
                updated_at=now,
            )
        )
        await self._audit(
            user_id=None,
            event_type="LOGIN_FAILURE",
            metadata=metadata,
            details={"email": email, "attempts": failed_attempts},
        )

    async def _audit(
        self,
        *,
        user_id: UUID | None,
        event_type: str,
        metadata: RequestMetadata,
        details: dict[str, object] | None = None,
    ) -> None:
        await self._auth.add_security_event(
            SecurityEvent(
                id=uuid4(),
                user_id=user_id,
                event_type=event_type,
                ip_address=metadata.ip_address[:64],
                user_agent=metadata.user_agent[:500],
                metadata_json=json.dumps(details or {}, sort_keys=True),
                created_at=datetime.now(UTC),
            )
        )

    def _verify_typed_token(
        self,
        token: str,
        expected_type: str,
    ) -> dict[str, object]:
        try:
            payload = self._token_service.verify_token(token)
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Session token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("Session token is invalid.") from exc
        if payload.get("type") != expected_type:
            raise AuthenticationError("Unexpected token type.")
        return payload

    @staticmethod
    def _payload_uuid(payload: dict[str, object], key: str) -> UUID:
        value = payload.get(key)
        if not isinstance(value, str):
            raise AuthenticationError("Session token is incomplete.")
        try:
            return UUID(value)
        except ValueError as exc:
            raise AuthenticationError("Session token is invalid.") from exc

    def _login_state_is_stale(
        self,
        state: LoginSecurityState,
        now: datetime,
    ) -> bool:
        if state.locked_until is not None:
            locked_until = state.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=UTC)
            return locked_until <= now

        if state.first_failed_at is None:
            return False

        first_failed_at = state.first_failed_at
        if first_failed_at.tzinfo is None:
            first_failed_at = first_failed_at.replace(tzinfo=UTC)
        return first_failed_at + timedelta(
            minutes=self._settings.login_lock_minutes
        ) <= now

    @staticmethod
    def _is_future(value: datetime | None, now: datetime) -> bool:
        if value is None:
            return False
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value > now

    @staticmethod
    def _validate_new_password(password: str) -> None:
        if len(password) < 10:
            raise ValidationError(
                "Password must contain at least 10 characters."
            )
        if not any(character.isalpha() for character in password):
            raise ValidationError("Password must contain a letter.")
        if not any(character.isdigit() for character in password):
            raise ValidationError("Password must contain a number.")

    @staticmethod
    def _validate_user_token_version(
        user: User | None,
        payload: dict[str, object],
    ) -> None:
        if user is None:
            raise AuthenticationError("Account no longer exists.")
        if not user.is_active:
            raise AuthorizationError("Your account is inactive.")
        version = payload.get("ver")
        if not isinstance(version, int) or version != user.auth_version:
            raise AuthenticationError("Your session is no longer valid.")
