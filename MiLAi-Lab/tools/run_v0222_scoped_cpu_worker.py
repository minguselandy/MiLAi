"""Fresh CPU replay bootstrap: deny sockets before loading the worker stack."""

from __future__ import annotations


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0222_scoped_cpu_worker import main as worker_main
    # isort: split
    from v0222_scoped_cpu_observation import run_observed

    return run_observed(worker_main, "worker")


if __name__ == "__main__":
    raise SystemExit(main())
