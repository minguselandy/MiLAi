from __future__ import annotations

from alembic.script import ScriptDirectory

from milai.operations.migrations import alembic_config, migration_layout


def test_source_migration_layout_has_a_unique_head() -> None:
    layout = migration_layout()

    assert layout.config_path.is_file()
    assert layout.script_path.is_dir()
    assert ScriptDirectory.from_config(alembic_config()).get_current_head()
