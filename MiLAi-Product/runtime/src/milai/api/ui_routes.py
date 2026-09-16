from __future__ import annotations

from flask import Blueprint, Response, make_response, render_template

ui_blueprint = Blueprint("ui", __name__)


@ui_blueprint.get("/")
def index() -> Response:
    response = make_response(render_template("index.html"))
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
