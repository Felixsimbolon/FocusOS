"""Redacted, owner-scoped run records around one model call."""
from dataclasses import dataclass
from datetime import datetime
import time
from uuid import UUID

from focusos_api.database import DatabaseUnavailable, scoped_client
from focusos_api.extractor import (ExtractionFailure, ModelCall, MODEL,
                                   PROMPT_VERSION, SCHEMA_VERSION, extract_structured)


@dataclass(frozen=True)
class RecordedExtraction:
    run_id: UUID
    call: ModelCall


def recorded_extraction(access_token: str, source_id: UUID, source_ref: str,
                        body: str, reference_time: datetime, timezone_name: str) -> RecordedExtraction:
    with scoped_client(access_token) as (_, client):
        run_id = UUID(str(client.rpc("focusos_start_extraction_run", {
            "p_source_id": str(source_id), "p_model": MODEL,
            "p_schema": SCHEMA_VERSION, "p_prompt": PROMPT_VERSION,
        }).execute().data))
    started = time.monotonic()
    call = None
    failure = None
    unexpected = None
    try:
        call = extract_structured(source_ref, body, reference_time, timezone_name)
    except ExtractionFailure as exc:
        failure = exc
    except Exception as exc:
        unexpected = exc
    with scoped_client(access_token) as (_, client):
        finished = client.rpc("focusos_finish_extraction_run", {
            "p_run_id": str(run_id),
            "p_status": "failed" if failure or unexpected else "succeeded",
            "p_latency_ms": call.latency_ms if call else round((time.monotonic()-started)*1000),
            "p_input_tokens": call.input_tokens if call else None,
            "p_output_tokens": call.output_tokens if call else None,
            "p_safe_error": failure.kind if failure else "database_error" if unexpected else None,
        }).execute().data
    if finished is not True:
        raise DatabaseUnavailable("Run outcome could not be recorded")
    if failure:
        raise failure
    if unexpected:
        raise ExtractionFailure("database_error") from unexpected
    return RecordedExtraction(run_id=run_id, call=call)
