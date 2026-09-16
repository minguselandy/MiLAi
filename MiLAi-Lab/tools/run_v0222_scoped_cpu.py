"""Fresh CPU stage process: deny sockets before importing the parent runner."""


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0222_scoped_cpu_runner import main as runner_main
    # isort: split
    from v0222_scoped_cpu_observation import run_observed

    return run_observed(runner_main, "stage")


if __name__ == "__main__":
    raise SystemExit(main())
