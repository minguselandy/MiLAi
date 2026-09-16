from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config


@dataclass(frozen=True, slots=True)
class MigrationLayout:
    config_path: Path
    script_path: Path
    prepend_sys_path: Path
    packaged: bool


def migration_layout() -> MigrationLayout:
    package_root = Path(__file__).resolve().parents[1]
    packaged_config = package_root / "_alembic.ini"
    packaged_scripts = package_root / "_migrations"
    if packaged_config.is_file() and packaged_scripts.is_dir():
        return MigrationLayout(
            config_path=packaged_config,
            script_path=packaged_scripts,
            prepend_sys_path=package_root.parent,
            packaged=True,
        )

    runtime_root = Path(__file__).resolve().parents[3]
    source_config = runtime_root / "alembic.ini"
    source_scripts = runtime_root / "migrations"
    if not source_config.is_file() or not source_scripts.is_dir():
        raise RuntimeError("MiLAi Runtime migration resources are unavailable")
    return MigrationLayout(
        config_path=source_config,
        script_path=source_scripts,
        prepend_sys_path=runtime_root / "src",
        packaged=False,
    )


def alembic_config() -> Config:
    layout = migration_layout()
    config = Config(str(layout.config_path))
    config.set_main_option("script_location", str(layout.script_path))
    config.set_main_option("prepend_sys_path", str(layout.prepend_sys_path))
    return config
