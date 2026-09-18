"""
api.py
------
The HTTP boundary. This is intentionally thin: it validates the request
shape, delegates to TranslationService, and maps whatever happens (success
or a specific typed failure) onto the response contract from spec
section 8/12. No translation logic lives here -- that's the point of
having translator_service as a separate, framework-free layer.

Error mapping is centralized in one place (`_error_response`) so every
failure path returns the same JSON shape, which is what lets the frontend
developer write one generic "if not success, show error.message" branch
instead of handling each error code differently.
"""

import logging
import time

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import config
from .models import TranslateRequest, TranslateResponse, ErrorDetail, ErrorCode
from .translator_service import (
    TranslationService, InvalidLanguageError, InvalidRequestError,
)
from .providers.base import ProviderTimeoutError, ProviderRateLimitError, ProviderError

# Deliberately not logging request bodies anywhere in this file -- see
# spec section 11 ("be careful with logging the submitted compliance
# data"). Only metadata (language, latency, error class) is logged.
logger = logging.getLogger("translator.api")

router = APIRouter()


def _error_response(status_code: int, code: ErrorCode, message: str) -> JSONResponse:
    body = TranslateResponse(success=False, error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


@router.post("/api/translate", response_model=TranslateResponse)
async def translate_endpoint(payload: TranslateRequest, request: Request):
    # `payload: TranslateRequest` (rather than the raw `Request` object) is
    # what makes FastAPI's auto-generated /docs page know the request body
    # shape and render an editable, pre-filled example -- a plain `Request`
    # parameter gives FastAPI no schema to show, which is why /docs
    # previously rendered with no body box at all. Malformed JSON or a
    # payload that doesn't match the schema is now handled by the
    # `validation_exception_handler` registered in main.py, which converts
    # FastAPI's default 422 shape into our own INVALID_REQUEST contract --
    # so every error path (this one included) still returns the same
    # {success, error: {code, message}} shape documented in the README.
    parsed = payload

    if not parsed.data:
        return _error_response(400, ErrorCode.MISSING_DATA, "`data` must be a non-empty object.")

    if parsed.target_language not in config.SUPPORTED_LANGUAGES:
        return _error_response(
            400, ErrorCode.INVALID_LANGUAGE,
            f"'{parsed.target_language}' is not a supported target_language. "
            f"Supported: {', '.join(sorted(config.SUPPORTED_LANGUAGES))}.",
        )

    service: TranslationService = request.app.state.translation_service
    start = time.perf_counter()

    try:
        result = await service.translate(parsed.data, parsed.target_language)
    except (InvalidLanguageError,) as exc:
        return _error_response(400, ErrorCode.INVALID_LANGUAGE, str(exc))
    except InvalidRequestError as exc:
        return _error_response(400, ErrorCode.MISSING_DATA, str(exc))
    except ProviderTimeoutError:
        logger.warning("Translation provider timed out (lang=%s)", parsed.target_language)
        return _error_response(504, ErrorCode.TRANSLATION_TIMEOUT, "Translation service is temporarily unavailable.")
    except ProviderRateLimitError:
        logger.warning("Translation provider rate-limited (lang=%s)", parsed.target_language)
        return _error_response(429, ErrorCode.RATE_LIMITED, "Translation service is temporarily rate-limited.")
    except ProviderError as exc:
        logger.error("Translation provider error (lang=%s): %s", parsed.target_language, type(exc).__name__)
        return _error_response(502, ErrorCode.PROVIDER_ERROR, "Translation service is temporarily unavailable.")
    except Exception as exc:  # last-resort catch-all -- never leak a stack trace to the caller
        logger.exception("Unexpected error during translation")
        return _error_response(500, ErrorCode.TRANSLATION_PROVIDER_ERROR, "Translation service is temporarily unavailable.")

    total_ms = (time.perf_counter() - start) * 1000

    response = TranslateResponse(
        success=True,
        target_language=result.target_language,
        data=result.data,
        translation_time_ms=round(total_ms, 2),
    )
    if config.EXPOSE_TIMING_BREAKDOWN:
        response.provider_latency_ms = round(result.provider_latency_ms, 2)
        response.backend_latency_ms = round(result.total_backend_latency_ms, 2)
        response.provider = result.provider_name

    return JSONResponse(status_code=200, content=response.model_dump(exclude_none=True))