import pytest
from pydantic import ValidationError

from knowledge_assistant.core.config import Settings


SECURE_TEST_KEY = "test-signing-key-2f5e932ac1744cc98959190c"


def test_development_configuration_defaults_debug_to_false() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        jwt_secret_key=SECURE_TEST_KEY,
    )

    assert settings.app_debug is False


@pytest.mark.parametrize(
    "placeholder",
    [
        "change-this-secret-key-in-production",
        "replace-with-at-least-32-random-characters",
        "replace-with-a-secret-of-at-least-32-characters",
    ],
)
def test_documented_jwt_placeholders_are_rejected(placeholder: str) -> None:
    with pytest.raises(
        ValidationError,
        match="documented placeholder",
    ) as validation_error:
        Settings(_env_file=None, jwt_secret_key=placeholder)

    assert placeholder not in str(validation_error.value)


def test_jwt_signing_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_short_jwt_signing_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret_key="too-short")


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError, match="APP_DEBUG must be false"):
        Settings(
            _env_file=None,
            app_env="production",
            app_debug=True,
            jwt_secret_key=SECURE_TEST_KEY,
        )


def test_production_accepts_secure_configuration() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        app_debug=False,
        jwt_secret_key=SECURE_TEST_KEY,
    )

    assert settings.app_debug is False
    assert settings.effective_cookie_secure is True
