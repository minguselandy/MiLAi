"""Explicit Host-only selection of the public SDK; the Lab package stays independent."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import zipfile
from pathlib import Path


def source_runtime(config: dict):
    selection = config.get("host_acquisition", {"implementation": "LAB"})
    kind = selection["implementation"]
    if kind == "LAB":
        return importlib.import_module("milai_lab.methods.host_acquisition"), {
            "implementation": "LAB"}
    if kind != "CLIENT_SDK":
        raise ValueError("UNKNOWN_HOST_ACQUISITION_IMPLEMENTATION")
    wheel = Path(selection["wheel"])
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != selection["wheel_sha256"]:
        raise ValueError("SDK_WHEEL_CHANGED")
    version = importlib.metadata.version("milai-client")
    if version != selection["version"]:
        raise ValueError("SDK_VERSION_CHANGED")
    api = importlib.import_module("milai_client.host_acquisition")
    package = Path(api.__file__).resolve().parent
    checked = 0
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("milai_client/") and name.endswith(".py"):
                if (package.parent / name).read_bytes() != archive.read(name):
                    raise ValueError("INSTALLED_SDK_DIFFERS_FROM_WHEEL")
                checked += 1
    return api, {"implementation": kind, "version": version,
        "wheel_sha256": digest, "matching_python_files": checked,
        "module": api.__name__, "module_sha256": hashlib.sha256(
            Path(api.__file__).read_bytes()).hexdigest(), "event_loop": "ONE_PER_COLD_HOST"}
