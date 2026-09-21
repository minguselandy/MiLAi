"""Strict argument, request identity, and MCP schema middleware."""

from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from time import time
from typing import Any, ClassVar
from urllib.parse import urlsplit
from uuid import uuid4

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension
from mcp.server.mcpserver.context import Context
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    InputRequiredResult,
    TextContent,
    Tool,
)
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from milai_mcp.aigcit_auth import AigcitErrorMiddleware, AigcitTokenVerifier
from milai_mcp.auth_policy import (
    ALL_TOOL_SCOPES,
    Admission,
    AdmissionDenied,
    AdmissionPolicy,
    AuthDependencyUnavailable,
    project_scope_digest,
)
from milai_mcp.http_transport import HttpResourceBinding
from milai_mcp.input_contracts import (
    CreatePatchInput,
    EvidenceCaptureInput,
    IssueResolutionPatchInput,
    safe_validation_fields,
)
from milai_mcp.oauth_provider import (
    OAuthPublicClientMetadataMiddleware,
    OAuthTokenResourceBindingMiddleware,
)
from milai_mcp.schema_export import inline_tool_schema
from milai_mcp.server_contracts import CodexFullProposalInput
from milai_mcp.server_wire import _wire_sha256

_request_access_token: ContextVar[AccessToken | None] = ContextVar(
    "milai_mcp_request_access_token", default=None
)


class _StrictArguments(Extension):
    identifier = "io.milai/strict-tool-arguments"
    _literal_confirmations: ClassVar[dict[str, str]] = {
        "milai_evidence_capture": "CAPTURE",
        "milai_proposal_create": "SUBMIT",
        "milai_evidence_revoke": "REVOKE",
        "milai_namespace_cleanup_submit": "CLEANUP_NAMESPACE",
    }

    def __init__(
        self,
        allowed: dict[str, frozenset[str]],
        *,
        required: dict[str, frozenset[str]] | None = None,
        examples: dict[str, str] | None = None,
        models: dict[str, type[BaseModel]] | None = None,
    ) -> None:
        self._allowed = allowed
        self._required = required or {}
        self._examples = examples or {}
        self._models = models if models is not None else {}

    def _error(
        self,
        *,
        tool_name: str,
        problem: str,
        reason: str,
        fix: str,
    ) -> CallToolResult:
        payload = {
            "error": "INVALID_TOOL_ARGUMENTS",
            "tool": tool_name,
            "problem": problem,
            "reason": reason,
            "fix": fix,
        }
        example = self._examples.get(tool_name)
        if example is not None:
            payload["example"] = example
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                )
            ],
            is_error=True,
        )

    async def intercept_tool_call(
        self,
        params: CallToolRequestParams,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        arguments = params.arguments or {}
        unexpected = sorted(set(arguments) - self._allowed.get(params.name, frozenset()))
        if unexpected:
            allowed = sorted(self._allowed.get(params.name, frozenset()))
            return self._error(
                tool_name=params.name,
                problem="unexpected arguments: " + ", ".join(unexpected),
                reason="identity, authority and scope are server-owned",
                fix="remove those arguments; allowed arguments are: " + ", ".join(allowed),
            )
        missing = sorted(self._required.get(params.name, frozenset()) - set(arguments))
        if missing:
            return self._error(
                tool_name=params.name,
                problem="missing required arguments: " + ", ".join(missing),
                reason="the requested operation cannot be identified safely",
                fix="add the missing arguments and retry the same intended operation",
            )
        expected_confirmation = self._literal_confirmations.get(params.name)
        supplied_confirmation = arguments.get("confirmation")
        if expected_confirmation is not None and supplied_confirmation != expected_confirmation:
            return self._error(
                tool_name=params.name,
                problem="confirmation literal is invalid",
                reason="the guard prevents an accidental mutation",
                fix=f"set confirmation exactly to {expected_confirmation} after authorization",
            )
        if params.name == "milai_memory_review" and arguments.get("confirmation") != arguments.get(
            "decision"
        ):
            return self._error(
                tool_name=params.name,
                problem="confirmation does not match the review decision",
                reason="the guard prevents accidental approval or rejection",
                fix="set confirmation to the same APPROVE or REJECT value as decision",
            )
        if params.name in self._models:
            try:
                self._models[params.name].model_validate(arguments)
            except ValidationError as exc:
                return CallToolResult(
                    is_error=True,
                    content=[
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "code": "INVALID_ARGUMENT",
                                    "retryable": False,
                                    "fields": safe_validation_fields(
                                        exc.errors(include_input=False, include_url=False),
                                        working_state=params.name == "milai_working_state_update",
                                        compact=params.name
                                        in {
                                            "milai_memory_save",
                                            "milai_memory_read",
                                            "milai_memory_list",
                                            "milai_memory_delete",
                                            "milai_memory_status",
                                        },
                                    ),
                                }
                            ),
                        )
                    ],
                )
        if (
            params.name == "milai_evidence_capture"
            and params.name in self._required
            and "source_type" in arguments
        ):
            try:
                EvidenceCaptureInput.model_validate(arguments)
            except ValidationError as exc:
                return CallToolResult(
                    is_error=True,
                    content=[
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "code": "INVALID_ARGUMENT",
                                    "fields": safe_validation_fields(
                                        exc.errors(include_input=False, include_url=False)
                                    ),
                                    "retryable": False,
                                }
                            ),
                        )
                    ],
                )
        if (
            params.name == "milai_proposal_create"
            and params.name in self._required
            and "proposal" in arguments
        ):
            try:
                CodexFullProposalInput.model_validate(arguments["proposal"])
            except ValidationError as exc:
                fields = safe_validation_fields(exc.errors(include_input=False, include_url=False))
                for field in fields:
                    if field["path"].split(".")[0] in (
                        CreatePatchInput.model_fields.keys()
                        | IssueResolutionPatchInput.model_fields.keys()
                    ):
                        field["path"] = "proposed_patch." + field["path"]
                    field["path"] = "proposal" + ("." + field["path"] if field["path"] else "")
                    if field["type"] == "value_error" and field["path"] == "proposal":
                        field["expected"] = (
                            "CREATE requires a complete patch and no target; non-CREATE requires "
                            "target_claim_id and expected_version_id; authority and scope are "
                            "server-owned"
                        )
                return CallToolResult(
                    is_error=True,
                    content=[
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "code": "INVALID_ARGUMENT",
                                    "fields": fields,
                                    "retryable": False,
                                }
                            ),
                        )
                    ],
                )
        return await call_next(ctx)


