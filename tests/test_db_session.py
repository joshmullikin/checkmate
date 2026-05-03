"""Tests for db/session.py"""
import importlib
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
import sqlmodel

import db.session as db_session


def test_create_db_and_tables_calls_metadata_create_all(monkeypatch):
    called = {"engine": None}

    def fake_create_all(engine):
        called["engine"] = engine

    monkeypatch.setattr(db_session.SQLModel.metadata, "create_all", fake_create_all)
    db_session.create_db_and_tables()
    assert called["engine"] is db_session.engine


def test_get_session_commits_on_success(monkeypatch):
    fake_session = MagicMock()

    def fake_session_ctor(_engine):
        return fake_session

    monkeypatch.setattr(db_session, "Session", fake_session_ctor)

    with db_session.get_session() as got:
        assert got is fake_session

    fake_session.commit.assert_called_once()
    fake_session.rollback.assert_not_called()
    fake_session.close.assert_called_once()


def test_get_session_rolls_back_on_error(monkeypatch):
    fake_session = MagicMock()

    def fake_session_ctor(_engine):
        return fake_session

    monkeypatch.setattr(db_session, "Session", fake_session_ctor)

    with pytest.raises(RuntimeError):
        with db_session.get_session():
            raise RuntimeError("boom")

    fake_session.rollback.assert_called_once()
    fake_session.close.assert_called_once()


def test_get_session_dep_yields_session(monkeypatch):
    class _CM:
        def __init__(self):
            self.session = object()

        def __enter__(self):
            return self.session

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(db_session, "Session", lambda _engine: _CM())

    gen = db_session.get_session_dep()
    session = next(gen)
    assert session is not None
    with pytest.raises(StopIteration):
        next(gen)


def test_sqlite_connect_listener_sets_pragmas():
    executed = []
    closed = {"value": False}

    class _Cursor:
        def execute(self, sql):
            executed.append(sql)

        def close(self):
            closed["value"] = True

    class _Conn:
        def cursor(self):
            return _Cursor()

    db_session._set_sqlite_pragma(_Conn(), None)

    assert "PRAGMA journal_mode=WAL" in executed
    assert "PRAGMA busy_timeout=5000" in executed
    assert closed["value"] is True


def test_engine_uses_postgres_pooling_options_when_database_url_is_postgres(monkeypatch):
    captured = {}
    original_create_engine = sqlmodel.create_engine

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/checkmate")
    monkeypatch.setattr(sqlmodel, "create_engine", fake_create_engine)

    reloaded = importlib.reload(db_session)
    assert captured["url"].startswith("postgresql://")
    assert captured["kwargs"]["pool_size"] == 5
    assert captured["kwargs"]["max_overflow"] == 10
    assert captured["kwargs"]["pool_timeout"] == 30
    assert captured["kwargs"]["pool_recycle"] == 1800
    assert captured["kwargs"]["pool_pre_ping"] is True

    # Restore default sqlite branch for any later tests.
    monkeypatch.setattr(sqlmodel, "create_engine", original_create_engine)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./qa_testing.db")
    importlib.reload(reloaded)
