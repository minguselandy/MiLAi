"""Keep in-process CLI instance selection local to the invoking test."""

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_cli_instance_environment():
    # CLI entrypoints intentionally set this selector for their process. Tests
    # invoke several entrypoints in one process, so restore their caller's state.
    name = "MILA_V0224_INSTANCE"
    original = os.environ.get(name)
    try:
        yield
    finally:
        if original is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = original
