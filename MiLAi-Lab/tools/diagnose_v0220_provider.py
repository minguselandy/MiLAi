"""Read-only stopped-request evidence and CPU backend probes. Never sends completions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

import httpx

from v0220_evidence import read, save, seal, sha, validate

CONTAINER = "bcec1ef46198"
CPU_PROBE = r"""
import sys,json,traceback,importlib.metadata
from types import SimpleNamespace
import xgrammar
from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
from vllm.config.structured_outputs import StructuredOutputsConfig
from vllm.v1.structured_output.backend_xgrammar import validate_xgrammar_grammar
from vllm.v1.structured_output.backend_guidance import validate_guidance_grammar
request=json.load(sys.stdin)
schema=request['response_format']['json_schema']['schema']
results=[]
def probe(name,call):
    try:
        call()
        row={'name':name,'status':'PASS'}
    except Exception as exc:
        row={'name':name,'status':'REJECTED','exception_type':type(exc).__name__,
             'message':str(exc),
             'frames':[{'file':f.filename,'line':f.lineno,'function':f.name}
                       for f in traceback.extract_tb(exc.__traceback__)]}
    results.append(row)
def params():
    return ChatCompletionRequest.model_validate(request).to_sampling_params(4096,{})
probe('native_xgrammar_parse',lambda:xgrammar.Grammar.from_json_schema(schema))
probe('pydantic_sampling',params)
probe('vllm_xgrammar_validation',lambda:validate_xgrammar_grammar(params()))
probe('vllm_guidance_validation',lambda:validate_guidance_grammar(params()))
probe('vllm_default_auto_validation',lambda:params()._validate_structured_outputs(
    SimpleNamespace(is_diffusion=False),StructuredOutputsConfig(),object()))
print(json.dumps({'results':results,
 'versions':{p:importlib.metadata.version(p) for p in ('vllm','xgrammar','llguidance')},
 'default_backend':StructuredOutputsConfig().backend,
 'model_requests':0,'model_config_stub':'is_diffusion=False; non-Mistral tokenizer sentinel',
 'scope':'CPU validation only, not a reproduction of original HTTP handler or GPU execution'}))
"""


def command(argv: list[str], *, data: str | None = None) -> dict:
    result = subprocess.run(  # noqa: S603 - fixed read-only Docker/diagnostic argv
        argv, input=data, capture_output=True, text=True, timeout=45
    )
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def diagnose(source: Path, root: Path) -> dict:
    validate(source)
    request = source / "episodes/v2c1-01/v2c1-01-01-request.json"
    http = source / "episodes/v2c1-01/v2c1-01-01-http.json"
    seal(
        root,
        entries=[Path(__file__)],
        inputs=[
            source / "manifest.json",
            source / "result.json",
            source / "run-started.json",
            request,
            http,
        ],
        contract={
            "stage": "READ_ONLY_PROVIDER_FAILURE_DIAGNOSIS",
            "container": CONTAINER,
            "model_requests": 0,
            "no_service_changes": True,
            "not_usage_settlement": True,
        },
    )
    started = read(source / "run-started.json")["unix"]
    def iso(value):
        return dt.datetime.fromtimestamp(value, dt.UTC).isoformat()
    logs = command(
        ["docker", "logs", "--since", iso(started - 2), "--until", iso(started + 8), CONTAINER]
    )
    save(root / "server-log-window.json", logs)
    inspection = command(["docker", "inspect", "--format", "{{.Image}}", CONTAINER])
    save(root / "server-image.json", inspection)
    probe = command(
        ["docker", "exec", "-i", CONTAINER, "python3", "-c", CPU_PROBE], data=request.read_text()
    )
    save(root / "cpu-probes.json", probe)
    if probe["returncode"] != 0:
        raise ValueError("CPU_DIAGNOSTIC_INCOMPLETE")
    cpu = json.loads(probe["stdout"].splitlines()[-1])
    save(root / "cpu-probes-parsed.json", cpu)
    statuses = {r["name"]: r for r in cpu["results"]}
    assert statuses["native_xgrammar_parse"]["status"] == "PASS"
    assert statuses["vllm_xgrammar_validation"]["status"] == "REJECTED"
    assert "uniqueItems" in statuses["vllm_guidance_validation"]["message"]
    for name, argv in {
        "host-gpu": [
            "nvidia-smi",
            "--query-gpu=index,name,utilization.gpu,memory.used",
            "--format=csv,noheader",
        ],
        "container-gpu": [
            "docker",
            "exec",
            CONTAINER,
            "nvidia-smi",
            "--query-gpu=index,name",
            "--format=csv,noheader",
        ],
    }.items():
        save(root / f"{name}.json", command(argv))
    with httpx.Client(base_url="http://127.0.0.1:7860", timeout=5, trust_env=False) as client:
        response = client.get("/health")
        save(root / "health.json", {"status_code": response.status_code, "body": response.text})
    code_paths = [
        "v1/structured_output/backend_xgrammar.py",
        "v1/structured_output/backend_guidance.py",
        "sampling_params.py",
        "entrypoints/serve/utils/error_response.py",
        "entrypoints/openai/chat_completion/serving.py",
    ]
    for relative in code_paths:
        path = "/usr/local/lib/python3.12/dist-packages/vllm/" + relative
        copied = command(
            [
                "docker",
                "exec",
                CONTAINER,
                "python3",
                "-c",
                "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text(),end='')",
                path,
            ]
        )
        save(root / "server-source" / (relative.replace("/", "--") + ".json"), copied)
    validate(root)
    result = {
        "status": "BOUNDED_DIAGNOSIS_WITH_UNSETTLED_USAGE_RETAINED",
        "source_request_sha256": sha(request),
        "http_status": read(http)["status_code"],
        "confirmed_gap": "Full public schema uses uniqueItems; current vLLM backend validation "
        "rejects it in both XGrammar and Guidance paths. Small compatibility examples omitted it.",
        "not_proven": "Original empty-message HTTP500 location and actual usage. CPU rejection "
        "does not establish a request-level GPU/token receipt for the historical HTTP call.",
        "gpu_observation": "See separate host/container NVML and health receipts. "
        "HTTP health is not proof of generation readiness. No shared service changes.",
        "model_requests": 0,
        "judge_requests": 0,
        "usage_settlement": "NOT_AUTHORIZED_BY_THIS_DIAGNOSTIC_RESERVATION_REMAINS_PENDING",
    }
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    diagnose(args.source, args.root)
