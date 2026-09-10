"""HTTP API: parse input, run the pipeline, map errors to status codes. No business logic here."""

import base64
import binascii
import hashlib
import json
import logging
import time
import uuid
from datetime import date
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from validator import __version__
from validator.config import Settings, load_settings
from validator.ingest import (
    Document,
    DocumentError,
    PdfText,
    UnsupportedMediaType,
    document_from_bytes,
    document_from_text,
)
from validator.models import (
    ExtractionResponse,
    ExtractRequest,
    RuleConfig,
    ValidateRequest,
    ValidationResponse,
)
from validator.observability import configure_logging, request_id_var
from validator.pipeline import ExtractionRun, Pipeline, ValidationRun, build_pipeline

logger = logging.getLogger("validator.api")

EXAMPLE_CONFIG = {
    "document_type": "SUPPLIER_INVOICE",
    "max_age_days": 90,
    "allowed_currencies": ["EUR", "GBP"],
    "required_fields": ["supplier_name", "invoice_number", "invoice_date", "total_amount"],
}


class InvalidRequest(Exception):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.details = details


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local $refs; FastAPI does not hoist $defs from openapi_extra into components."""
    definitions = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(definitions[node["$ref"].rsplit("/", 1)[-1]])
            return {key: resolve(value) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _request_body(model: type[BaseModel], with_config: bool) -> dict[str, Any]:
    multipart: dict[str, Any] = {
        "type": "object",
        "required": ["file"],
        "properties": {
            "file": {
                "type": "string",
                "format": "binary",
                "description": "PDF with a text layer, or a UTF-8 text file",
            }
        },
    }
    if with_config:
        multipart["required"].append("config")
        multipart["properties"]["config"] = {
            "type": "string",
            "description": "RuleConfig as a JSON string",
            "example": json.dumps(EXAMPLE_CONFIG),
        }
        multipart["properties"]["reference_date"] = {
            "type": "string",
            "format": "date",
            "description": "Date the invoice age is measured against; defaults to today",
        }
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": _inline_refs(model.model_json_schema())},
                "multipart/form-data": {"schema": multipart},
            },
        }
    }


def _validation_details(exc: ValidationError) -> Any:
    return json.loads(exc.json(include_url=False))


async def _read_input(
    request: Request, with_config: bool, pdf_text: PdfText
) -> tuple[Document, RuleConfig | None, date | None]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type == "application/json":
        return await _read_json(request, with_config, pdf_text)
    if content_type == "multipart/form-data":
        return await _read_multipart(request, with_config, pdf_text)
    raise UnsupportedMediaType(
        f"unsupported content type '{content_type or 'none'}'; "
        "use application/json or multipart/form-data"
    )


async def _read_json(
    request: Request, with_config: bool, pdf_text: PdfText
) -> tuple[Document, RuleConfig | None, date | None]:
    try:
        raw = await request.json()
    except json.JSONDecodeError as exc:
        raise InvalidRequest("request body is not valid JSON") from exc
    model = ValidateRequest if with_config else ExtractRequest
    try:
        body = model.model_validate(raw)
    except ValidationError as exc:
        raise InvalidRequest(
            "request body does not match the schema", _validation_details(exc)
        ) from exc
    source = body.document
    if source.text is not None:
        document = document_from_text(source.text)
    else:
        try:
            data = base64.b64decode(source.content_base64 or "", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidRequest("content_base64 is not valid base64") from exc
        document = document_from_bytes(data, source.media_type, source.filename, pdf_text)
    if isinstance(body, ValidateRequest):
        return document, body.config, body.reference_date
    return document, None, None


async def _read_multipart(
    request: Request, with_config: bool, pdf_text: PdfText
) -> tuple[Document, RuleConfig | None, date | None]:
    form = await request.form()
    upload = form.get("file")
    if upload is None or isinstance(upload, str):
        raise InvalidRequest("multipart body needs a 'file' part")
    document = document_from_bytes(
        await upload.read(), upload.content_type, upload.filename, pdf_text
    )
    if not with_config:
        return document, None, None
    raw_config = form.get("config")
    if not isinstance(raw_config, str):
        raise InvalidRequest("multipart body needs a 'config' part containing JSON")
    try:
        config = RuleConfig.model_validate_json(raw_config)
    except ValidationError as exc:
        raise InvalidRequest("config does not match the schema", _validation_details(exc)) from exc
    raw_date = form.get("reference_date")
    try:
        reference_date = (
            date.fromisoformat(raw_date) if isinstance(raw_date, str) and raw_date else None
        )
    except ValueError as exc:
        raise InvalidRequest("reference_date must be YYYY-MM-DD") from exc
    return document, config, reference_date


def _error(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error})


def _run_fields(document: Document, run: ExtractionRun) -> dict[str, Any]:
    """What the request log line records about one run: never the document's content."""
    return {
        "extractor_used": run.extractor_used,
        "model": run.llm.model if run.llm else None,
        "prompt_version": run.llm.prompt_version if run.llm else None,
        "llm_latency_ms": run.llm.latency_ms if run.llm else None,
        "input_tokens": run.llm.input_tokens if run.llm else None,
        "output_tokens": run.llm.output_tokens if run.llm else None,
        "estimated_cost_usd": run.llm.estimated_cost_usd if run.llm else None,
        "verdict": run.status.value if isinstance(run, ValidationRun) else None,
        "document_chars": len(document.text),
        "document_sha256": hashlib.sha256(document.text.encode("utf-8")).hexdigest()[:16],
    }


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    pipeline = pipeline or build_pipeline(settings)
    app = FastAPI(
        title="AI Document Validator",
        version=__version__,
        description="Extracts supplier-invoice fields and validates them against configurable rules.",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            # One line per request: id, latency, and for document requests the model and verdict.
            logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    **getattr(request.state, "log_fields", {}),
                },
            )
            return response
        finally:
            request_id_var.reset(token)

    @app.exception_handler(InvalidRequest)
    async def _invalid_request(request: Request, exc: InvalidRequest) -> JSONResponse:
        return _error(422, "invalid_request", str(exc), exc.details)

    @app.exception_handler(DocumentError)
    async def _document_error(request: Request, exc: DocumentError) -> JSONResponse:
        return _error(exc.status_code, exc.code, str(exc))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error")
        return _error(500, "internal_error", "unexpected server error")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "extractor": settings.extractor}

    @app.post(
        "/v1/validate",
        response_model=ValidationResponse,
        openapi_extra=_request_body(ValidateRequest, with_config=True),
        summary="Extract fields and validate them against business rules",
    )
    async def validate(request: Request) -> ValidationResponse:
        document, config, reference_date = await _read_input(
            request, with_config=True, pdf_text=settings.pdf_text
        )
        if config is None:
            raise InvalidRequest("config is required")
        run = await run_in_threadpool(
            pipeline.validate, document, config, reference_date or date.today()
        )
        request.state.log_fields = _run_fields(document, run)
        return ValidationResponse(
            request_id=request_id_var.get() or "",
            extractor_used=run.extractor_used,
            extraction=run.extraction,
            llm=run.llm,
            warnings=run.warnings,
            status=run.status,
            reference_date=run.reference_date,
            rules=run.rules,
        )

    @app.post(
        "/v1/extract",
        response_model=ExtractionResponse,
        openapi_extra=_request_body(ExtractRequest, with_config=False),
        summary="Extract fields only, without evaluating rules",
    )
    async def extract(request: Request) -> ExtractionResponse:
        document, _, _ = await _read_input(request, with_config=False, pdf_text=settings.pdf_text)
        run = await run_in_threadpool(pipeline.extract, document)
        request.state.log_fields = _run_fields(document, run)
        return ExtractionResponse(
            request_id=request_id_var.get() or "",
            extractor_used=run.extractor_used,
            extraction=run.extraction,
            llm=run.llm,
            warnings=run.warnings,
        )

    return app
