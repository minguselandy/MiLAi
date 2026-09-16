"""Fresh CPU preflight process: deny sockets before importing the replay stack."""


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from preflight_v0222_scoped_cpu import main as preflight_main
    from v0222_scoped_cpu_observation import run_observed

    return run_observed(preflight_main, "preflight")


if __name__ == "__main__":
    raise SystemExit(main())
