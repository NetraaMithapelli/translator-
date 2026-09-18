"""
models.py
---------
Pydantic schemas for the HTTP API layer only. Deliberately kept separate
from translator_service's own TranslationResult dataclass -- the service
layer has no dependency on pydantic/FastAPI, so it can be unit-tested (and
reused from a CLI, a queue worker, etc.) without pulling in a web
framework. api.py is the adapter between the two.
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    INVALID_LANGUAGE = "INVALID_LANGUAGE"
    INVALID_REQUEST = "INVALID_REQUEST"
    MISSING_DATA = "MISSING_DATA"
    TRANSLATION_TIMEOUT = "TRANSLATION_TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSLATION_PROVIDER_ERROR = "TRANSLATION_PROVIDER_ERROR"


class TranslateRequest(BaseModel):
    target_language: str = Field(..., description="ISO-ish language code, e.g. 'hi', 'mr'.")
    data: dict[str, Any] = Field(..., description="The structured compliance JSON to translate.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "target_language": "hi",
                "data": {
                    "product_id": "LOCAL_SNACK_002",
                    "product_name": "Demo Local Snack",
                    "status": "NON_COMPLIANT",
                    "rules_checked": 12,
                    "rules_passed": 5,
                    "rules_failed": 5,
                    "rules_review_required": 0,
                    "rules_not_applicable": 2,
                    "generated_at": "2026-09-15T12:30:00Z",
                },
            }
        }
    }


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class TranslateResponse(BaseModel):
    success: bool
    target_language: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    translation_time_ms: Optional[float] = None
    provider_latency_ms: Optional[float] = None
    backend_latency_ms: Optional[float] = None
    provider: Optional[str] = None
    error: Optional[ErrorDetail] = None