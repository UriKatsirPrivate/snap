import json
import os
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
    def clear(self) -> None: ...


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

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


class BigQueryRecorder(DecisionRecorder):
    """Streams decision records into BigQuery for replay/eval later."""

    _SCHEMA = [
        {"name": "id", "type": "STRING", "mode": "REQUIRED"},
        {"name": "kind", "type": "STRING", "mode": "REQUIRED"},
        {"name": "task_id", "type": "STRING", "mode": "REQUIRED"},
        {"name": "offered", "type": "STRING", "mode": "REPEATED"},
        {"name": "selector_choice", "type": "STRING", "mode": "NULLABLE"},
        {"name": "abstained", "type": "BOOLEAN", "mode": "REQUIRED"},
        {"name": "validated", "type": "BOOLEAN", "mode": "REQUIRED"},
        {"name": "fallback_used", "type": "BOOLEAN", "mode": "REQUIRED"},
        {"name": "final_choice", "type": "STRING", "mode": "NULLABLE"},
        {"name": "selector_latency_ms", "type": "FLOAT", "mode": "NULLABLE"},
        {"name": "created_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
    ]

    def __init__(self, config: Config):
        from google.cloud import bigquery

        self._client = bigquery.Client(project=config.gcp_project)
        self._table_id = f"{config.gcp_project}.{config.bq_dataset}.{config.bq_table}"
        self._ensure_table(config.bq_dataset)

    def _ensure_table(self, dataset: str) -> None:
        from google.cloud import bigquery
        from google.cloud.exceptions import NotFound

        dataset_ref = bigquery.DatasetReference(self._client.project, dataset)
        try:
            self._client.get_dataset(dataset_ref)
        except NotFound:
            self._client.create_dataset(bigquery.Dataset(dataset_ref))

        try:
            self._client.get_table(self._table_id)
        except NotFound:
            table = bigquery.Table(self._table_id, schema=self._SCHEMA)
            self._client.create_table(table)

    def record(self, record: DecisionRecord) -> None:
        row = json.loads(record.model_dump_json())
        errors = self._client.insert_rows_json(self._table_id, [row])
        if errors:
            raise RuntimeError(f"BigQuery insert failed: {errors}")

    def recent(self, limit: int) -> list[DecisionRecord]:
        query = f"SELECT * FROM `{self._table_id}` ORDER BY created_at DESC LIMIT {int(limit)}"
        rows = self._client.query(query).result()
        return [DecisionRecord.model_validate(dict(row)) for row in rows]

    def clear(self) -> None:
        raise NotImplementedError(
            "Clearing BigQuery decision history is a production-data-destructive "
            "operation and is intentionally not wired up; do it manually if needed."
        )


def get_recorder(config: Config) -> DecisionRecorder:
    if config.records_backend == "bigquery":
        return BigQueryRecorder(config)
    return LocalJsonlRecorder(config.local_records_path)
