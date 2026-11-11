from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-only-secret-with-at-least-thirty-two-bytes")
os.environ.setdefault("DATABASE_URL", "sqlite:///./.pytest-neura.db")
os.environ.setdefault("ALLOW_SQLITE", "true")
os.environ.setdefault("COOKIE_SECURE", "false")
