#!/usr/bin/env python3
"""Sync local market-bar cache to Aliyun OSS.

Local cache stays the source of truth for strategy reads/writes.
This script only mirrors files to OSS when you choose to run it.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.market_bar_store import DEFAULT_STORE_DIR
from utils.oss_sync import iter_local_files, load_project_dotenv, object_key_for_path, oss_config_from_env

load_project_dotenv(PROJECT_ROOT / ".env")


def _resolve_local_root(cli_root: str) -> Path:
    if cli_root:
        return Path(cli_root).expanduser().resolve()
    import os

    root_text = (os.environ.get("CN_MARKET_BAR_STORE_DIR") or "").strip()
    if root_text:
        configured = Path(root_text).expanduser().resolve()
        if configured.exists():
            return configured
        print(f"CN_MARKET_BAR_STORE_DIR does not exist ({configured}); falling back to {DEFAULT_STORE_DIR}")
    return DEFAULT_STORE_DIR.resolve()


def _oss_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", default="", help="Local market data root. Defaults to CN_MARKET_BAR_STORE_DIR.")
    parser.add_argument("--prefix", default="", help="OSS object prefix. Defaults to OSS_PREFIX or market-bars.")
    parser.add_argument("--dry-run", action="store_true", help="Show pending uploads without writing OSS.")
    parser.add_argument("--force", action="store_true", help="Upload every file even if remote looks current.")
    args = parser.parse_args()

    root = _resolve_local_root(args.local_root)
    if not root.exists():
        raise SystemExit(f"Local root does not exist: {root}")

    cfg = oss_config_from_env()
    prefix = args.prefix.strip() or cfg.normalized_prefix

    try:
        import oss2
    except ImportError as exc:
        raise SystemExit("Missing dependency `oss2`. Install it with `pip install -r requirements.txt`.") from exc

    auth = oss2.Auth(cfg.access_key_id, cfg.access_key_secret)
    bucket = oss2.Bucket(auth, cfg.endpoint, cfg.bucket_name)

    uploaded = 0
    skipped = 0
    total_bytes = 0

    for path in iter_local_files(root):
        object_key = object_key_for_path(root, path, prefix)
        local_stat = path.stat()
        should_upload = bool(args.force)

        if not should_upload:
            try:
                meta = bucket.head_object(object_key)
            except oss2.exceptions.NoSuchKey:
                should_upload = True
            except oss2.exceptions.ServerError as exc:
                raise SystemExit(f"OSS server error while checking {object_key}: {exc}") from exc
            else:
                remote_size = int(getattr(meta, "content_length", -1))
                remote_mtime = _oss_datetime(getattr(meta, "last_modified", None))
                local_mtime = datetime.fromtimestamp(local_stat.st_mtime, tz=timezone.utc)
                should_upload = remote_size != local_stat.st_size or (
                    remote_mtime is not None and local_mtime > remote_mtime
                )

        action = "UPLOAD" if should_upload else "SKIP"
        print(f"{action} {path} -> oss://{cfg.bucket_name}/{object_key}")
        if not should_upload:
            skipped += 1
            continue
        if args.dry_run:
            continue
        bucket.put_object_from_file(object_key, str(path))
        uploaded += 1
        total_bytes += local_stat.st_size

    mode = "dry-run" if args.dry_run else "done"
    print(
        f"sync {mode}: root={root} uploaded={uploaded} skipped={skipped} bytes={total_bytes} "
        f"bucket={cfg.bucket_name} prefix={prefix or '/'}"
    )


if __name__ == "__main__":
    main()
