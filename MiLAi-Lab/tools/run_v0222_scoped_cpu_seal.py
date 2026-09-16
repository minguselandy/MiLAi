"""Fresh CPU seal process: deny sockets before importing the offline sealer."""


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from seal_v0222_scoped_cpu import main as seal_main
    from v0222_scoped_cpu_observation import run_observed

    return run_observed(seal_main, "seal")


if __name__ == "__main__":
    raise SystemExit(main())
