"""One bounded, read-only CUDA driver query after a stopped readiness check."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from v0220_evidence import read, save, seal, sha, validate

PROBE = r"""
import ctypes,json,os
from pathlib import Path
value={'model_requests':0,'creates_cuda_context':False,'device_nodes':{}}
for name in ('/dev/nvidiactl','/dev/nvidia0','/dev/nvidia1','/dev/nvidia-uvm'):
 p=Path(name)
 if p.exists():
  s=p.stat(); value['device_nodes'][name]={'mode':oct(s.st_mode),'major':os.major(s.st_rdev),
                                        'minor':os.minor(s.st_rdev)}
 else: value['device_nodes'][name]={'exists':False}
try:
 driver=ctypes.CDLL('libcuda.so.1'); code=driver.cuInit(0)
 value['cuInit_returncode']=code
 name=ctypes.c_char_p(); driver.cuGetErrorName(code,ctypes.byref(name))
 value['cuInit_error_name']=name.value.decode() if name.value else None
 if code==0:
  count=ctypes.c_int()
  value['cuDeviceGetCount_returncode']=driver.cuDeviceGetCount(ctypes.byref(count))
  value['device_count']=count.value
except Exception as exc: value['exception_type']=type(exc).__name__
print(json.dumps(value))
"""


def run(source: Path, root: Path) -> dict:
    validate(source)
    if read(source / "result.json")["status"] != "SERVICE_NOT_READY":
        raise ValueError("STOPPED_SERVICE_READINESS_REQUIRED")
    frozen = sha(source / "stop.json")
    seal(
        root,
        entries=[Path(__file__)],
        inputs=[source / "manifest.json", source / "result.json", source / "stop.json"],
        contract={
            "model_requests": 0,
            "seconds_bound": 20,
            "scope": "One cuInit/device enumeration query; no CUDA context or inference",
            "no_service_changes": True,
        },
    )
    completed = subprocess.run(  # noqa: S603 - fixed bounded read-only driver query
        ["/usr/bin/docker", "exec", "bcec1ef46198", "python3", "-c", PROBE],
        capture_output=True,
        text=True,
        timeout=20,
    )
    save(
        root / "process.json",
        {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        },
    )
    if completed.returncode:
        result = {"status": "DRIVER_QUERY_INCOMPLETE", "model_requests": 0}
    else:
        result = {
            "status": "READ_ONLY_DRIVER_QUERY_RECORDED",
            "observed": json.loads(completed.stdout),
            "model_requests": 0,
            "limit": "New diagnostic process only; does not prove whether an already "
            "running engine can execute a kernel or establish a service repair cause",
        }
    assert sha(source / "stop.json") == frozen
    validate(root)
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.root)
