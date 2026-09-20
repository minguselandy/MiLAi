"use strict";

const byId = (id) => document.getElementById(id);
const output = (value) => { byId("result").textContent = JSON.stringify(value, null, 2); };
const ids = (id) => byId(id).value.split(",").map((value) => value.trim()).filter(Boolean);
let capabilities = null;

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function api(path, options = {}) {
  const token = byId("token").value;
  const headers = {"Authorization": `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {})};
  const response = await fetch(path, {...options, headers});
  const body = await response.json();
  output(body);
  if (!response.ok) throw new Error(body.error?.code || `HTTP_${response.status}`);
  return body;
}

function classificationAllowed(value) {
  if (!capabilities) return false;
  if (capabilities.data_mode === "LOCAL_PERSONAL_DATA") return true;
  if (capabilities.data_mode === "DEIDENTIFIED_ALLOWED") return value !== "PERSONAL";
  return value === "SYNTHETIC";
}

function updateDataGate() {
  const classification = byId("data-classification").value;
  const allowed = classificationAllowed(classification);
  byId("capture-evidence").disabled = !allowed;
  byId("data-gate-message").textContent = capabilities
    ? `Runtime data mode=${capabilities.data_mode}; ${classification} ${allowed ? "允许进入非 canonical Evidence" : "被当前 gate 阻断"}。`
    : "尚未连接；Evidence capture 保持禁用。";
}

async function loadProposals() {
  const inbox = await api("/v1/proposals?status=PENDING_REVIEW&limit=50");
  byId("proposal-inbox").textContent = JSON.stringify(inbox, null, 2);
  return inbox;
}

byId("connect").addEventListener("click", async () => {
  try {
    const [document, ready, watermarks] = await Promise.all([
      api("/v1/capabilities"),
      api("/health/ready"),
      api("/v1/system/watermarks")
    ]);
    capabilities = document;
    byId("data-mode-badge").textContent = `Data mode: ${document.data_mode}`;
    byId("profile-badge").textContent = `Agent profile: ${document.profile}`;
    byId("crypto-badge").textContent = `Encrypted Blob: ${document.features.encrypted_blob ? "ENABLED" : "DISABLED"}`;
    byId("remote-badge").textContent = `Remote: ${document.features.remote_access ? "ENABLED" : "DISABLED"}`;
    byId("connection-status").textContent = JSON.stringify({ready, capabilities: document, watermarks}, null, 2);
    byId("copy-mcp").disabled = false;
    updateDataGate();
    await loadProposals();
  } catch (_) {
    capabilities = null;
    updateDataGate();
  }
});

byId("data-classification").addEventListener("change", updateDataGate);

byId("copy-mcp").addEventListener("click", async () => {
  const profile = capabilities?.profile === "operator"
    ? "operator"
    : capabilities?.profile === "submitter" ? "submitter" : "reader";
  const tokenPlaceholder = "${MILAI_AGENT_" + profile.toUpperCase() + "_TOKEN}";
  const config = {
    mcpServers: {
      milai: {
        command: "milai-mcp",
        args: ["--profile", profile],
        env: {
          MILAI_BASE_URL: window.location.origin,
          MILAI_AGENT_TOKEN: tokenPlaceholder,
          MILAI_AGENT_SCOPE_JSON: byId("scope").value,
          MILAI_AGENT_REQUIRED_AUTHORITY: byId("authority").value
        }
      }
    }
  };
  const serialized = JSON.stringify(config, null, 2);
  try { await navigator.clipboard.writeText(serialized); } catch (_) { /* render fallback */ }
  output({status: "SECRET_FREE_MCP_CONFIG_READY", config});
});

byId("capture-evidence").addEventListener("click", async () => {
  const classification = byId("data-classification").value;
  if (!classificationAllowed(classification)) {
    output({error: {code: "DATA_MODE_BLOCKED"}});
    return;
  }
  if (!byId("capture-confirmed").checked) {
    output({error: {code: "CAPTURE_CONFIRMATION_REQUIRED"}});
    return;
  }
  try {
    const result = await api("/v1/evidence", {
      method: "POST",
      headers: {"Idempotency-Key": crypto.randomUUID()},
      body: JSON.stringify({
        source_type: "USER_OBSERVATION",
        source_ref: byId("capture-source").value,
        subject_id: byId("capture-subject").value,
        observed_at: new Date().toISOString(),
        content: byId("capture-content").value,
        data_classification: classification,
        media_type: "text/plain",
        permission_snapshot: {readable: true, classification},
        retention_state: "READABLE"
      })
    });
    byId("evidence-id").value = result.evidence_id || "";
    byId("inspect-evidence-id").value = result.evidence_id || "";
  } catch (_) { /* the safe error envelope is already rendered */ }
});

byId("load-proposals").addEventListener("click", async () => {
  try { await loadProposals(); } catch (_) { /* rendered */ }
});

byId("chat").addEventListener("click", async () => {
  try {
    const actionSensitive = byId("action-sensitive").checked;
    const confirmed = byId("live-confirmation").checked;
    const query = byId("query").value;
    const activeGoal = byId("goal").value;
    const requestedScope = JSON.parse(byId("scope").value);
    const requiredAuthority = byId("authority").value;
    const actionDigest = actionSensitive
      ? await sha256Hex(canonicalJson(JSON.parse(byId("action").value)))
      : null;
    if (actionSensitive && confirmed && !capabilities) {
      capabilities = await api("/v1/capabilities");
    }
    let confirmationEvidenceId = null;
    let confirmationNonce = null;
    if (actionSensitive && confirmed) {
      confirmationNonce = crypto.randomUUID();
      const bindingDigest = await sha256Hex(canonicalJson({
        tenant_id: capabilities.tenant_id,
        query,
        active_goal: activeGoal,
        requested_scope: requestedScope,
        required_authority: requiredAuthority,
        action_digest: actionDigest
      }));
      const confirmation = await api("/v1/evidence", {
        method: "POST",
        headers: {"Idempotency-Key": crypto.randomUUID()},
        body: JSON.stringify({
          source_type: "USER_CONFIRMATION",
          source_ref: `chat-confirmation:v2:${confirmationNonce}:${bindingDigest}`,
          subject_id: "action-sensitive-chat",
          observed_at: new Date().toISOString(),
          content: "CONFIRM_ACTION",
          media_type: "text/plain",
          permission_snapshot: {readable: true, scope: "local"},
          retention_state: "READABLE"
        })
      });
      confirmationEvidenceId = confirmation.evidence_id;
    }
    const body = {
      query,
      active_goal: activeGoal,
      requested_scope: requestedScope,
      required_authority: requiredAuthority,
      action_sensitive: actionSensitive,
      action_digest: actionDigest,
      live_confirmation: actionSensitive && confirmed ? "CONFIRM_ACTION" : null,
      confirmation_evidence_id: confirmationEvidenceId,
      confirmation_nonce: confirmationNonce
    };
    const result = await api("/v1/chat", {method: "POST", body: JSON.stringify(body)});
    if (result.retrieval_trace_id) {
      byId("trace-id").value = result.retrieval_trace_id;
      byId("inspect-trace-id").value = result.retrieval_trace_id;
    }
    if (result.evidence_refs?.[0]) {
      byId("evidence-id").value = result.evidence_refs[0];
      byId("inspect-evidence-id").value = result.evidence_refs[0];
    }
  } catch (_) { /* the safe error envelope is already rendered */ }
});

byId("trace").addEventListener("click", async () => {
  try { await api(`/v1/retrieval-traces/${encodeURIComponent(byId("trace-id").value)}`); } catch (_) { /* rendered */ }
});

byId("inspect").addEventListener("click", async () => {
  const targets = [
    ["claim", "inspect-claim-id", "/v1/claims/"],
    ["evidence", "inspect-evidence-id", "/v1/evidence/"],
    ["open_issue", "inspect-issue-id", "/v1/open-issues/"],
    ["retrieval_trace", "inspect-trace-id", "/v1/retrieval-traces/"]
  ];
  const result = {};
  for (const [name, input, prefix] of targets) {
    const value = byId(input).value.trim();
    if (!value) continue;
    try { result[name] = await api(`${prefix}${encodeURIComponent(value)}`); }
    catch (_) { result[name] = {status: "UNAVAILABLE_OR_UNAUTHORIZED"}; }
  }
  output(result);
});

byId("correct").addEventListener("click", async () => {
  try {
    const result = await api("/v1/proposals", {
      method: "POST",
      headers: {"Idempotency-Key": crypto.randomUUID()},
      body: JSON.stringify(JSON.parse(byId("proposal").value))
    });
    if (result.proposal_id) byId("proposal-id").value = result.proposal_id;
    await loadProposals();
  } catch (_) { /* rendered */ }
});

byId("review").addEventListener("click", async () => {
  try {
    await api(`/v1/proposals/${encodeURIComponent(byId("proposal-id").value)}/review`, {
      method: "POST",
      headers: {"Idempotency-Key": crypto.randomUUID()},
      body: JSON.stringify({decision: byId("decision").value, policy_version: "local-ui-v1", reason_code: "LOCAL_USER_REVIEW"})
    });
    await loadProposals();
  } catch (_) { /* rendered */ }
});

byId("capture-episode").addEventListener("click", async () => {
  try {
    const result = await api("/v1/episodes", {
      method: "POST",
      headers: {"Idempotency-Key": crypto.randomUUID()},
      body: JSON.stringify({
        subject_id: byId("episode-subject").value,
        evidence_refs: ids("episode-evidence-ids"),
        chat_turn_refs: ids("episode-chat-ids"),
        context_capsule_refs: ids("episode-context-ids")
      })
    });
    byId("episode-id").value = result.episode_id || "";
    byId("episode-revision").value = result.revision || 1;
  } catch (_) { /* rendered */ }
});

byId("settle-episode").addEventListener("click", async () => {
  if (!window.confirm("Settlement 会关闭 Episode 并使其 ContextCapsule 过期。确定继续？")) return;
  try {
    const result = await api(`/v1/episodes/${encodeURIComponent(byId("episode-id").value)}/settle`, {
      method: "POST",
      headers: {"Idempotency-Key": crypto.randomUUID()},
      body: JSON.stringify({
        expected_revision: Number(byId("episode-revision").value),
        residual_proposal_ids: ids("episode-proposal-ids"),
        open_issue_ids: ids("episode-issue-ids"),
        confirmation: "SETTLE"
      })
    });
    byId("episode-revision").value = result.revision || byId("episode-revision").value;
  } catch (_) { /* rendered */ }
});

byId("revoke").addEventListener("click", async () => {
  if (!window.confirm("撤销会立即阻断相关 Claim，并异步清理副本。确定继续？")) return;
  try {
    await api(`/v1/evidence/${encodeURIComponent(byId("evidence-id").value)}/revoke`, {
      method: "POST",
      headers: {"Idempotency-Key": crypto.randomUUID()},
      body: JSON.stringify({reason_code: "LOCAL_USER_REQUEST", confirmation: "REVOKE"})
    });
    byId("inspect-evidence-id").value = byId("evidence-id").value;
  } catch (_) { /* rendered */ }
});
