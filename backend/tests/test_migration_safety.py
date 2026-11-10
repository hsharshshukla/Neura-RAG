from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

VERSIONS = Path(__file__).parents[1] / "app" / "alembic" / "versions"


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS / filename
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "filename",
    [
        "20250830_add_cancel_schedule_fields.py",
        "20250906_pro_trial_and_billing_event.py",
        "20250906b_safe_pro_trial_and_billing_event.py",
    ],
)
def test_version_capacity_guard_is_idempotent_widening(
    filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    migration = _load_migration(filename)
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration._ensure_alembic_version_capacity()

    assert statements == ["ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"]


def test_storage_cleanup_drops_only_known_tables_without_cascade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration("67eec25b6a9f_ensure_timestamp_default_index.py")
    dropped: list[tuple[str, dict[str, Any]]] = []

    class Inspector:
        def has_table(self, _table_name: str) -> bool:
            return True

    monkeypatch.setattr(migration.op, "get_bind", object)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: Inspector())
    monkeypatch.setattr(
        migration.op,
        "drop_table",
        lambda table_name, **kwargs: dropped.append((table_name, kwargs)),
    )

    migration.upgrade()

    assert dropped == [
        ("embedding_index", {}),
        ("upload_link", {}),
        ("blob", {}),
    ]


@pytest.mark.parametrize(
    ("vector_extension", "expected_tables"),
    [
        (False, ["upload_link", "blob"]),
        (True, ["embedding_index", "upload_link", "blob"]),
    ],
)
def test_storage_downgrade_uses_database_vector_capability(
    vector_extension: bool,
    expected_tables: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration("67eec25b6a9f_ensure_timestamp_default_index.py")
    created: list[str] = []

    monkeypatch.setattr(migration, "_database_has_vector_extension", lambda: vector_extension)
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda table_name, *_args, **_kwargs: created.append(table_name),
    )
    monkeypatch.setattr(migration.op, "create_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "execute", lambda *_args, **_kwargs: None)

    migration.downgrade()

    assert created == expected_tables
