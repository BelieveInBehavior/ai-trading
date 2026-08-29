#!/usr/bin/env python3
"""Event-driven backtest for main_trend (主升浪).

Severe timing discipline:
  T日 收盘后       : 系统只能使用截至 T 日收盘的数据发现候选
  T+1 开盘        : 模拟真实买入（V1 无盘口历史，默认用 T+1 open 作为代理）
  持仓期每日收盘   : 监控 HOLD / REDUCE / SELL
  SELL 信号次日开盘: 模拟真实卖出。
  V2.0 工程化变更：
    1) MA10 减半 / MA20 清仓退出逻辑（策略引擎）
    2) 单日最大新开 5 只，总持仓最大 20 只
    3) MA20/Risk Stop 触发时按当日 VWAP 保守成交（代理），不用收盘完美平仓

Usage:
  # V1: 无盘口历史, T+1 open 买入, 状态机退出
  .venv/bin/python scripts/main_trend_event_backtest.py \\
      --start 2026-06-01 --end 2026-08-18 \\
      --symbols-limit 100 \\
      --output-dir agents_workspace_main_trend_event

  # 使用已有的真实 t1_execution.json (含手工/盘口执行的 BUY)
  .venv/bin/python scripts/main_trend_event_backtest.py \\
      --start 2026-06-01 --end 2026-08-18 \\
      --use-t1-files --workspace-dir agents_workspace_main_trend

  # 只测候选 Alpha: T+1 open 买入, 持有 N 个交易日后下一交易日 open 卖出
  .venv/bin/python scripts/main_trend_event_backtest.py \\
      --start 2026-06-01 --end 2026-08-18 \\
      --exit-mode hold --hold-days 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
from strategies.main_trend.schemas import Holding
from utils.cn_price_provider import get_stock_zh_a_hist
from utils.market_manager import GLOBAL_MARKET_MANAGER

# bar cache: (open, high, low, close, vwap_approx)
_ohlc_mem: Dict[Tuple[str, str], Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]] = {}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def compact(s: str) -> str:
    return str(s or "").strip().replace("-", "").replace("/", "")


def trade_dates_between(start: str, end: str) -> List[str]:
    raw = [str(d).replace("-", "").replace("/", "") for d in GLOBAL_MARKET_MANAGER.get_trade_date(market_name="CN-Stock")]
    return [d for d in sorted(raw) if compact(start) <= d <= compact(end)]


def num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        v = float(value)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply_factor_overrides(
    cfg: MainTrendConfig,
    *,
    enable_market_sentiment: bool = True,
    enable_hot_money: bool = True,
    ablation_tag: str = "",
) -> MainTrendConfig:
    """Research-only config overrides for ablation.

    Disabled factors are set to neutral and their score weights are zeroed so
    the comparison reflects actual removal rather than a constant 50 offset.
    """
    cfg.sentiment = dict(cfg.sentiment or {})
    cfg.hot_money = dict(cfg.hot_money or {})
    cfg.scoring = dict(cfg.scoring or {})

    cfg.sentiment["enabled"] = bool(enable_market_sentiment)
    cfg.hot_money["enabled"] = bool(enable_hot_money)

    if not enable_market_sentiment:
        cfg.scoring["market_sentiment_weight"] = 0.0
    if not enable_hot_money:
        cfg.scoring["hot_money_weight"] = 0.0

    if ablation_tag:
        cfg.backtest = dict(cfg.backtest or {})
        cfg.backtest["ablation_tag"] = str(ablation_tag)
    return cfg


def asof_env(date: str) -> None:
    os.environ["CONTEST_TRADE_ASOF_DATE"] = date


def day_ohlc(symbol: str, date: str, back_days: int = 5) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Return (open, high, low, close, vwap_approx) through shared bar storage."""
    key = (symbol, date)
    if key in _ohlc_mem:
        return _ohlc_mem[key]
    empty = (None, None, None, None, None)
    try:
        df = get_stock_zh_a_hist(symbol=symbol, start_date=date, end_date=date, adjust="qfq", verbose=False)
        if df is None or df.empty:
            _ohlc_mem[key] = empty
            return _ohlc_mem[key]
        date_col = "日期" if "日期" in df.columns else "date"
        rows = df[df[date_col].astype(str).str.replace("-", "", regex=False) == date]
        if rows.empty:
            _ohlc_mem[key] = empty
        else:
            r = rows.iloc[-1]
            open_px = num(r.get("开盘")) or num(r.get("open"))
            high_px = num(r.get("最高")) or num(r.get("high"))
            low_px = num(r.get("最低")) or num(r.get("low"))
            close_px = num(r.get("收盘")) or num(r.get("close"))
            amount = num(r.get("成交额")) or num(r.get("amount"))
            volume = num(r.get("成交量")) or num(r.get("volume"))
            vwap = None
            if amount is not None and volume and volume > 0:
                vwap_val = amount / (volume * 100.0)
                if vwap_val and vwap_val == vwap_val and vwap_val > 0:
                    vwap = round(vwap_val, 4)
            _ohlc_mem[key] = (open_px, high_px, low_px, close_px, vwap)
    except Exception:
        _ohlc_mem[key] = empty
    return _ohlc_mem[key]


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    code: str
    name: str
    signal_date: str
    entry_date: str
    entry_price: float
    score: float = 0.0
    grade: str = "A"
    sector: str = ""
    theme: str = ""
    status: str = "OPEN"              # OPEN | SELL_READY | CLOSED
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    exit_class: str = ""
    exit_level: str = ""
    hold_days: int = 0
    return_pct: Optional[float] = None
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma5_dev_pct: Optional[float] = None
    reference_price: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "signal_date": self.signal_date,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "score": self.score,
            "grade": self.grade,
            "sector": self.sector,
            "theme": self.theme,
            "status": self.status,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "exit_class": self.exit_class,
            "exit_level": self.exit_level,
            "hold_days": self.hold_days,
            "return_pct": self.return_pct,
            "ma5": self.ma5,
            "ma10": self.ma10,
            "ma5_dev_pct": self.ma5_dev_pct,
            "reference_price": self.reference_price,
        }


