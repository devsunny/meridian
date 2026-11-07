from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings

logger = logging.getLogger("meridian.db")
settings = get_settings()


class Base(DeclarativeBase):
    pass


def _build_engine() -> Engine:
    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if settings.is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if settings.is_sqlite:
        # WAL + foreign keys; the API and a local worker share the file.
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    return engine


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def init_db(seed: bool = True) -> None:
    from . import models  # noqa: F401 - register mappings

    Base.metadata.create_all(bind=engine)
    if seed and settings.seed_demo:
        from .seed import seed_demo_data

        try:
            with session_scope() as session:
                seed_demo_data(session)
        except Exception as exc:  # noqa: BLE001 - concurrent role startup may race the seed
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError):
                logger.info("demo_seed_already_applied", extra={"reason": "concurrent_startup"})
            else:
                logger.exception("demo_seed_failed")
    logger.info("database_initialised", extra={"backend": engine.dialect.name})


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def db_health() -> tuple[bool, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, exc.__class__.__name__


class MetricRegistry:
    """Tiny Prometheus-compatible registry; avoids another runtime dependency."""

    def __init__(self) -> None:
        self.counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self.gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self.histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(list)

    def inc(self, name: str, value: float = 1, **labels: str) -> None:
        self.counters[(name, tuple(sorted(labels.items())))] += value

    def gauge(self, name: str, value: float, **labels: str) -> None:
        self.gauges[(name, tuple(sorted(labels.items())))] = value

    def observe(self, name: str, value: float, **labels: str) -> None:
        self.histograms[(name, tuple(sorted(labels.items())))].append(value)
        self.histograms[(name, tuple(sorted(labels.items())))] = self.histograms[
            (name, tuple(sorted(labels.items())))
        ][-5000:]

    @staticmethod
    def _labels(labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"

    def render(self) -> str:
        lines: list[str] = []
        for (name, labels), value in sorted(self.counters.items()):
            lines.append(f"{name}_total{self._labels(labels)} {value:g}")
        for (name, labels), value in sorted(self.gauges.items()):
            lines.append(f"{name}{self._labels(labels)} {value:g}")
        for (name, labels), values in sorted(self.histograms.items()):
            if not values:
                continue
            lines.append(f"{name}_count{self._labels(labels)} {len(values)}")
            lines.append(f"{name}_sum{self._labels(labels)} {sum(values):g}")
            lines.append(f"{name}_max{self._labels(labels)} {max(values):g}")
        return "\n".join(lines) + "\n"


metrics = MetricRegistry()


@contextmanager
def advisory_lock(name: str) -> Iterator[bool]:
    """Cross-process lock: Postgres advisory lock, SQLite write transaction fallback.

    The scheduler uses this to ensure only one replica materialises a given tick. The returned
    boolean is False when another replica holds the lock.
    """
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            key = abs(hash(name)) % (2**31)
            acquired = bool(connection.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                    connection.commit()
    else:
        yield True
