#!/usr/bin/env python3
"""Upload/download main_trend result.json via Aliyun OSS.

Full-market result.json is too large for GitHub. Keep the files locally and
mirror them to the bucket; pull them back on another machine with download.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.oss_sync import load_project_dotenv, object_key_for_path, oss_config_from_env

load_project_dotenv(PROJECT_ROOT / ".env")

DEFAULT_LOCAL = PROJECT_ROOT / "agents_workspace_main_trend"
DEFAULT_PREFIX = "workspace-results/agents_workspace_main_trend"


def _workspace_prefix(cli_prefix: str) -> str:
    if cli_prefix.strip():
        return cli_prefix.strip().strip("/")
    return (os.environ.get("OSS_WORKSPACE_PREFIX") or DEFAULT_PREFIX).strip().strip("/")


def _local_results(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("*/result.json") if path.is_file())


def _bucket(cfg):
    try:
        import oss2
    except ImportError as exc:
        raise SystemExit("Missing dependency `oss2`. Install it with `pip install -r requirements.txt`.") from exc

    auth = oss2.Auth(cfg.access_key_id, cfg.access_key_secret)
    bucket = oss2.Bucket(auth, cfg.endpoint, cfg.bucket_name, connect_timeout=30)
    try:
        bucket.get_bucket_info()
    except oss2.exceptions.NoSuchBucket:
        print(f"create bucket {cfg.bucket_name} at {cfg.endpoint}", flush=True)
        bucket.create_bucket()
    return oss2, bucket


def upload(root: Path, prefix: str, *, dry_run: bool, force: bool) -> None:
    cfg = oss_config_from_env()
    oss2, bucket = _bucket(cfg)
    files = _local_results(root)
    if not files:
        raise SystemExit(f"No result.json under {root}")

    uploaded = 0
    skipped = 0
    for path in files:
        object_key = object_key_for_path(root, path, prefix)
        should_upload = force
        if not should_upload:
            try:
                meta = bucket.head_object(object_key)
            except oss2.exceptions.NoSuchKey:
                should_upload = True
            else:
                should_upload = int(getattr(meta, "content_length", -1)) != path.stat().st_size
        action = "UPLOAD" if should_upload else "SKIP"
        print(f"{action} {path} -> oss://{cfg.bucket_name}/{object_key} ({path.stat().st_size} bytes)", flush=True)
        if not should_upload:
            skipped += 1
            continue
        if dry_run:
            continue
        bucket.put_object_from_file(object_key, str(path))
        uploaded += 1
    mode = "dry-run" if dry_run else "done"
    print(f"upload {mode}: uploaded={uploaded} skipped={skipped} prefix={prefix}")


def download(root: Path, prefix: str, *, dry_run: bool, force: bool) -> None:
    cfg = oss_config_from_env()
    oss2, bucket = _bucket(cfg)
    listed = 0
    written = 0
    skipped = 0
    for obj in oss2.ObjectIterator(bucket, prefix=f"{prefix}/"):
        name = Path(obj.key).name
        if name != "result.json":
            continue
        relative = Path(obj.key[len(prefix) :].lstrip("/"))
        dest = root / relative
        listed += 1
        if dest.exists() and dest.stat().st_size == int(obj.size) and not force:
            print(f"SKIP {dest} <- oss://{cfg.bucket_name}/{obj.key}")
            skipped += 1
            continue
        print(f"DOWNLOAD {dest} <- oss://{cfg.bucket_name}/{obj.key} ({obj.size} bytes)")
        if dry_run:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        bucket.get_object_to_file(obj.key, str(dest))
        written += 1
    if listed == 0:
        raise SystemExit(f"No result.json objects under oss://{cfg.bucket_name}/{prefix}/")
    mode = "dry-run" if dry_run else "done"
    print(f"download {mode}: written={written} skipped={skipped} prefix={prefix}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["upload", "download"])
    parser.add_argument("--local-root", default=str(DEFAULT_LOCAL))
    parser.add_argument("--prefix", default="", help="OSS prefix. Defaults to OSS_WORKSPACE_PREFIX.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = Path(args.local_root).expanduser().resolve()
    prefix = _workspace_prefix(args.prefix)
    if args.action == "upload":
        upload(root, prefix, dry_run=args.dry_run, force=args.force)
    else:
        download(root, prefix, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
