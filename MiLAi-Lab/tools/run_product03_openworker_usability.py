#!/usr/bin/env python3
"""Compatibility CLI wrapper for the Product-03 OpenWorker usability runner."""

from __future__ import annotations

from milai_lab.runners import product03_openworker_usability as _implementation

for _name, _value in vars(_implementation).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

del _name, _value


if __name__ == "__main__":
    _implementation.main()
