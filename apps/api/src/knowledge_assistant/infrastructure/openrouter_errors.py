import logging
from typing import NoReturn

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_PUBLIC_ERROR = (
    "The AI provider is temporarily unavailable. Please try again later."
)


def raise_openrouter_request_error(
    error: httpx.HTTPError,
    *,
    operation: str,
) -> NoReturn:
    if isinstance(error, httpx.HTTPStatusError):
        request_id = _safe_request_id(error.response)
        logger.warning(
            "OpenRouter %s failed with status %s (request_id=%s).",
            operation,
            error.response.status_code,
            request_id,
        )
    else:
        logger.warning(
            "OpenRouter %s failed with transport error %s.",
            operation,
            type(error).__name__,
        )
    raise RuntimeError(OPENROUTER_PUBLIC_ERROR) from error


def raise_openrouter_response_error(
    error: Exception,
    *,
    operation: str,
) -> NoReturn:
    logger.warning(
        "OpenRouter %s returned an invalid response (%s).",
        operation,
        type(error).__name__,
    )
    raise RuntimeError(OPENROUTER_PUBLIC_ERROR) from error


def _safe_request_id(response: httpx.Response) -> str:
    value = response.headers.get("x-request-id", "unavailable")
    return "".join(
        character
        for character in value[:128]
        if character.isprintable()
    ) or "unavailable"