class _RequestAccessTokenMiddleware:
    """Carry authenticated HTTP identity into the MCP handler task."""

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        request = ctx.request
        request_scope = getattr(request, "scope", {})
        user = request_scope.get("user") if isinstance(request_scope, dict) else None
        access_token = getattr(user, "access_token", None)
        context_token = _request_access_token.set(
            access_token if isinstance(access_token, AccessToken) else None
        )
        try:
            return await call_next(ctx)
        finally:
            _request_access_token.reset(context_token)


class _StrictSchemaMCPServer(MCPServer):
    hidden_tools: frozenset[str] = frozenset()
    oauth_token_resource_url: str | None = None
    external_binding: HttpResourceBinding | None = None
    external_verifier: AigcitTokenVerifier | None = None
    inline_proposal_schema: bool = False
    inline_all_input_schemas: bool = False

    def streamable_http_app(self, **kwargs: Any) -> Starlette:
        public_resource = (
            self.external_binding.resource_url
            if self.external_binding
            else self.oauth_token_resource_url
        )
        if public_resource is not None:
            # Binding the socket to loopback behind a TLS proxy must not make
            # the SDK reject the server-owned public Host/Origin. Keep an exact
            # allowlist (including a non-default TLS port), never proxy input.
            resource = urlsplit(public_resource)
            kwargs["transport_security"] = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[resource.netloc],
                allowed_origins=[f"{resource.scheme}://{resource.netloc}"],
            )
        app = super().streamable_http_app(**kwargs)
        if self.oauth_token_resource_url is not None:
            app.add_middleware(
                OAuthTokenResourceBindingMiddleware,
                resource_url=self.oauth_token_resource_url,
            )
            app.add_middleware(OAuthPublicClientMetadataMiddleware)
        if self.external_binding is not None:
            binding = self.external_binding
            metadata_path = (
                "/.well-known/oauth-protected-resource" + urlsplit(binding.resource_url).path
            )
            # The SDK couples advertised scopes to endpoint-wide required scopes.
            # Replace only this public route; per-tool intersection stays below.
            app.router.routes[:] = [
                route
                for route in app.router.routes
                if getattr(route, "path", None) != metadata_path
            ]

            async def external_metadata(_request: Request) -> JSONResponse:
                return JSONResponse(
                    {
                        "resource": binding.resource_url,
                        "authorization_servers": [binding.issuer_url],
                        "scopes_supported": list(binding.scopes),
                        "bearer_methods_supported": ["header"],
                    },
                    headers={"Cache-Control": "no-store"},
                )

            app.router.routes.append(Route(metadata_path, external_metadata, methods=["GET"]))
            app.add_middleware(AigcitErrorMiddleware)
        return app

    async def _external_admission(self) -> Admission:
        verifier = self.external_verifier
        token = _request_access_token.get() or get_access_token()
        if verifier is None or token is None:
            raise AdmissionDenied("request_identity_required")
        if token.expires_at is None or token.expires_at <= time():
            raise AdmissionDenied("request_identity_expired")
        claims = token.claims or {}
        subject = claims.get("milai_external_sub")
        granted = claims.get("milai_granted_scopes")
        if (
            claims.get("milai_auth_mode") != "aigcit"
            or claims.get("iss") != verifier.cache.issuer
            or claims.get("milai_deployment_scope_sha256", claims.get("milai_scope_sha256"))
            != verifier.scope_digest
            or token.resource != verifier.resource_url
            or not isinstance(subject, str)
            or not isinstance(granted, list)
            or not all(isinstance(scope, str) for scope in granted)
        ):
            raise AdmissionDenied("request_identity_invalid")
        admission = await asyncio.to_thread(verifier.policy.admit, subject, frozenset(granted))
        if token.subject != admission.principal_id:
            raise AdmissionDenied("request_identity_invalid")
        expected_digest = (
            project_scope_digest(admission.project_id)
            if admission.project_id is not None
            else verifier.scope_digest
        )
        if (
            claims.get("milai_scope_sha256") != expected_digest
            or claims.get("milai_project_id") != admission.project_id
        ):
            raise AdmissionDenied("request_scope_invalid")
        return admission

    def _audit_external_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        reason: str,
        admission: Admission | None = None,
    ) -> None:
        token = _request_access_token.get() or get_access_token()
        binding = self.external_binding
        operation = arguments.get("operation_id")
        runtime_operation = None
        if (
            admission is not None
            and binding is not None
            and name in ALL_TOOL_SCOPES
            and isinstance(operation, str)
        ):
            runtime_operation = _wire_sha256(
                {
                    "host_principal_id": admission.principal_id,
                    "scope_sha256": (token.claims or {}).get("milai_scope_sha256")
                    if token
                    else None,
                    "tool": name,
                    "operation_id": operation,
                }
            )
        logging.getLogger("milai_mcp.auth").info(
            json.dumps(
                {
                    "event": "tool_authorization",
                    "request_id": uuid4().hex,
                    "principal": admission.principal_id if admission else None,
                    "client_id": token.client_id if token and admission else None,
                    "policy_version": admission.policy_version if admission else None,
                    "tool": name if name in ALL_TOOL_SCOPES else "unknown_tool",
                    "granted_scopes": sorted(admission.granted_scopes) if admission else [],
                    "effective_scopes": sorted(admission.effective_scopes) if admission else [],
                    "reason": reason,
                    "runtime_operation_id": runtime_operation,
                },
                sort_keys=True,
            )
        )

    async def authorize_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> CallToolResult | None:
        """Authorize both public entrypoints and each private facade operation."""
        if self.external_verifier is not None:
            admission = None
            try:
                admission = await self._external_admission()
                if not AdmissionPolicy.allows_tool(name, set(admission.effective_scopes)):
                    raise AdmissionDenied("insufficient_scope")
            except (AdmissionDenied, AuthDependencyUnavailable) as exc:
                code = (
                    "auth_dependency_unavailable"
                    if isinstance(exc, AuthDependencyUnavailable)
                    else "insufficient_scope"
                )
                self._audit_external_tool(name, arguments, code, admission)
                return CallToolResult(is_error=True, content=[TextContent(type="text", text=code)])
            self._audit_external_tool(name, arguments, "allowed", admission)
        return None

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[Any, Any] | None = None,
    ) -> CallToolResult | InputRequiredResult:
        denied = await self.authorize_tool(name, arguments)
        if denied is not None:
            return denied
        return await super().call_tool(name, arguments, context)

    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        if self.external_verifier is not None:
            admission = await self._external_admission()
            scopes = set(admission.effective_scopes)
            registered = sorted(tool.name for tool in tools)
            tools = [tool for tool in tools if AdmissionPolicy.allows_tool(tool.name, scopes)]
            visible = sorted(tool.name for tool in tools if tool.name not in self.hidden_tools)
            logging.getLogger("milai_mcp.auth").info(
                json.dumps(
                    {
                        "event": "tool_directory_authorization",
                        "request_id": uuid4().hex,
                        "granted_scopes": sorted(admission.granted_scopes),
                        "enabled_scopes": sorted(self.external_verifier.policy.enabled_scopes),
                        "effective_scopes": sorted(scopes),
                        "registered_tools": registered,
                        "visible_tools": visible,
                        "filtered_tools": sorted(set(registered) - set(visible)),
                    },
                    sort_keys=True,
                )
            )
        return [
            tool.model_copy(
                update={
                    "input_schema": {
                        **(
                            inline_tool_schema(tool.input_schema)
                            if self.inline_all_input_schemas
                            or (
                                self.inline_proposal_schema and tool.name == "milai_proposal_create"
                            )
                            else tool.input_schema
                        ),
                        "additionalProperties": False,
                    }
                }
            )
            for tool in tools
            if tool.name not in self.hidden_tools
        ]
