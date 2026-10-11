import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from knowledge_assistant.application.users.commands.register_user import (
    RegisterUserCommand,
    RegisterUserUseCase,
)
from knowledge_assistant.application.users.services.account_security import (
    RequestMetadata,
    SessionTokens,
)
from knowledge_assistant.bootstrap.dependencies.user import (
    CoreAccountSecurityDependency,
    CurrentAuthDependency,
    CurrentUserDependency,
    FullAccountSecurityDependency,
    get_register_user_use_case,
)
from knowledge_assistant.core.config import get_settings
from knowledge_assistant.domain.common.exceptions import AuthenticationError
from knowledge_assistant.domain.users.entities import User
from knowledge_assistant.presentation.api.v1.schemas.auth import (
    ActionDispatchResponse,
    AuthSessionResponse,
    ChangePasswordRequest,
    CurrentUserResponse,
    DeleteAccountRequest,
    EmailVerificationConfirmRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    RegisterResponse,
    SecurityEventResponse,
    SessionResponse,
)
from knowledge_assistant.presentation.middleware.client_ip import (
    resolve_client_ip,
)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

RegisterUserDependency = Annotated[
    RegisterUserUseCase,
    Depends(get_register_user_use_case),
]


def _metadata(request: Request) -> RequestMetadata:
    settings = get_settings()
    ip_address = resolve_client_ip(
        request,
        settings.trusted_proxy_networks,
    )
    return RequestMetadata(
        ip_address=ip_address[:64],
        user_agent=request.headers.get("user-agent", "unknown")[:500],
    )


def _user_response(user: User) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        email=str(user.email),
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        preferred_language=user.preferred_language,
        theme_preference=user.theme_preference,
        assistant_behavior=user.assistant_behavior,
        created_at=user.created_at,
        email_verified_at=user.email_verified_at,
    )


def _set_auth_cookies(
    response: Response,
    tokens: SessionTokens,
) -> None:
    settings = get_settings()
    common = {
        "httponly": True,
        "secure": settings.effective_cookie_secure,
        "samesite": settings.effective_cookie_samesite,
        "domain": settings.auth_cookie_domain,
        "path": "/",
    }
    response.set_cookie(
        key=settings.access_cookie_name,
        value=tokens.access_token,
        max_age=tokens.access_expires_in,
        **common,
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=tokens.refresh_token,
        max_age=tokens.refresh_expires_in,
        **common,
    )


def _clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    for cookie_name in (
        settings.access_cookie_name,
        settings.refresh_cookie_name,
    ):
        response.delete_cookie(
            key=cookie_name,
            domain=settings.auth_cookie_domain,
            path="/",
            secure=settings.effective_cookie_secure,
            httponly=True,
            samesite=settings.effective_cookie_samesite,
        )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    payload: RegisterRequest,
    use_case: RegisterUserDependency,
) -> RegisterResponse:
    user = await use_case.execute(
        RegisterUserCommand(
            email=str(payload.email),
            password=payload.password,
            full_name=payload.full_name,
        )
    )
    return RegisterResponse(
        id=user.id,
        email=str(user.email),
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
    )


@router.post(
    "/login",
    response_model=AuthSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Login user and create a rotating cookie session",
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: CoreAccountSecurityDependency,
) -> AuthSessionResponse:
    result = await service.login(
        email=str(payload.email),
        password=payload.password,
        metadata=_metadata(request),
    )
    _set_auth_cookies(response, result.tokens)
    return AuthSessionResponse(
        user=_user_response(result.user),
        csrf_token=result.tokens.csrf_token,
        expires_in=result.tokens.access_expires_in,
    )