@dataclass
class Position:
    trade: Trade
    holding: Optional[Holding] = None
    # monitoring state carried between days
    prev_close: Optional[float] = None
    prev_ma20: Optional[float] = None
    highest_close: Optional[float] = None
    holding_days: int = 0
    initial_stop: Optional[float] = None


# ---------------------------------------------------------------------------
# event-driven backtest
# ---------------------------------------------------------------------------

class MainTrendEventBacktest:
    def __init__(
        self,
        engine: MainTrendEngine,
        dates: List[str],
        output_root: Path,
        symbols_limit: int = 0,
        concurrency: int = 4,
        use_t1_files: bool = False,
        workspace_dir: Optional[Path] = None,
        allow_future_leak: bool = False,
        exit_mode: str = "state_machine",
        hold_days: int = 5,
        max_holding_days: int = 5,
        max_opens_per_day: int = 5,
        max_open_positions: int = 20,
        risk_fill_mode: str = "vwap",
        gap_slippage_bps: float = 20.0,
    ):
        self.max_opens_per_day = max_opens_per_day
        self.max_open_positions = max_open_positions
        self.risk_fill_mode = risk_fill_mode
        self.gap_slippage_bps = gap_slippage_bps
        self.engine = engine
        self.dates = dates
        self.output_root = output_root
        self.symbols_limit = symbols_limit
        self.concurrency = concurrency
        self.use_t1_files = use_t1_files
        self.workspace_dir = Path(workspace_dir).expanduser().resolve() if workspace_dir else None
        self.allow_future_leak = allow_future_leak
        self.exit_mode = exit_mode
        self.hold_days = hold_days
        self.max_holding_days = max_holding_days

        self.trades: List[Trade] = []
        self.positions: List[Position] = []
        self.candidates_by_date: Dict[str, List[Dict[str, Any]]] = {}
        self.raw_by_date: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.reduce_log: List[Dict[str, Any]] = []

    # ---------- helpers ----------
    def _log(self, event: str, date: str, **kw: Any) -> None:
        self.events.append({"date": date, "event": event, **kw})

    def _open_trade(self, code: str) -> Optional[Trade]:
        for t in self.trades:
            if t.code == code and t.status != "CLOSED":
                return t
        return None

    def _open_position(self, code: str) -> Optional[Position]:
        for p in self.positions:
            if p.trade.code == code and p.trade.status != "CLOSED":
                return p
        return None

    # ---------- engine day ----------
    async def _run_tday(self, date: str) -> Dict[str, Any]:
        trigger = f"{date[:4]}-{date[4:6]}-{date[6:8]} 18:00:00"
        return await self.engine.run_day(
            trigger_time=trigger,
            max_symbols=self.symbols_limit,
            output_dir=str(self.output_root / date / "engine"),
            phase="tday",
        )

    def _parse_candidates(self, date: str, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        discovery = raw.get("discovery") or {}
        cands = discovery.get("eligible") or []
        pool_map = {}
        for c in (raw.get("tday_pool") or {}).get("pool") or []:
            pool_map[str(c.get("symbol_code"))] = c
        out = []
        for c in cands:
            code = str(c.get("symbol_code") or "")
            pool = pool_map.get(code) or {}
            row = dict(c)
            row["pre_score"] = num(pool.get("pre_score")) or num(row.get("pre_score"))
            row["reference_price"] = num(pool.get("reference_price")) or num(row.get("reference_price"))
            row["suggested_position_pct"] = num(pool.get("suggested_position_pct")) or num(row.get("suggested_position_pct"))
            row["theme"] = pool.get("theme") or row.get("theme") or ""
            row["initial_stop"] = num(pool.get("initial_stop"))
            tf = row.get("technical_factor") or c.get("technical_factor") or {}
            if tf:
                ma5 = num(tf.get("ma5"))
                ma10 = num(tf.get("ma10"))
                if ma5 is not None:
                    row["ma5"] = ma5
                if ma10 is not None:
                    row["ma10"] = ma10
                ref = num(tf.get("close")) or row.get("reference_price")
                if ma5 and ref:
                    row["ma5_dev_pct"] = round((ref / ma5 - 1.0) * 100.0, 4)
            out.append(row)
        return out

    # ---------- execution ----------
    def _candidate_execution_info(self, cand: Dict[str, Any], signal_date: str, exec_date: str) -> Optional[Dict[str, Any]]:
        code = str(cand.get("symbol_code") or "")
        if self.use_t1_files and self.workspace_dir:
            t1_path = self.workspace_dir / signal_date / "t1_execution.json"
            if t1_path.exists():
                try:
                    payload = json.loads(t1_path.read_text(encoding="utf-8"))
                except Exception:
                    payload = None
                if payload:
                    row = next((r for r in (payload.get("rows") or []) if str(r.get("symbol_code")) == code), None)
                    if row and (str(row.get("action") or "").upper() == "BUY"):
                        entry = num(row.get("entry_price")) or num(cand.get("reference_price"))
                        if entry:
                            return {
                                "entry": entry,
                                "grade": str(row.get("execution_grade") or "A"),
                                "score": num(row.get("final_score")) or num(row.get("pre_score")) or num(cand.get("pre_score")) or 0.0,
                                "reason": "t1_execution_file",
                            }
        open_px = day_ohlc(code, exec_date)[0]
        if open_px is None:
            return None
        return {
            "code": code,
            "entry": open_px,
            "grade": "V1_OPEN",
            "score": num(cand.get("pre_score")) or num(cand.get("entry_score")) or 0.0,
            "reason": "t1_open_proxy",
        }

    def _execute_tplus_one(self, signal_date: str, exec_date: str) -> None:
        buys_today = 0
        open_positions = len(self.positions)
        # 硬仓位上限下先买评分最高的候选，避免“前几个/顺序靠前”挤占名额。
        ordered = sorted(
            (self.candidates_by_date.get(signal_date) or []),
            key=lambda c: num(c.get("pre_score")) or num(c.get("entry_score")) or 0.0,
            reverse=True,
        )
        for cand in ordered:
            code = str(cand.get("symbol_code") or "")
            if self._open_trade(code):
                continue
            # V2.0 硬仓位上限：单日最大新开 5 只；总持仓容量 20 只。
            # forward 模式专门做“候选前向收益”而不做组合模拟，因此不限制买入数量。
            if self.exit_mode != "forward":
                if buys_today >= self.max_opens_per_day:
                    self._log("BUY_REJECT_LIMIT", exec_date, code=code, reason=f"max_opens_per_day={self.max_opens_per_day}")
                    continue
                if open_positions + buys_today >= self.max_open_positions:
                    self._log("BUY_REJECT_LIMIT", exec_date, code=code, reason=f"max_open_positions={self.max_open_positions}")
                    continue
            info = self._candidate_execution_info(cand, signal_date, exec_date)
            if not info:
                continue
            trade = Trade(
                code=code,
                name=str(cand.get("symbol_name") or ""),
                signal_date=signal_date,
                entry_date=exec_date,
                entry_price=float(info["entry"]),
                score=float(info.get("score", 0.0) or 0.0),
                grade=str(info.get("grade") or "A"),
                sector=str(cand.get("sector_name") or ""),
                theme=str(cand.get("theme") or ""),
                ma5=num(cand.get("ma5")),
                ma10=num(cand.get("ma10")),
                ma5_dev_pct=num(cand.get("ma5_dev_pct")),
                reference_price=num(cand.get("reference_price")),
            )
            self.trades.append(trade)
            initial_stop = num(cand.get("initial_stop"))
            self.positions.append(Position(trade=trade, initial_stop=initial_stop))
            buys_today += 1
            self._log("BUY", exec_date, code=code, name=trade.name, entry_price=info["entry"], signal_date=signal_date, grade=trade.grade, reason=info.get("reason", ""))

    # ---------- exits ----------
    def _close_trade(self, trade: Trade, sell_date: str, price: float) -> None:
        trade.exit_date = sell_date
        trade.exit_price = price
        trade.status = "CLOSED"
        trade.return_pct = (price / trade.entry_price - 1.0) * 100.0
        if trade.entry_date in self.dates and sell_date in self.dates:
            trade.hold_days = max(0, self.dates.index(sell_date) - self.dates.index(trade.entry_date))
        self.positions = [p for p in self.positions if p.trade is not trade]

    def _execute_pending_sells(self, date: str) -> None:
        ready = [p for p in self.positions if p.trade.status == "SELL_READY"]
        for p in ready:
            bar = day_ohlc(p.trade.code, date)
            open_px = bar[0]
            if open_px is None:
                continue
            # V2.0 陷阱 2：Risk Stop / MA20 清仓不许用收盘价完美平仓。
            # 默认按当日 VWAP（成交额/成交量代理）成交，做最保守近似；低于开盘价时按
            # 开盘价加滑点（gap_slippage_bps）兜底，避免使用“当日最低点”这种事后完美价位。
            exit_px = open_px
            exit_mode_used = "open"
            # 只对风险性退出做 VWAP 模拟，避免把普通超期/持有卖出也强行打坏。
            exit_class = str(p.trade.exit_class or "").upper()
            risk_sell = any(k in exit_class for k in ("SELL", "STOP")) or (p.trade.exit_reason or "").find("无条件清仓") >= 0
            if risk_sell and self.risk_fill_mode == "vwap":
                vwap = bar[4]
                if vwap and vwap > 0:
                    exit_px = vwap
                    exit_mode_used = "vwap"
                else:
                    # 无 VWAP：用开盘价 + 滑点作为保守代理
                    exit_px = open_px * (1.0 - self.gap_slippage_bps / 10000.0)
                    exit_mode_used = f"open_slippage_{self.gap_slippage_bps:.0f}bps"
            elif risk_sell and self.risk_fill_mode == "close":
                close_px = bar[3]
                if close_px and close_px > 0:
                    exit_px = close_px
                    exit_mode_used = "close"
            self._close_trade(p.trade, date, exit_px)
            self._log("SELL_EXEC", date, code=p.trade.code, exit_price=exit_px, signal_date=p.trade.signal_date, reason=p.trade.exit_reason, fill_mode=exit_mode_used)

    def _build_holding(self, pos: Position, date: str, holding_days: int) -> Holding:
        return Holding(
            symbol_code=pos.trade.code,
            symbol_name=pos.trade.name,
            entry_date=pos.trade.entry_date,
            entry_price=pos.trade.entry_price,
            quantity=1,
            holding_days=holding_days,
            highest_price=max(num(pos.highest_close) or pos.trade.entry_price, pos.trade.entry_price),
            current_price=num(pos.prev_close) or pos.trade.entry_price,
            buy_score=pos.trade.score,
            signal_tier=pos.trade.grade,
            trade_plan={},
            stop_loss_price=pos.initial_stop,
            atr_trailing_stop=None,
            prev_close=pos.prev_close,
            prev_ma20=pos.prev_ma20,
            highest_close=num(pos.highest_close) or pos.trade.entry_price,
            event_catalyst=None,
            realtime_quote={},
            order_flow_score=50.0,
        )

    def _monitor_state_machine(self, date: str) -> None:
        if not self.positions:
            return
        holdings = []
        pos_map = {}
        for pos in self.positions:
            h = self._build_holding(pos, date, pos.holding_days)
            pos.holding = h
            pos_map[h.symbol_code] = pos
            holdings.append(h)
        try:
            refreshed = self.engine.refresh_holding_factors(holdings, trade_date=date)
            exits = self.engine.evaluate_exits(refreshed, trade_date=date)
        except Exception:
            refreshed, exits = [], []
        refreshed_map = {h.symbol_code: h for h in refreshed}
        exit_map = {d.symbol_code: d for d in exits}
        for code, pos in pos_map.items():
            pos.holding_days += 1
            cur = refreshed_map.get(code)
            if cur is not None:
                pos.holding = cur
                close = num(cur.current_price) or num(cur.ma20)
                if close is not None:
                    pos.prev_close = close
                    if pos.highest_close is None or close > pos.highest_close:
                        pos.highest_close = close
                if cur.ma20 is not None:
                    pos.prev_ma20 = cur.ma20
                if cur.holding_days is not None:
                    pos.holding_days = cur.holding_days
            dec = exit_map.get(code)
            if dec is None:
                continue
            action = str(dec.action or "").lower()
            is_sell = action in ("sell", "exit") or str(dec.exit_class or "").upper().startswith("SELL")
            is_reduce = action == "reduce" or str(dec.exit_class or "").upper() == "REDUCE"
            if is_sell:
                pos.trade.status = "SELL_READY"
                pos.trade.exit_class = dec.exit_class or ""
                pos.trade.exit_level = dec.exit_level or ""
                pos.trade.exit_reason = dec.reason or dec.exit_class or ""
                self._log("SELL_SIGNAL", date, code=code, name=pos.trade.name, exit_class=dec.exit_class, reason=pos.trade.exit_reason)
            elif is_reduce:
                self.reduce_log.append({"date": date, "code": code, "name": pos.trade.name, "reason": dec.reason or "", "exit_class": dec.exit_class or ""})
                self._log("REDUCE_SIGNAL", date, code=code, reason=dec.reason or "")
            else:
                pos.trade.exit_reason = ""

    def _monitor_hold_mode(self, date: str) -> None:
        for pos in self.positions:
            if pos.trade.entry_date in self.dates and date in self.dates:
                days = self.dates.index(date) - self.dates.index(pos.trade.entry_date)
                pos.holding_days = days
                if days >= self.hold_days and pos.trade.status != "SELL_READY":
                    pos.trade.status = "SELL_READY"
                    pos.trade.exit_class = "HOLD_N_DAYS"
                    pos.trade.exit_reason = f"hold_{self.hold_days}_days"
                    self._log("SELL_SIGNAL", date, code=pos.trade.code, reason=pos.trade.exit_reason)

    # ---------- output ----------
    def _save_day_files(self, date: str) -> None:
        daydir = self.output_root / date
        write_json(daydir / "result_summary.json", {
            "date": date,
            "candidates_count": len(self.candidates_by_date.get(date, [])),
            "open_positions": len(self.positions),
            "closed_today": [t.to_dict() for t in self.trades if t.exit_date == date],
            "events": [e for e in self.events if e.get("date") == date],
            "reduce_today": [r for r in self.reduce_log if r.get("date") == date],
        })
        recs = [t.to_dict() for t in self.trades if t.entry_date == date or t.exit_date == date or t.status != "CLOSED"]
        write_json(daydir / "trade_records.json", {"date": date, "count": len(recs), "records": recs})
        write_json(daydir / "portfolio.json", {
            "date": date,
            "open": [{"code": p.trade.code, "name": p.trade.name, "entry_date": p.trade.entry_date, "entry_price": p.trade.entry_price, "holding_days": p.holding_days, "status": p.trade.status} for p in self.positions],
        })

    def summary(self) -> Dict[str, Any]:
        closed = [t for t in self.trades if t.status == "CLOSED"]
        rets = [t.return_pct for t in closed if t.return_pct is not None]
        exit_ct = Counter((t.exit_class or "OPEN") for t in self.trades if t.status == "CLOSED")
        limit_rejects = sum(1 for e in self.events if (e.get("event") or "") == "BUY_REJECT_LIMIT")
        fill_modes = Counter(str(e.get("fill_mode") or "") for e in self.events if (e.get("event") or "") == "SELL_EXEC")
        exit_class_stats = {}
        for cls in sorted(exit_ct):
            cls_rets = [t.return_pct for t in closed if t.return_pct is not None and (t.exit_class or "OPEN") == cls]
            exit_class_stats[cls] = {
                "count": len(cls_rets),
                "avg_return_pct": round(sum(cls_rets) / len(cls_rets), 3) if cls_rets else None,
                "win_rate_pct": round(sum(1 for r in cls_rets if r > 0) / len(cls_rets) * 100, 2) if cls_rets else None,
            }
        return {
            "ma_mode": str((self.engine.config.technical or {}).get("ma_mode") or "ema"),
            "ablation_tag": str((self.engine.config.backtest or {}).get("ablation_tag") or ""),
            "market_sentiment_enabled": bool((self.engine.config.sentiment or {}).get("enabled", True)),
            "hot_money_enabled": bool((self.engine.config.hot_money or {}).get("enabled", True)),
            "score_weights": {
                "trend": float((self.engine.config.scoring or {}).get("trend_weight", 0.40) or 0.40),
                "sector": float((self.engine.config.scoring or {}).get("sector_weight", 0.25) or 0.25),
                "market_sentiment": float((self.engine.config.scoring or {}).get("market_sentiment_weight", 0.15) or 0.0),
                "hot_money": float((self.engine.config.scoring or {}).get("hot_money_weight", 0.10) or 0.0),
                "catalyst": float((self.engine.config.scoring or {}).get("catalyst_weight", 0.10) or 0.10),
                "pre": float((self.engine.config.scoring or {}).get("pre_weight", 0.60) or 0.60),
                "execution": float((self.engine.config.scoring or {}).get("execution_weight", 0.40) or 0.40),
            },
            "start": self.dates[0] if self.dates else None,
            "end": self.dates[-1] if self.dates else None,
            "trading_days": len(self.dates),
            "candidates_total": sum(len(v) for v in self.candidates_by_date.values()),
            "candidate_unique_symbols": len({str(c.get("symbol_code")) for cs in self.candidates_by_date.values() for c in cs}),
            "trades_total": len(self.trades),
            "closed_total": len(closed),
            "open_total": len([t for t in self.trades if t.status != "CLOSED"]),
            "avg_return_pct": round(sum(rets) / len(rets), 2) if rets else None,
            "win_rate_pct": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 2) if rets else None,
            "total_return_pct": round(sum(rets), 2) if rets else None,
            "profit_factor": (lambda wins, losses: round(sum(wins) / abs(sum(losses)), 3) if losses and sum(losses) != 0 else None)([r for r in rets if r > 0], [r for r in rets if r < 0]),
            "exit_class_distribution": dict(exit_ct),
            "exit_class_stats": exit_class_stats,
            "sell_confirm_avg_return_pct": exit_class_stats.get("SELL_CONFIRM", {}).get("avg_return_pct"),
            "reduce_signals": len(self.reduce_log),
            "v2_max_opens_per_day": self.max_opens_per_day,
            "v2_max_open_positions": self.max_open_positions,
            "v2_buy_limit_rejects": limit_rejects,
            "v2_sell_fill_modes": dict(fill_modes),
        }

    def _compute_forward_returns(self) -> dict:
        """纯前向收益：T+1 open 买入 -> +1/+3/+5/+10 个交易日 open 卖出。"""
        date_index = {d: i for i, d in enumerate(self.dates)}
        records = []
        date_index = {d: i for i, d in enumerate(self.dates)}
        seen_score = 0
        for t in self.trades:
            if t.score < 70:
                continue
            seen_score += 1
            entry_idx = date_index.get(t.entry_date)
            if entry_idx is None:
                continue
            base = {"code": t.code, "name": t.name, "signal_date": t.signal_date,
                    "entry_date": t.entry_date, "entry_price": t.entry_price,
                    "score": t.score, "grade": t.grade,
                    "ma5": t.ma5, "ma10": t.ma10, "ma5_dev_pct": t.ma5_dev_pct,
                    "reference_price": t.reference_price}
            any_rec = False
            for h in (1, 3, 5, 10):
                exit_idx = entry_idx + h
                if exit_idx >= len(self.dates):
                    continue
                exit_date = self.dates[exit_idx]
                bar = day_ohlc(t.code, exit_date, back_days=3)
                open_px = bar[0]
                if not open_px or open_px <= 0:
                    continue
                ret = (open_px / t.entry_price - 1.0) * 100.0
                records.append({**base, "horizon": h, "exit_date": exit_date,
                                "exit_price": open_px, "return_pct": round(ret, 4)})
                any_rec = True
            if not any_rec:
                pass
        stats = {}
        for h in (1, 3, 5, 10):
            r = [x["return_pct"] for x in records if x["horizon"] == h]
            wins = [x for x in r if x > 0]
            losses = [x for x in r if x < 0]
            stats[str(h)] = {
                "count": len(r),
                "avg_return_pct": round(sum(r) / len(r), 4) if r else None,
                "win_rate_pct": round(len(wins) / len(r) * 100, 2) if r else None,
                "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses and sum(losses) != 0 else None,
                "signals_ge70": seen_score,
            }
        # EMA5 过热分桶（同样只统计 >=70）
        def bucket(dev):
            if dev is None:
                return "unknown"
            if dev < 0:
                return "below"
            if dev < 3:
                return "0-3%"
            if dev < 6:
                return "3-6%"
            if dev < 10:
                return "6-10%"
            return "10%+"
        bucket_stats = {}
        for h in (1, 3, 5, 10):
            for dev in ("below", "0-3%", "3-6%", "6-10%", "10%+", "unknown"):
                r = [x["return_pct"] for x in records if x["horizon"] == h and bucket(x["ma5_dev_pct"]) == dev]
                if not r:
                    continue
                wins = [x for x in r if x > 0]
                losses = [x for x in r if x < 0]
                bucket_stats.setdefault(str(h), {})[dev] = {
                    "count": len(r),
                    "avg_return_pct": round(sum(r) / len(r), 4),
                    "win_rate_pct": round(len(wins) / len(r) * 100, 2),
                    "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses and sum(losses) != 0 else None,
                }
        payload = {
            "ma_mode": str((self.engine.config.technical or {}).get("ma_mode") or "ema"),
            "trades_total": len(self.trades),
            "signals_ge70": seen_score,
            "stats": stats,
            "ema5_buckets": bucket_stats,
            "records": records,
        }
        write_json(self.output_root / "forward_returns.json", payload)
        return payload

    def write_summary(self) -> None:
        write_json(self.output_root / "summary.json", self.summary())
        write_json(self.output_root / "all_trades.json", {"count": len(self.trades), "trades": [t.to_dict() for t in self.trades]})
        write_json(self.output_root / "events.json", {"count": len(self.events), "events": self.events})

    # ---------- main loop ----------
    async def run(self) -> Dict[str, Any]:
        for i, date in enumerate(self.dates):
            asof_env(date)
            # 1) execute pending sells at today's open
            self._execute_pending_sells(date)
            # 2) execute T+1 buys for candidates detected in previous T day
            if i > 0:
                signal_pre = self.dates[i - 1]
                self._execute_tplus_one(signal_pre, date)
            # 3) run T日 discovery (uses only data up to today's close)
            raw = await self._run_tday(date)
            cands = self._parse_candidates(date, raw)
            self.candidates_by_date[date] = cands
            self.raw_by_date[date] = raw
            write_json(self.output_root / date / "candidates.json", {
                "date": date,
                "count": len(cands),
                "candidates": [{
                    "code": c.get("symbol_code"),
                    "name": c.get("symbol_name"),
                    "pre_score": c.get("pre_score"),
                    "reference_price": c.get("reference_price"),
                    "trend_state": c.get("trend_state"),
                    "trend_quality": c.get("trend_quality"),
                    "market_regime": c.get("market_regime"),
                    "sector_name": c.get("sector_name"),
                    "theme": c.get("theme"),
                } for c in cands],
            })
            # 4) monitor open positions with today's close
            if self.exit_mode == "state_machine":
                self._monitor_state_machine(date)
            elif self.exit_mode == "hold":
                self._monitor_hold_mode(date)
            # forward 模式：不监控退出，只保留持仓到最后统一计算前向收益
            # 5) save day files
            self._save_day_files(date)
            print(f"[event_bt] {date}: candidates={len(cands)} open={len(self.positions)} trades={len(self.trades)}", flush=True)
        summ = self.summary()
        if self.exit_mode == "forward":
            fwd = self._compute_forward_returns()
            summ["forward_returns"] = fwd.get('stats')
            summ['forward_returns_file'] = str(self.output_root / "forward_returns.json")
        self.write_summary()
        print(json.dumps(summ, ensure_ascii=False, indent=2))
        return summ


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--date", default="")
    parser.add_argument("--output-dir", default="agents_workspace_main_trend_event")
    parser.add_argument("--market-data-root", default="", help="共享市场数据根目录；默认 /Users/ruby/Desktop/real-market-data 或环境变量 MARKET_DATA_ROOT")
    parser.add_argument("--bar-store-dir", default="", help="共享日线行情存储目录；默认 <market-data-root>/bar_store")
    parser.add_argument("--financial-report-store-dir", default="", help="共享财报存储目录；默认 <market-data-root>/financial_reports")
    parser.add_argument("--disable-shared-data-store", action="store_true", help="禁用共享行情/财报写入，仅使用远程/临时缓存")
    parser.add_argument("--symbols-limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--allow-future-leak", action="store_true")
    parser.add_argument("--use-t1-files", action="store_true")
    parser.add_argument("--workspace-dir", default="")
    parser.add_argument("--exit-mode", default="state_machine", choices=["state_machine", "hold", "forward"])
    parser.add_argument("--hold-days", type=int, default=5)
    parser.add_argument("--max-holding-days", type=int, default=5, help="状态机模式下的最大持仓天数；main_trend 短冲刺默认 5 天")
    parser.add_argument("--max-opens-per-day", type=int, default=5)
    parser.add_argument("--max-open-positions", type=int, default=20)
    parser.add_argument("--risk-fill-mode", default="vwap", choices=["vwap", "open", "close"])
    parser.add_argument("--gap-slippage-bps", type=float, default=20.0)
    parser.add_argument("--ma-mode", default="ema", choices=["sma", "ema"], help="MA/EMA A/B: sma=等权滚动均线；ema=指数平滑均线(默认)")
    parser.add_argument("--disable-market-sentiment", action="store_true", help="Ablation: disable MarketSentimentState and zero its score weight")
    parser.add_argument("--disable-hot-money", action="store_true", help="Ablation: disable HotMoneyState and zero its score weight")
    parser.add_argument("--ablation-tag", default="", help="Optional label written into summary.json for research comparisons")
    parser.add_argument("--skip-sector-daily", action='store_true', help='跳过板块日线历史抓取（只保留板块名称/等级快照），避免网络超时长时间卡住')
    args = parser.parse_args()

    if args.market_data_root:
        os.environ["MARKET_DATA_ROOT"] = str(Path(args.market_data_root).expanduser())
    if args.bar_store_dir:
        os.environ["CN_MARKET_BAR_STORE_DIR"] = str(Path(args.bar_store_dir).expanduser())
    if args.financial_report_store_dir:
        os.environ["CN_FINANCIAL_REPORT_STORE_DIR"] = str(Path(args.financial_report_store_dir).expanduser())
    if args.disable_shared_data_store:
        os.environ["CN_MARKET_BAR_STORE"] = "0"
        os.environ["CN_FINANCIAL_REPORT_STORE"] = "0"

    if args.skip_sector_daily:
        try:
            import utils.sector_flow_provider as _sfp
            # 阻断慢速的逐板块日线拉取；build_sector_snapshot 内是局部 import，
            # 必须在 source 函数名和该 import 的源模块上同时 patch。
            _sfp.get_industry_daily_history_map = lambda *a, **k: {}
            _sfp.get_industry_daily_history = lambda *a, **k: __import__("pandas").DataFrame()
        except Exception as exc:
            print(f"[warn] skip-sector-daily patch failed: {exc}", file=sys.stderr)

    if args.date:
        start = end = compact(args.date)
    elif args.start:
        start = compact(args.start)
        end = compact(args.end or args.start)
    else:
        raise SystemExit("--date or --start required")

    dates = trade_dates_between(start, end)
    if not dates:
        raise SystemExit(f"No trading days between {start} and {end}")

    cfg = _apply_factor_overrides(
        MainTrendConfig.from_yaml(),
        enable_market_sentiment=not args.disable_market_sentiment,
        enable_hot_money=not args.disable_hot_money,
        ablation_tag=args.ablation_tag,
    )
    engine = MainTrendEngine(cfg)
    engine.config.execution["use_tencent_realtime"] = False
    engine.config.technical = dict(engine.config.technical or {})
    engine.config.technical["ma_mode"] = args.ma_mode

    bt = MainTrendEventBacktest(
        engine=engine,
        dates=dates,
        output_root=Path(args.output_dir).expanduser().resolve(),
        symbols_limit=args.symbols_limit,
        concurrency=args.concurrency,
        use_t1_files=args.use_t1_files,
        workspace_dir=Path(args.workspace_dir) if args.workspace_dir else None,
        allow_future_leak=args.allow_future_leak,
        exit_mode=args.exit_mode,
        hold_days=args.hold_days,
        max_holding_days=args.max_holding_days,
        max_opens_per_day=args.max_opens_per_day,
        max_open_positions=args.max_open_positions,
        risk_fill_mode=args.risk_fill_mode,
        gap_slippage_bps=args.gap_slippage_bps,
    )
    asyncio.run(bt.run())


if __name__ == "__main__":
    main()
