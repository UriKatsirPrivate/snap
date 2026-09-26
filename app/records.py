from abc import ABC, abstractmethod
from pathlib import Path

from app.config import Config
from app.schemas import DecisionRecord


class DecisionRecorder(ABC):
    @abstractmethod
    def record(self, record: DecisionRecord) -> None: ...

    @abstractmethod
    def recent(self, limit: int) -> list[DecisionRecord]: ...

    @abstractmethod
    def clear(self, task_ids: list[str] | None = None) -> None: ...


class LocalJsonlRecorder(DecisionRecorder):
    """Appends decision records as JSON lines. Used for local dev/tests."""

    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, record: DecisionRecord) -> None:
        with self._path.open("a") as f:
            f.write(record.model_dump_json() + "\n")

    def recent(self, limit: int) -> list[DecisionRecord]:
        if not self._path.exists():
            return []
        lines = self._path.read_text().splitlines()
        records = [DecisionRecord.model_validate_json(line) for line in lines if line]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]

    def clear(self, task_ids: list[str] | None = None) -> None:
        if not self._path.exists():
            return
        if task_ids is None:
            self._path.unlink()
            return
        exclude = set(task_ids)
        lines = self._path.read_text().splitlines()
        kept = [
            line
            for line in lines
            if line and DecisionRecord.model_validate_json(line).task_id not in exclude
        ]
        self._path.write_text("".join(line + "\n" for line in kept))


class CloudSqlRecorder(DecisionRecorder):
    """Stores decision records in a Cloud SQL Postgres table, via IAM auth."""

    _SCHEMA = [
        ("id", "TEXT PRIMARY KEY"),
        ("kind", "TEXT NOT NULL"),
        ("task_id", "TEXT NOT NULL"),
        ("offered", "TEXT[] NOT NULL"),
        ("selector_choice", "TEXT"),
        ("abstained", "BOOLEAN NOT NULL"),
        ("validated", "BOOLEAN NOT NULL"),
        ("fallback_used", "BOOLEAN NOT NULL"),
        ("final_choice", "TEXT"),
        ("selector_latency_ms", "DOUBLE PRECISION"),
        ("selector_cost_usd", "DOUBLE PRECISION"),
        ("created_at", "TIMESTAMPTZ NOT NULL"),
    ]
    _COLUMN_NAMES = [name for name, _ in _SCHEMA]
    _TABLE = "decisions"

    def __init__(self, config: Config):
        from google.cloud.sql.connector import Connector

        self._connector = Connector()
        self._instance = config.cloudsql_instance
        self._db = config.cloudsql_database
        self._user = config.cloudsql_user
        self._ensure_table()

    def _connect(self):
        return self._connector.connect(
            self._instance,
            "pg8000",
            user=self._user,
            db=self._db,
            enable_iam_auth=True,
        )

    def _ensure_table(self) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            columns_sql = ",\n    ".join(f"{name} {ddl}" for name, ddl in self._SCHEMA)
            cur.execute(f"CREATE TABLE IF NOT EXISTS {self._TABLE} (\n    {columns_sql}\n)")
            # Reconcile drift for tables created before a field existed in
            # _SCHEMA (the exact class of bug that silently broke this
            # service's BigQuery-backed predecessor). New columns are added
            # nullable regardless of the declared DDL -- retroactively adding
            # NOT NULL would fail against any existing rows.
            for name, ddl in self._SCHEMA:
                base_type = ddl.replace("PRIMARY KEY", "").replace("NOT NULL", "").strip()
                cur.execute(f"ALTER TABLE {self._TABLE} ADD COLUMN IF NOT EXISTS {name} {base_type}")
            conn.commit()
        finally:
            conn.close()

    def record(self, record: DecisionRecord) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            placeholders = ", ".join(["%s"] * len(self._COLUMN_NAMES))
            data = record.model_dump()
            values = [data[name] for name in self._COLUMN_NAMES]
            cur.execute(
                f"INSERT INTO {self._TABLE} ({', '.join(self._COLUMN_NAMES)}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
        finally:
            conn.close()

    def recent(self, limit: int) -> list[DecisionRecord]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT {', '.join(self._COLUMN_NAMES)} FROM {self._TABLE} "
                "ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
            return [DecisionRecord.model_validate(dict(zip(self._COLUMN_NAMES, row))) for row in rows]
        finally:
            conn.close()

    def clear(self, task_ids: list[str] | None = None) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            if task_ids is None:
                cur.execute(f"DELETE FROM {self._TABLE}")
            else:
                cur.execute(f"DELETE FROM {self._TABLE} WHERE task_id = ANY(%s)", (task_ids,))
            conn.commit()
        finally:
            conn.close()


def get_recorder(config: Config) -> DecisionRecorder:
    if config.records_backend == "cloudsql":
        return CloudSqlRecorder(config)
    return LocalJsonlRecorder(config.local_records_path)
