import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    gcp_project: str | None
    gcp_location: str
    gemini_model: str
    records_backend: str
    bq_dataset: str
    bq_table: str
    local_records_path: str


def load_config() -> Config:
    return Config(
        gcp_project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        gcp_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        records_backend=os.environ.get("RECORDS_BACKEND", "local"),
        bq_dataset=os.environ.get("BQ_DATASET", "snap"),
        bq_table=os.environ.get("BQ_TABLE", "decisions"),
        local_records_path=os.environ.get("LOCAL_RECORDS_PATH", "data/decisions.jsonl"),
    )
