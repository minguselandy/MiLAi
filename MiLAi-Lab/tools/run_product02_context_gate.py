#!/usr/bin/env python3
"""Compatibility CLI wrapper for the Product-02 context gate runner."""

from __future__ import annotations

from milai_lab.runners import product02_context_gate as _implementation

for _name, _value in vars(_implementation).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

del _name, _value


if __name__ == "__main__":
    raise SystemExit(_implementation.main())
