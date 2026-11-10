from __future__ import annotations

import pytest

from app.lifespan import validate_rate_limit_storage


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_local_environments_may_use_memory_rate_limits(
    environment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDIS_URL", "memory://")
    validate_rate_limit_storage(environment)


@pytest.mark.parametrize("redis_url", ["", "memory://", "http://redis:6379", "redis://"])
def test_staging_rejects_non_shared_rate_limit_storage(
    redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDIS_URL", redis_url)
    with pytest.raises(RuntimeError, match="shared redis"):
        validate_rate_limit_storage("staging")


@pytest.mark.parametrize("redis_url", ["redis://redis:6379/0", "rediss://redis:6380/0"])
def test_staging_accepts_networked_redis(redis_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", redis_url)
    validate_rate_limit_storage("staging")