@router.post(
    "/refresh",
    response_model=AuthSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate refresh token and renew the session",
)
async def refresh_session(
    request: Request,
    response: Response,
    service: CoreAccountSecurityDependency,
) -> AuthSessionResponse:
    settings = get_settings()
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise AuthenticationError("Refresh cookie was not provided.")
    result = await service.refresh(
        refresh_token=refresh_token,
        metadata=_metadata(request),
    )
    _set_auth_cookies(response, result.tokens)
    return AuthSessionResponse(
        user=_user_response(result.user),
        csrf_token=result.tokens.csrf_token,
        expires_in=result.tokens.access_expires_in,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def logout(
    request: Request,
    response: Response,
    service: CoreAccountSecurityDependency,
) -> MessageResponse:
    settings = get_settings()
    await service.revoke_refresh_token(
        refresh_token=request.cookies.get(settings.refresh_cookie_name),
        metadata=_metadata(request),
    )
    _clear_auth_cookies(response)
    return MessageResponse(message="Signed out successfully.")


@router.post(
    "/logout-all",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def logout_all(
    request: Request,
    response: Response,
    authenticated: CurrentAuthDependency,
    service: CoreAccountSecurityDependency,
) -> MessageResponse:
    await service.logout_all(
        user=authenticated.user,
        metadata=_metadata(request),
    )
    _clear_auth_cookies(response)
    return MessageResponse(message="All sessions were signed out.")


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    status_code=status.HTTP_200_OK,
)
async def get_me(
    current_user: CurrentUserDependency,
) -> CurrentUserResponse:
    return _user_response(current_user)


@router.patch(
    "/profile",
    response_model=CurrentUserResponse,
    status_code=status.HTTP_200_OK,
)
async def update_profile(
    payload: ProfileUpdateRequest,
    request: Request,
    current_user: CurrentUserDependency,
    service: CoreAccountSecurityDependency,
) -> CurrentUserResponse:
    user = await service.update_profile(
        user=current_user,
        full_name=payload.full_name,
        preferred_language=payload.preferred_language,
        theme_preference=payload.theme_preference,
        assistant_behavior=payload.assistant_behavior,
        metadata=_metadata(request),
    )
    return _user_response(user)


@router.post(
    "/change-password",
    response_model=AuthSessionResponse,
    status_code=status.HTTP_200_OK,
)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: CurrentUserDependency,
    service: CoreAccountSecurityDependency,
) -> AuthSessionResponse:
    result = await service.change_password(
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        metadata=_metadata(request),
    )
    _set_auth_cookies(response, result.tokens)
    return AuthSessionResponse(
        user=_user_response(result.user),
        csrf_token=result.tokens.csrf_token,
        expires_in=result.tokens.access_expires_in,
    )


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    status_code=status.HTTP_200_OK,
)
async def list_sessions(
    authenticated: CurrentAuthDependency,
    service: CoreAccountSecurityDependency,
) -> list[SessionResponse]:
    sessions = await service.list_sessions(authenticated.user.id)
    return [
        SessionResponse(
            id=session.id,
            current=session.id == authenticated.session_id,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            expires_at=session.expires_at,
            user_agent=session.user_agent,
            ip_address=session.ip_address,
        )
        for session in sessions
    ]


@router.delete(
    "/sessions/{session_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def revoke_session(
    session_id: UUID,
    request: Request,
    authenticated: CurrentAuthDependency,
    service: CoreAccountSecurityDependency,
) -> MessageResponse:
    await service.revoke_session(
        user=authenticated.user,
        session_id=session_id,
        current_session_id=authenticated.session_id,
        metadata=_metadata(request),
    )
    return MessageResponse(message="Session revoked.")


@router.get(
    "/security-events",
    response_model=list[SecurityEventResponse],
    status_code=status.HTTP_200_OK,
)
async def list_security_events(
    current_user: CurrentUserDependency,
    service: CoreAccountSecurityDependency,
) -> list[SecurityEventResponse]:
    events = await service.list_security_events(current_user.id)
    return [
        SecurityEventResponse(
            id=event.id,
            event_type=event.event_type,
            ip_address=event.ip_address,
            user_agent=event.user_agent,
            metadata=json.loads(event.metadata_json or "{}"),
            created_at=event.created_at,
        )
        for event in events
    ]


@router.post(
    "/password-reset/request",
    response_model=ActionDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    service: CoreAccountSecurityDependency,
) -> ActionDispatchResponse:
    result = await service.request_password_reset(
        email=str(payload.email),
        metadata=_metadata(request),
    )
    return ActionDispatchResponse(
        message=(
            "If an active account exists for that email, a reset link "
            "has been prepared."
        ),
        delivery=result.delivery,
    )


@router.post(
    "/password-reset/confirm",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    response: Response,
    service: CoreAccountSecurityDependency,
) -> MessageResponse:
    await service.confirm_password_reset(
        token=payload.token,
        new_password=payload.new_password,
        metadata=_metadata(request),
    )
    _clear_auth_cookies(response)
    return MessageResponse(
        message="Password reset completed. Sign in with your new password."
    )


@router.post(
    "/email-verification/request",
    response_model=ActionDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_email_verification(
    request: Request,
    current_user: CurrentUserDependency,
    service: CoreAccountSecurityDependency,
) -> ActionDispatchResponse:
    result = await service.request_email_verification(
        user=current_user,
        metadata=_metadata(request),
    )
    return ActionDispatchResponse(
        message="Verification instructions have been prepared.",
        delivery=result.delivery,
    )


@router.post(
    "/email-verification/confirm",
    response_model=CurrentUserResponse,
    status_code=status.HTTP_200_OK,
)
async def confirm_email_verification(
    payload: EmailVerificationConfirmRequest,
    request: Request,
    service: CoreAccountSecurityDependency,
) -> CurrentUserResponse:
    user = await service.confirm_email_verification(
        token=payload.token,
        metadata=_metadata(request),
    )
    return _user_response(user)


@router.delete(
    "/account",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_account(
    payload: DeleteAccountRequest,
    request: Request,
    response: Response,
    current_user: CurrentUserDependency,
    service: FullAccountSecurityDependency,
) -> MessageResponse:
    await service.delete_account(
        user=current_user,
        password=payload.password,
        confirmation=payload.confirmation,
        metadata=_metadata(request),
    )
    _clear_auth_cookies(response)
    return MessageResponse(message="Account deleted permanently.")
