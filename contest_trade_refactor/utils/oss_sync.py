"""Helpers for syncing local market-data directories with Aliyun OSS."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def load_project_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file without overriding existing env vars."""
    env_path = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, val = text.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = val.strip().strip('"').strip("'")
    except OSError as exc:
        raise RuntimeError(f"Failed to load env file {env_path}: {exc}") from exc


def normalize_oss_endpoint(endpoint: str) -> str:
    text = str(endpoint or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    return f"https://{text}"


@dataclass(frozen=True)
class OssConfig:
    access_key_id: str
    access_key_secret: str
    bucket_name: str
    endpoint: str
    prefix: str = "market-bars"

    @property
    def normalized_prefix(self) -> str:
        text = self.prefix.strip().strip("/")
        return text


def oss_config_from_env() -> OssConfig:
    cfg = OssConfig(
        access_key_id=_env("OSS_ACCESS_KEY_ID"),
        access_key_secret=_env("OSS_ACCESS_KEY_SECRET"),
        bucket_name=_env("OSS_BUCKET"),
        endpoint=normalize_oss_endpoint(_env("OSS_ENDPOINT")),
        prefix=_env("OSS_PREFIX", "market-bars"),
    )
    missing = [
        name
        for name, value in (
            ("OSS_ACCESS_KEY_ID", cfg.access_key_id),
            ("OSS_ACCESS_KEY_SECRET", cfg.access_key_secret),
            ("OSS_BUCKET", cfg.bucket_name),
            ("OSS_ENDPOINT", cfg.endpoint),
        )
        if not value
    ]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing OSS config: {joined}")
    return cfg


def iter_local_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.endswith(".tmp"):
            continue
        if any(part.startswith(".") and part not in {".", ".."} for part in path.relative_to(root).parts):
            continue
        yield path


def object_key_for_path(root: Path, path: Path, prefix: str) -> str:
    relative = path.relative_to(root).as_posix().lstrip("/")
    clean_prefix = str(prefix or "").strip().strip("/")
    return f"{clean_prefix}/{relative}" if clean_prefix else relative

