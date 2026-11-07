import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

# Le SDK Gladia lit GLADIA_API_KEY à l'import : charger le .env avant tout import de SDK.
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    hai_api_key: str | None
    gladia_api_key: str | None
    linkup_api_key: str | None
    h_agent: str
    h_max_concurrency: int
    traces_dir: Path


def get_settings() -> Settings:
    return Settings(
        hai_api_key=os.getenv("HAI_API_KEY") or None,
        gladia_api_key=os.getenv("GLADIA_API_KEY") or None,
        linkup_api_key=os.getenv("LINKUP_API_KEY") or None,
        h_agent=os.getenv("RUNAI_H_AGENT", "h/web-surfer-pro"),
        h_max_concurrency=int(os.getenv("RUNAI_H_MAX_CONCURRENCY", "3")),
        traces_dir=Path(os.getenv("RUNAI_TRACES_DIR", ROOT / "traces")),
    )
