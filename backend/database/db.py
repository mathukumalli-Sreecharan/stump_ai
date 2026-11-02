
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine,
    inspect,
    String,
    Text,
    Integer,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from backend.config import DATABASE_URL


# ==================================================
# DATABASE ENGINE
# ==================================================

engine = create_engine(
    DATABASE_URL,
    connect_args=(
        {"check_same_thread": False}
        if DATABASE_URL.startswith("sqlite")
        else {}
    ),
)


# ==================================================
# SESSION FACTORY
# ==================================================

SessionLocal = sessionmaker[Session](
    bind=engine,
    expire_on_commit=False,
)


# ==================================================
# BASE MODEL
# ==================================================

class Base(DeclarativeBase):
    pass


# ==================================================
# TASK RECORD
# ==================================================

class TaskRecord(Base):

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(
        String(80),
        primary_key=True,
    )

    task_version: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    record_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )


# ==================================================
# EVALUATION RECORD
# ==================================================

class EvaluationRecord(Base):

    __tablename__ = "evaluations"

    evaluation_id: Mapped[str] = mapped_column(
        String(80),
        primary_key=True,
    )

    task_id: Mapped[str] = mapped_column(
        String(80),
        index=True,
        nullable=False,
    )

    # Nullable for evaluations created before task-version tracking existed.
    task_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    model: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    # Stores the complete internal evaluation result.
    # Public API responses must use explicit serializers.
    result_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )


class JobRecord(Base):
    """Persistent status for local background generation pipelines."""

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
        onupdate=lambda: datetime.now(timezone.utc).isoformat(),
    )


# ==================================================
# INITIALIZE TABLES
# ==================================================

Base.metadata.create_all(engine)

# Additive SQLite migration: older evaluation records remain intact and get a
# NULL task_version until they are explicitly backfilled.
if engine.dialect.name == "sqlite":
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("evaluations")
    }
    if "task_version" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE evaluations ADD COLUMN task_version INTEGER"
            )
