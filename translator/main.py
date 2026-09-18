"""
main.py
-------
Application entrypoint. Run with:

    uvicorn translator.main:app --reload

This file's only job is composition root: pick a provider based on
config.TRANSLATION_PROVIDER, construct the one shared TranslationService
(so its cache and the provider's reused HTTP client persist across
requests), and attach it to app.state so api.py can reach it per-request.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import config
from .api import router
from .models import TranslateResponse, ErrorDetail, ErrorCode
from .translator_service import TranslationService
from .cache import TranslationCache
from .providers.base import ProviderError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("translator.main")


def _build_provider():
    """
    Provider selection is a single switch statement driven by env var --
    this is the whole "provider is replaceable" story from spec section 5:
    add a new provider class under providers/, add one branch here (or
    even just wire it up in a deployment-specific main.py), done.
    """
    if config.TRANSLATION_PROVIDER == "google":
        from .providers.google_translate_provider import GoogleTranslateProvider
        return GoogleTranslateProvider()
    elif config.TRANSLATION_PROVIDER == "bhashini":
        from .providers.bhashini_provider import BhashiniProvider
        return BhashiniProvider()
    elif config.TRANSLATION_PROVIDER == "libretranslate":
        from .providers.libretranslate_provider import LibreTranslateProvider
        return LibreTranslateProvider()
    elif config.TRANSLATION_PROVIDER == "mymemory":
        from .providers.mymemory_provider import MyMemoryProvider
        return MyMemoryProvider()
    elif config.TRANSLATION_PROVIDER == "anthropic":
        from .providers.anthropic_provider import AnthropicTranslateProvider
        return AnthropicTranslateProvider()
    elif config.TRANSLATION_PROVIDER == "mock":
        from .providers.mock_provider import MockProvider
        logger.warning("Using MockProvider -- set TRANSLATION_PROVIDER=google (or another real "
                        "provider) before deploying. Mock output is not real translation.")
        return MockProvider()
    else:
        raise ProviderError(f"Unknown TRANSLATION_PROVIDER: {config.TRANSLATION_PROVIDER!r}")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Compliance Translation Service",
        description="Translates human-readable fields of a compliance result payload "
                    "into the requested Indian language while preserving all "
                    "machine-readable fields exactly.",
        version="1.0.0",
    )

    provider = _build_provider()
    cache = TranslationCache(ttl_seconds=config.TRANSLATION_CACHE_TTL_SECONDS)
    app.state.translation_service = TranslationService(provider=provider, cache=cache)

    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Converts FastAPI/pydantic's default 422 validation error shape
        # (a list of field-level error objects) into the single error
        # contract documented in the README -- so a malformed body,
        # a missing `target_language`, or `data` sent as the wrong type
        # all come back as {success: false, error: {code, message}} exactly
        # like every other failure path in api.py, rather than a
        # differently-shaped 422 the frontend would need special-case
        # handling for.
        logger.info("Rejected malformed translate request: %s", exc.errors())
        body = TranslateResponse(
            success=False,
            error=ErrorDetail(
                code=ErrorCode.INVALID_REQUEST,
                message="Request body is not valid JSON matching the expected schema "
                        "(`target_language`: string, `data`: object).",
            ),
        )
        return JSONResponse(status_code=400, content=body.model_dump(exclude_none=True))

    @app.get("/health")
    async def health():
        return {"status": "ok", "provider": provider.name}

    return app


app = create_app()