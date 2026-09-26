import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    gcp_project: str | None
    gcp_location: str
    gemini_model: str
    records_backend: str
    cloudsql_instance: str | None
    cloudsql_database: str
    cloudsql_user: str | None
    local_records_path: str
    admin_api_key: str | None


def load_config() -> Config:
    return Config(
        gcp_project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        gcp_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        records_backend=os.environ.get("RECORDS_BACKEND", "local"),
        cloudsql_instance=os.environ.get("CLOUDSQL_INSTANCE"),
        cloudsql_database=os.environ.get("CLOUDSQL_DATABASE", "snap"),
        cloudsql_user=os.environ.get("CLOUDSQL_USER"),
        local_records_path=os.environ.get("LOCAL_RECORDS_PATH", "data/decisions.jsonl"),
        admin_api_key=os.environ.get("ADMIN_API_KEY"),
    )
