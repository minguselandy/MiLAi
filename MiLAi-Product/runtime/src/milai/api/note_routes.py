"""Private Host note API. Identity binding is supplied by the trusted Host."""

from typing import cast

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from milai.api.auth import authenticated_context
from milai.api.errors import ApiError
from milai.application.host_note import HostNoteService
from milai.domain.host_note import NoteBrowse, NoteGet, NoteOperationGet, NoteWrite
from milai.persistence.database import SessionContext
from milai.persistence.host_note_repository import NoteError

note_blueprint = Blueprint("notes", __name__, url_prefix="/v1/notes")


@note_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


@note_blueprint.errorhandler(NoteError)
def note_error(error: NoteError):  # type: ignore[no-untyped-def]
    code = str(error)
    status = 404 if code in {"NOTE_NOT_FOUND", "NOTE_OPERATION_NOT_FOUND"} else 409
    if code in {"INVALID_NOTE", "INVALID_NOTE_CURSOR"}:
        status = 400
    elif code == "NOTE_SCOPE_DENIED":
        status = 403
    return jsonify({"error": {
        "code": code, "message": "Note operation could not be completed.", "retryable": False,
        "request_id": g.request_id,
    }}), status


@note_blueprint.errorhandler(ValidationError)
def validation_error(error: ValidationError):  # type: ignore[no-untyped-def]
    return jsonify({"error": {
        "code": "INVALID_REQUEST", "message": "Note input does not match its public contract.",
        "retryable": False, "details": {"fields": [
            {"path": ".".join(map(str, item["loc"])), "type": item["type"]}
            for item in error.errors(include_input=False, include_url=False)
        ]},
    }}), 400


def _service() -> HostNoteService:
    return cast(HostNoteService, current_app.extensions["milai.host_note_service"])


def _context() -> SessionContext:
    return cast(SessionContext, g.session_context)


@note_blueprint.post("/write")
def write_note():  # type: ignore[no-untyped-def]
    operation_id = request.headers.get("Idempotency-Key", "")
    if not 1 <= len(operation_id) <= 128:
        raise ApiError(code="INVALID_REQUEST", message="Stable Idempotency-Key required (1..128).",
                       status_code=400)
    command = NoteWrite.model_validate(request.get_json(silent=True))
    result = _service().write(_context(), command, operation_id)
    return jsonify({**result, "request_id": g.request_id})


@note_blueprint.post("/get")
def get_note():  # type: ignore[no-untyped-def]
    command = NoteGet.model_validate(request.get_json(silent=True))
    return jsonify({**_service().get(_context(), command), "request_id": g.request_id})


@note_blueprint.post("/browse")
def browse_notes():  # type: ignore[no-untyped-def]
    command = NoteBrowse.model_validate(request.get_json(silent=True))
    return jsonify({**_service().browse(_context(), command), "request_id": g.request_id})


@note_blueprint.post("/operations/get")
def get_note_operation():  # type: ignore[no-untyped-def]
    command = NoteOperationGet.model_validate(request.get_json(silent=True))
    return jsonify({**_service().operation(_context(), command), "request_id": g.request_id})
