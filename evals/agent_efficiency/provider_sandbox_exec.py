from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path

_MS_RDONLY = 1
_MS_REMOUNT = 32
_MS_BIND = 4096
_MS_REC = 16384
_PR_SET_NO_NEW_PRIVS = 38
_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_ADD_RULE = 445
_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1
_LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
_LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2


class _LandlockRulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _LandlockPathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _mount(source: Path | None, target: Path, flags: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    mount = libc.mount
    mount.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    mount.restype = ctypes.c_int
    source_value = None if source is None else os.fsencode(source)
    if mount(source_value, os.fsencode(target), None, flags, None) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def _hide(source: Path, target: Path) -> None:
    if not target.is_dir():
        return
    _mount(source, target, _MS_BIND | _MS_REC)
    _mount(None, target, _MS_BIND | _MS_REMOUNT | _MS_RDONLY | _MS_REC)


def _replace_file(source: Path, target: Path) -> None:
    if not source.is_file() or not target.is_file():
        raise OSError(f"sandbox file mount is unavailable: {target}")
    _mount(source, target, _MS_BIND)
    _mount(None, target, _MS_BIND | _MS_REMOUNT | _MS_RDONLY)


def _mount_private_tmp() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    mount = libc.mount
    mount.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    mount.restype = ctypes.c_int
    if mount(b"tmpfs", b"/tmp", b"tmpfs", 0, b"size=64m,mode=1777") != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), "/tmp")


def _landlock_call(number: int, *arguments: object) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    result = int(libc.syscall(number, *arguments))
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), "landlock")
    return result


def _restrict_file_reads_and_execution(
    *,
    runtime_fd: int,
    source_copy: Path,
    dependency_targets: list[Path],
) -> None:
    version = _landlock_call(
        _LANDLOCK_CREATE_RULESET,
        0,
        0,
        _LANDLOCK_CREATE_RULESET_VERSION,
    )
    if version < 1:
        raise OSError("Landlock ABI 1 or newer is required")
    handled = _LANDLOCK_ACCESS_FS_EXECUTE | _LANDLOCK_ACCESS_FS_READ_FILE
    ruleset_attr = _LandlockRulesetAttr(handled_access_fs=handled)
    ruleset_fd = _landlock_call(
        _LANDLOCK_CREATE_RULESET,
        ctypes.byref(ruleset_attr),
        ctypes.sizeof(ruleset_attr),
        0,
    )
    path_flag = getattr(os, "O_PATH", os.O_RDONLY) | os.O_CLOEXEC
    allowed: list[tuple[Path, int]] = [
        (Path(f"/proc/self/fd/{runtime_fd}"), handled),
        (source_copy, _LANDLOCK_ACCESS_FS_READ_FILE),
        (Path("/etc/hosts"), _LANDLOCK_ACCESS_FS_READ_FILE),
        (Path("/etc/resolv.conf"), _LANDLOCK_ACCESS_FS_READ_FILE),
        (Path("/dev/null"), _LANDLOCK_ACCESS_FS_READ_FILE),
        (Path("/dev/random"), _LANDLOCK_ACCESS_FS_READ_FILE),
        (Path("/dev/urandom"), _LANDLOCK_ACCESS_FS_READ_FILE),
    ]
    allowed.extend((path, handled) for path in dependency_targets)
    try:
        for path, access in allowed:
            descriptor = os.open(path, path_flag)
            try:
                path_attr = _LandlockPathBeneathAttr(
                    allowed_access=access,
                    parent_fd=descriptor,
                )
                _landlock_call(
                    _LANDLOCK_ADD_RULE,
                    ruleset_fd,
                    _LANDLOCK_RULE_PATH_BENEATH,
                    ctypes.byref(path_attr),
                    0,
                )
            finally:
                os.close(descriptor)
        _landlock_call(_LANDLOCK_RESTRICT_SELF, ruleset_fd, 0)
    finally:
        os.close(ruleset_fd)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enter the MiLAi provider adapter sandbox"
    )
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--gid", type=int, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--hidden-root", type=Path, action="append", default=[])
    parser.add_argument("--provider-host", required=True)
    parser.add_argument("--provider-ip", action="append", default=[])
    parser.add_argument("--runtime-fd", type=int, required=True)
    parser.add_argument("--source-fd", type=int, required=True)
    parser.add_argument("--start-gate-fd", type=int, required=True)
    parser.add_argument("--dependency", action="append", nargs=2, default=[])
    return parser


