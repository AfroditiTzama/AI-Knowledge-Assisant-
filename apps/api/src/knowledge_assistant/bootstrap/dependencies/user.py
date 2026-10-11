from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from knowledge_assistant.application.users.commands.register_user import (
    RegisterUserUseCase,
)
from knowledge_assistant.application.users.services.account_security import (
    AccountSecurityService,
)
from knowledge_assistant.bootstrap.dependencies.database import DatabaseSession
from knowledge_assistant.bootstrap.dependencies.document import (
    get_document_repository,
    get_file_storage,
    get_vector_store,
)
from knowledge_assistant.core.config import get_settings
from knowledge_assistant.domain.auth.repository import AuthRepository
from knowledge_assistant.domain.auth.token_service import TokenService
from knowledge_assistant.domain.common.exceptions import AuthenticationError
from knowledge_assistant.domain.documents.file_storage import FileStorage
from knowledge_assistant.domain.documents.repository import DocumentRepository
from knowledge_assistant.domain.notifications.email_delivery import EmailDelivery
from knowledge_assistant.domain.security.password_hasher import PasswordHasher
from knowledge_assistant.domain.users.entities import User
from knowledge_assistant.domain.vector_store.store import VectorStore
from knowledge_assistant.infrastructure.auth.jwt_token_service import (
    JWTTokenService,
)
from knowledge_assistant.infrastructure.database.repositories.auth_repository import (
    SQLAlchemyAuthRepository,
)
from knowledge_assistant.infrastructure.database.repositories.user_repository import (
    SQLAlchemyUserRepository,
)
from knowledge_assistant.infrastructure.notifications.email_delivery import (
    LocalOutboxEmailDelivery,
    SMTPEmailDelivery,
)
from knowledge_assistant.infrastructure.security.argon2_password_hasher import (
    Argon2PasswordHasher,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedRequest:
    user: User
    session_id: UUID
    token_source: str


bearer_scheme = HTTPBearer(auto_error=False)


def get_user_repository(
    session: DatabaseSession,
) -> SQLAlchemyUserRepository:
    return SQLAlchemyUserRepository(session)


def get_auth_repository(
    session: DatabaseSession,
) -> AuthRepository:
    return SQLAlchemyAuthRepository(session)


def get_password_hasher() -> PasswordHasher:
    return Argon2PasswordHasher()


def get_token_service() -> TokenService:
    return JWTTokenService()


@lru_cache
def get_email_delivery() -> EmailDelivery:
    settings = get_settings()
    if settings.mail_delivery_mode.lower() == "smtp":
        if not settings.smtp_host:
            raise RuntimeError(
                "SMTP_HOST is required when MAIL_DELIVERY_MODE=smtp."
            )
        return SMTPEmailDelivery(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_address=settings.mail_from_address,
            use_tls=settings.smtp_use_tls,
        )
    return LocalOutboxEmailDelivery(settings.mail_outbox_directory)


def get_core_account_security_service(
    users: SQLAlchemyUserRepository = Depends(get_user_repository),
    auth: AuthRepository = Depends(get_auth_repository),
    password_hasher: PasswordHasher = Depends(get_password_hasher),
    token_service: TokenService = Depends(get_token_service),
    email_delivery: EmailDelivery = Depends(get_email_delivery),
) -> AccountSecurityService:
    return AccountSecurityService(
        users=users,
        auth=auth,
        password_hasher=password_hasher,
        token_service=token_service,
        email_delivery=email_delivery,
        settings=get_settings(),
    )


def get_full_account_security_service(
    users: SQLAlchemyUserRepository = Depends(get_user_repository),
    auth: AuthRepository = Depends(get_auth_repository),
    password_hasher: PasswordHasher = Depends(get_password_hasher),
    token_service: TokenService = Depends(get_token_service),
    email_delivery: EmailDelivery = Depends(get_email_delivery),
    documents: DocumentRepository = Depends(get_document_repository),
    file_storage: FileStorage = Depends(get_file_storage),
    vector_store: VectorStore = Depends(get_vector_store),
) -> AccountSecurityService:
    return AccountSecurityService(
        users=users,
        auth=auth,
        password_hasher=password_hasher,
        token_service=token_service,
        email_delivery=email_delivery,
        documents=documents,
        file_storage=file_storage,
        vector_store=vector_store,
        settings=get_settings(),
    )


async def get_authenticated_request(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    service: AccountSecurityService = Depends(
        get_core_account_security_service
    ),
) -> AuthenticatedRequest:
    settings = get_settings()
    cookie_token = request.cookies.get(settings.access_cookie_name)
    bearer_token: str | None = None
    authorization_header = request.headers.get("authorization")

    if credentials is not None:
        if credentials.scheme.lower() != "bearer":
            raise AuthenticationError("Invalid authentication scheme.")
        bearer_token = credentials.credentials
    elif authorization_header is not None:
        raise AuthenticationError("Invalid Authorization header.")

    token = bearer_token if authorization_header is not None else cookie_token
    if not token:
        raise AuthenticationError(
            "Authentication credentials were not provided."
        )

    user, session = await service.authenticate_access_token(token)
    return AuthenticatedRequest(
        user=user,
        session_id=session.id,
        token_source=(
            "bearer" if authorization_header is not None else "cookie"
        ),
    )


async def get_current_user(
    authenticated: Annotated[
        AuthenticatedRequest,
        Depends(get_authenticated_request),
    ],
) -> User:
    return authenticated.user


CurrentAuthDependency = Annotated[
    AuthenticatedRequest,
    Depends(get_authenticated_request),
]
CurrentUserDependency = Annotated[
    User,
    Depends(get_current_user),
]
CoreAccountSecurityDependency = Annotated[
    AccountSecurityService,
    Depends(get_core_account_security_service),
]
FullAccountSecurityDependency = Annotated[
    AccountSecurityService,
    Depends(get_full_account_security_service),
]


def get_register_user_use_case(
    repository: SQLAlchemyUserRepository = Depends(get_user_repository),
    password_hasher: PasswordHasher = Depends(get_password_hasher),
) -> RegisterUserUseCase:
    return RegisterUserUseCase(
        repository=repository,
        password_hasher=password_hasher,
    )
