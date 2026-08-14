"""
app/database/sqlalchemy_session.py
────────────────────────────────────────────────────────────────────────────────
Engine y sesión SQLAlchemy para el módulo Content & Outliers.

Variable de entorno:
  CONTENT_DATABASE_URL  (default: sqlite en app/storage_vault/content_outliers.db)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

_DEFAULT_SQLITE = "sqlite:///./app/storage_vault/content_outliers.db"
DATABASE_URL = os.getenv("CONTENT_DATABASE_URL", _DEFAULT_SQLITE).strip() or _DEFAULT_SQLITE

_connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
    if DATABASE_URL.startswith("sqlite:///./"):
        rel_path = DATABASE_URL.replace("sqlite:///./", "")
        Path(rel_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_content_db() -> None:
    """Crea tablas del módulo content si no existen."""
    from app.content import models  # noqa: F401 — registra metadata

    Base.metadata.create_all(bind=engine)
    logger.info("[ContentDB] Tablas inicializadas — %s", DATABASE_URL.split("@")[-1][:80])
