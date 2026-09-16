"""Fresh CPU preparation process: deny sockets before importing replay code."""


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from prepare_v0222_scoped_cpu import main as prepare_main
    from v0222_scoped_cpu_observation import run_observed

    return run_observed(prepare_main, "prepare")


if __name__ == "__main__":
    raise SystemExit(main())