def main() -> None:
    args = _parser().parse_args()
    if os.geteuid() != 0:
        raise SystemExit(
            "provider sandbox launcher requires root before privilege drop"
        )
    if args.uid <= 0 or args.gid <= 0:
        raise SystemExit("provider sandbox uid/gid must be non-root")
    if not args.workspace_root.is_absolute():
        raise SystemExit("workspace root must be absolute")
    _mount_private_tmp()
    base = Path("/tmp/milai-provider")
    cwd = base / "cwd"
    home = base / "home"
    empty = base / "empty"
    dependencies = base / "dependencies"
    for path in (base, cwd, home, empty, dependencies):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    hosts = base / "hosts"
    resolv = base / "resolv.conf"
    host_lines = ["127.0.0.1 localhost", "::1 localhost"]
    host_lines.extend(f"{address} {args.provider_host}" for address in args.provider_ip)
    hosts.write_text("\n".join(host_lines) + "\n", encoding="ascii")
    resolv.write_text(
        "# DNS intentionally disabled by MiLAi provider sandbox\n", encoding="ascii"
    )
    hosts.chmod(0o444)
    resolv.chmod(0o444)
    for target in (args.workspace_root, *args.hidden_root):
        if not target.is_absolute():
            raise SystemExit("hidden roots must be absolute")
        _hide(empty, target)
    _replace_file(hosts, Path("/etc/hosts"))
    _replace_file(resolv, Path("/etc/resolv.conf"))
    source_copy = base / "adapter-source"
    with (
        Path(f"/proc/self/fd/{args.source_fd}").open("rb") as source_stream,
        source_copy.open("wb") as output,
    ):
        while block := source_stream.read(1024 * 1024):
            output.write(block)
    source_copy.chmod(0o444)
    dependency_fds: list[int] = []
    dependency_targets: list[Path] = []
    for index, (fd_text, target_text) in enumerate(args.dependency):
        if not fd_text.isdigit():
            raise SystemExit("dependency source must be a file descriptor")
        target = Path(target_text)
        if not target.is_absolute():
            raise SystemExit("dependency target must be absolute")
        pinned = dependencies / str(index)
        with (
            Path(f"/proc/self/fd/{fd_text}").open("rb") as source_stream,
            pinned.open("wb") as output,
        ):
            while block := source_stream.read(1024 * 1024):
                output.write(block)
        pinned.chmod(0o555)
        _replace_file(pinned, target)
        dependency_fds.append(int(fd_text))
        dependency_targets.append(target)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), "prctl(PR_SET_NO_NEW_PRIVS)")
    for path in (base, cwd, home):
        os.chown(path, args.uid, args.gid)
    _restrict_file_reads_and_execution(
        runtime_fd=args.runtime_fd,
        source_copy=source_copy,
        dependency_targets=dependency_targets,
    )
    os.setgroups([])
    os.setgid(args.gid)
    os.setuid(args.uid)
    os.environ.update(
        {
            "HOME": str(home),
            "TMPDIR": str(cwd),
            "XDG_CACHE_HOME": str(cwd / "cache"),
            "XDG_CONFIG_HOME": str(cwd / "config"),
        }
    )
    os.chdir(cwd)
    if os.read(args.start_gate_fd, 1) != b"1":
        raise SystemExit("provider sandbox start gate closed before authorization")
    os.close(args.start_gate_fd)
    runtime = f"/proc/self/fd/{args.runtime_fd}"
    for fd in (args.runtime_fd, args.source_fd, *dependency_fds):
        os.set_inheritable(fd, False)
    os.execve(runtime, [runtime, str(source_copy)], dict(os.environ))


if __name__ == "__main__":
    main()
