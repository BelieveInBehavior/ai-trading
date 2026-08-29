from __future__ import annotations

import os
from pathlib import Path


LEGACY_CACHE_ROOT = Path(__file__).resolve().parent / "cache"
DEFAULT_MARKET_DATA_ROOT = Path("/Users/ruby/Desktop/real-market-data")


def market_data_root() -> Path:
    configured = (os.environ.get("MARKET_DATA_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_MARKET_DATA_ROOT


def market_bar_store_dir() -> Path:
    configured = (os.environ.get("CN_MARKET_BAR_STORE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return market_data_root() / "bar_store"


def financial_report_store_dir() -> Path:
    configured = (os.environ.get("CN_FINANCIAL_REPORT_STORE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return market_data_root() / "financial_reports"


def market_manager_dir() -> Path:
    configured = (os.environ.get("MARKET_MANAGER_CACHE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return market_data_root() / "market_manager"


def legacy_market_bar_store_dir() -> Path:
    return LEGACY_CACHE_ROOT / "market_bars"


def legacy_market_manager_dir() -> Path:
    return LEGACY_CACHE_ROOT / "market_manager"


def preferred_existing_dir(primary: Path, legacy: Path) -> Path:
    if primary.exists():
        return primary
    return legacy
