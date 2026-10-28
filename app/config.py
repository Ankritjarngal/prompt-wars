from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    admin_username: str
    admin_password: str
    data_dir: Path
    max_upload_bytes: int
    host: str
    port: int
    skip_models: bool

    @property
    def db_path(self) -> Path:
        return self.data_dir / "prompt_wars.db"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        data_dir = Path(os.environ.get("DATA_DIR", "data"))
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir
        mb = int(os.environ.get("MAX_UPLOAD_MB", "8"))
        return cls(
            admin_username=os.environ.get("ADMIN_USERNAME", "admin"),
            admin_password=os.environ.get("ADMIN_PASSWORD", "promptwars"),
            data_dir=data_dir,
            max_upload_bytes=mb * 1024 * 1024,
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8000")),
            skip_models=os.environ.get("SKIP_MODELS", "").strip() == "1",
        )
