"""Bootstrap offline market_manager caches from AkShare / Tushare."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache" / "market_manager"
STOCK_BASIC_CACHE = CACHE_DIR / "stock_basic_cache.json"
NAMECHANGE_CACHE = CACHE_DIR / "namechange_data.json"


def ensure_market_manager_caches(verbose: bool = True) -> dict[str, bool]:
    """Build missing market_manager cache files. Returns status per cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    status = {
        "stock_basic_cache": STOCK_BASIC_CACHE.exists(),
        "namechange_data": NAMECHANGE_CACHE.exists(),
    }
    if not status["stock_basic_cache"]:
        status["stock_basic_cache"] = _build_stock_basic_cache(verbose=verbose)
    if not status["namechange_data"]:
        status["namechange_data"] = _build_namechange_cache(verbose=verbose)
    return status


def _normalize_ts_code(raw_code: str) -> str:
    code = str(raw_code or "").strip().upper()
    if not code:
        return code
    if "." in code:
        return code
    if code.startswith(("8", "4")):
        return f"{code}.BJ"
    if code.startswith("6"):
        return f"{code}.SH"
    return f"{code}.SZ"


def _fetch_stock_basic_frame(verbose: bool = True) -> pd.DataFrame:
    from utils.akshare_utils import akshare_cached

    for func_name in ("stock_info_a_code_name", "stock_zh_a_spot_em"):
        try:
            df = akshare_cached.run(func_name=func_name, func_kwargs={}, verbose=False)
            if df is None or df.empty:
                continue
            rename = {}
            for src, dst in (("代码", "symbol"), ("code", "symbol"), ("名称", "name")):
                if src in df.columns:
                    rename[src] = dst
            df = df.rename(columns=rename)
            if "symbol" not in df.columns or "name" not in df.columns:
                continue
            out = pd.DataFrame({
                "ts_code": df["symbol"].map(_normalize_ts_code),
                "symbol": df["symbol"].astype(str).str.zfill(6),
                "name": df["name"].astype(str),
                "list_status": "L",
            })
            out = out.dropna(subset=["ts_code", "name"]).drop_duplicates(subset=["ts_code"])
            if not out.empty:
                if verbose:
                    print(f"Fetched {len(out)} stocks via akshare {func_name}")
                return out
        except Exception as exc:
            if verbose:
                print(f"akshare {func_name} failed: {exc}")

    from utils.tushare_utils import pro_cached

    if verbose:
        print("Falling back to Tushare stock_basic...")
    stock_df = pro_cached.run(
        func_name="stock_basic",
        func_kwargs={
            "exchange": "SSE,SZSE,BJSE",
            "fields": "ts_code,symbol,name,area,industry,list_date,list_status,fullname",
        },
    )
    if stock_df is None or stock_df.empty:
        return pd.DataFrame()
    return stock_df[stock_df["list_status"] == "L"].copy()


def _build_stock_basic_cache(verbose: bool = True) -> bool:
    if verbose:
        print(f"Building {STOCK_BASIC_CACHE}...")
    listing = _fetch_stock_basic_frame(verbose=verbose)
    if listing.empty:
        if verbose:
            print("stock basic fetch returned empty")
        return False

    payload = listing.to_dict(orient="records")
    STOCK_BASIC_CACHE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if verbose:
        print(f"Saved {len(payload)} listed stocks to {STOCK_BASIC_CACHE}")
    return True


def _build_namechange_cache(verbose: bool = True) -> bool:
    """Build name->ts_code map from stock basic (current names + split variants)."""
    if not STOCK_BASIC_CACHE.exists() and not _build_stock_basic_cache(verbose=verbose):
        return False

    if verbose:
        print(f"Building {NAMECHANGE_CACHE} from stock basic names...")
    rows = json.loads(STOCK_BASIC_CACHE.read_text(encoding="utf-8"))
    name2code: dict[str, str] = {}
    for row in rows:
        code = str(row.get("ts_code") or "").strip()
        name = str(row.get("name") or "").strip()
        if not code or not name:
            continue
        name2code[name] = code
        if "-" in name:
            name2code[name.split("-", 1)[0]] = code
        fullname = str(row.get("fullname") or "").strip()
        if fullname and fullname != name:
            name2code[fullname] = code

    NAMECHANGE_CACHE.write_text(
        json.dumps(name2code, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if verbose:
        print(f"Saved {len(name2code)} name mappings to {NAMECHANGE_CACHE}")
    return True


if __name__ == "__main__":
    ensure_market_manager_caches(verbose=True)
