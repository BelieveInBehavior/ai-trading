"""First Board Continue 首板后延续 - 独立策略引擎。

首板后延续（C类机会）：
  - 严格首板识别：前一交易日未涨停 && 今日涨停
  - first_board_quality_score：首板质量
  - T+1 继续性确认 Gate：只要求正常延续，不要求 weak_to_strong
  - first_board_continuation_score + entry_quality_score 双重门槛
  - T+1~T+3 管理
"""
from __future__ import annotations

import asyncio
import json

import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from data_source.technical_indicators_akshare import compute_stock_technical_factor_from_history
from strategies.strong_diverge.engine import (
    _bool,
    _clamp,
    _int,
    _is_limit_up_change,
    _num,
    _normalize_code,
)
from utils.akshare_utils import akshare_cached
from utils.cn_price_provider import get_index_daily, get_stock_zh_a_hist
from utils.date_utils import get_latest_completed_trading_date, get_trading_date_range
from utils.market_manager import GLOBAL_MARKET_MANAGER
from utils.factor_store import ZT_SEAL_STORE

from strategies.first_board_continue.schemas import (
    BuySignal,
    ExitDecision,
    FirstBoardCandidate,
    FirstBoardDiscovery,
    Holding,
    WatchlistItem,
)

try:
    _BASE_DIR = Path(__file__).resolve().parent
except Exception:
    _BASE_DIR = Path("strategies/first_board_continue")


@dataclass
class FirstBoardContinueConfig:
    id: str = "first_board_continue"
    discovery: Dict[str, Any] = field(default_factory=dict)
    first_board: Dict[str, Any] = field(default_factory=dict)
    confirmation: Dict[str, Any] = field(default_factory=dict)
    holding: Dict[str, Any] = field(default_factory=dict)
    market: Dict[str, Any] = field(default_factory=dict)
    backtest: Dict[str, Any] = field(default_factory=dict)
    benchmark_symbol: str = "sh000300"
    quantitative_concurrency: int = 4

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "FirstBoardContinueConfig":
        return cls(
            id=str(cfg.get("id") or "first_board_continue"),
            discovery=dict(cfg.get("discovery") or {}),
            first_board=dict(cfg.get("first_board") or {}),
            confirmation=dict(cfg.get("confirmation") or {}),
            holding=dict(cfg.get("holding") or {}),
            market=dict(cfg.get("market") or {}),
            backtest=dict(cfg.get("backtest") or {}),
            benchmark_symbol=str(cfg.get("benchmark_symbol") or cfg.get("benchmark") or "sh000300"),
            quantitative_concurrency=int(cfg.get("quantitative_screen_concurrency", 4) or 4),
        )

    @classmethod
    def from_yaml(cls) -> "FirstBoardContinueConfig":
        import yaml
        with open(_BASE_DIR / "strategy.yaml", "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)


class FirstBoardContinueEngine:
    def __init__(self, config: FirstBoardContinueConfig | None = None):
        self.config = config or FirstBoardContinueConfig.from_yaml()

    # ================= 主入口 =================
    async def run_day(
        self,
        trigger_time: str,
        watchlist: Optional[List[WatchlistItem]] = None,
        holdings: Optional[List[Holding]] = None,
        output_dir: Optional[str] = None,
        max_symbols: int = 0,
    ) -> Dict[str, Any]:
        trade_date = get_latest_completed_trading_date(trigger_time)
        discovery = await self.discover(trigger_time, max_symbols=max_symbols)
        merged = self.merge_watchlist(discovery, prev_watchlist=watchlist, trade_date=trade_date)
        self.detect_first_board(merged, trade_date)
        self.advance_first_board_state(merged, trade_date)
        buy_signals = self.build_buy_signals(merged, trade_date)
        exits = self.evaluate_exits(holdings or [])
        result = {
            "trade_date": trade_date,
            "trigger_time": trigger_time,
            "discovery": discovery.to_dict() if hasattr(discovery, "to_dict") else {},
            "watchlist": [w.to_dict() for w in merged],
            "buy_signals": [b.to_dict() for b in buy_signals],
            "exit_decisions": [e.to_dict() for e in exits],
        }
        if output_dir:
            self._write_result(result, output_dir)
        return result

    # ================= 发现层 =================
    async def discover(self, trigger_time: str, max_symbols: int = 0) -> FirstBoardDiscovery:
        trade_date = get_latest_completed_trading_date(trigger_time)
        start_date, end_date = get_trading_date_range(end_date=trade_date, count=260, include_end=True)
        universe = await asyncio.to_thread(self._load_universe, max_symbols)
        benchmark = await asyncio.to_thread(self._load_benchmark, self.config.benchmark_symbol, start_date, end_date)
        sem = asyncio.Semaphore(max(1, int(self.config.quantitative_concurrency) or 4))
        candidates: List[FirstBoardCandidate] = []
        errors: List[str] = []

        async def _score(row: Dict[str, Any]) -> None:
            async with sem:
                try:
                    hist = await asyncio.to_thread(
                        get_stock_zh_a_hist,
                        symbol=str(row.get("symbol_code") or "")[:6],
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq",
                        verbose=False,
                    )
                    factor = await asyncio.to_thread(
                        compute_stock_technical_factor_from_history,
                        hist_df=hist,
                        symbol_code=str(row.get("symbol_code") or ""),
                        symbol_name=str(row.get("symbol_name") or ""),
                        trade_date=trade_date,
                        relative_strength_benchmark=self.config.benchmark_symbol,
                        benchmark_frame=benchmark,
                    )
                    if not factor:
                        return
                    cand = self._assess_first_board(factor)
                    if cand:
                        candidates.append(cand)
                except Exception as exc:
                    errors.append(str(exc))

        await asyncio.gather(*[_score(row) for row in universe])
        candidates.sort(key=lambda c: c.first_board_quality_score, reverse=True)
        context = f"首板延续发现池：扫描 {len(universe)} 只，首板候选 {len(candidates)} 只。"
        return FirstBoardDiscovery(
            trade_date=trade_date,
            candidates=candidates[: self._discovery_topk(self.config.discovery or {})],
            universe_count=len(universe),
            context_string=context,
            market_temperature={},
        )

    def _discovery_topk(self, cfg: Dict[str, Any]) -> int:
        return int(cfg.get("top_k", 300) or 300)

    def _load_universe(self, max_symbols: int = 0) -> list:
        try:
            raw = akshare_cached.run("stock_zh_a_spot_em", {}, False)
        except Exception:
            raw = akshare_cached.run("stock_info_a_code_name", {}, False)
        if raw is None or raw.empty:
            return []
        code_col = next((c for c in ("代码", "code", "ts_code") if c in raw.columns), None)
        name_col = next((c for c in ("名称", "name") if c in raw.columns), None)
        amount_col = next((c for c in ("成交额", "amount") if c in raw.columns), None)
        if not code_col:
            return []
        rows = []
        for _, row in raw.iterrows():
            code = _normalize_code(row.get(code_col))
            if not code:
                continue
            name = str(row.get(name_col) if name_col else row.get(code_col)).strip()
            if not name or name.upper().find("ST") >= 0 or "退" in name:
                continue
            rec = {"symbol_code": code, "symbol_name": name, "amount": 0.0}
            if amount_col:
                try:
                    rec["amount"] = float(row.get(amount_col) or 0.0)
                except Exception:
                    pass
            rows.append(rec)
        if max_symbols and max_symbols > 0:
            rows.sort(key=lambda r: r.get("amount", 0.0), reverse=True)
            rows = rows[:max_symbols]
        return rows

    def _load_benchmark(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        try:
            raw = get_index_daily(symbol, start, end, False)
            from data_source.technical_indicators_akshare import _prepare_price_frame
            return _prepare_price_frame(raw, date_columns=("date",), close_columns=("close",))
        except Exception:
            return pd.DataFrame()

    def _assess_first_board(self, factor: Dict[str, Any]) -> Optional[FirstBoardCandidate]:
        """从单日 technical_factor 判断首板：前一天未涨停（用 factor 里的痕迹判断） + 今天涨停。"""
        code = _normalize_code(factor.get("symbol_code"))
        if not code:
            return None
        if not _bool(factor.get("data_quality_valid", True)) or str(factor.get("data_quality_status") or "ok") != "ok":
            return None
        change = _num(factor.get("change_pct"))
        if change is not None and not _is_limit_up_change(code, change):
            return None
        # 首板严格识别：连续涨停数 <=1；若 continuous_board 缺失，用当日涨停近似
        board_in_factor = _int(factor.get("continuous_board"), 0)
        if board_in_factor and board_in_factor > 1:
            return None
        quality = self._compute_first_board_quality(factor)
        cand = FirstBoardCandidate(
            symbol_code=code,
            symbol_name=str(factor.get("symbol_name") or ""),
            trade_date=str(factor.get("report_date") or ""),
            first_board_event=True,
            first_board_date=str(factor.get("report_date") or ""),
            first_board_close=_num(factor.get("close")),
            first_board_quality_score=quality["score"],
            first_board_quality_grade=quality["grade"],
            first_board_quality_reasons=quality["reasons"],
            factor=factor,
            technical_factor=factor,
        )
        sec = self._compute_sector_breadth_gate(factor)
        up = self._compute_upside_room_gate(factor)
        cand.sector_breadth_score = sec["score"]
        cand.sector_breadth_passed = sec["passed"]
        cand.sector_breadth_reason = sec["reason"]
        cand.upside_room_score = up["score"]
        cand.upside_room_passed = up["passed"]
        cand.upside_room_reason = up["reason"]
        cand.gates = {"sector_breadth": sec, "upside_room": up}
        return cand

    def _compute_first_board_quality(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.config.first_board or {}
        score = 0.0
        reasons = []
        seal = _num(factor.get("seal_strength"), 0.0) or 0.0
        break_count = _int(factor.get("break_count"), 0)
        vol = _num(factor.get("volume_ratio"))
        amount = _num(factor.get("amount_ratio"))
        close_vs_20h = _num(factor.get("close_vs_20d_high_pct"))
        ret_3d = _num(factor.get("ret_3d_pct"))
        ret_5d = _num(factor.get("ret_5d_pct"))
        if seal >= 8:
            score += 18
            reasons.append(f"封单强({seal:.1f}%)")
        elif seal >= 4:
            score += 12
            reasons.append("封单较好")
        else:
            score += 5
        if break_count <= 1:
            score += 8
            reasons.append("炸板少")
        else:
            score -= 8
            reasons.append(f"炸板{break_count}次")
        if vol is not None:
            if 1.0 <= vol <= 3.0:
                score += 15
                reasons.append("有效放量")
            elif vol > 3.0:
                score -= 5
                reasons.append("极端爆量")
        if amount is not None and amount >= 1.2:
            score += 8
            reasons.append("成交额放大")
        if close_vs_20h is not None:
            if -2 <= close_vs_20h <= 8:
                score += 12
                reasons.append("贴近/突破20日新高")
            elif close_vs_20h < -8:
                score -= 10
                reasons.append("距20日高点偏远")
        mom = ret_3d if ret_3d is not None else ret_5d
        if mom is not None:
            if 0 <= mom <= 8:
                score += 10
                reasons.append(f"首板前动量健康({mom:.1f}%)")
            elif mom > 8:
                score += 4
                reasons.append("首板前已明显上涨")
            elif mom < 0:
                score -= 8
                reasons.append("超跌反弹式首板")
        if str(factor.get("sector_name") or factor.get("industry_name") or "").strip():
            score += 6
            reasons.append("有板块归属")
        score = _clamp(score)
        grade = "A" if score >= 75 else ("B" if score >= 60 else "C")
        return {"score": round(score, 2), "grade": grade, "reasons": reasons}

    # ================= 观察池 =================
    def merge_watchlist(
        self,
        discovery: FirstBoardDiscovery,
        prev_watchlist: Optional[List[WatchlistItem]],
        trade_date: str,
    ) -> List[WatchlistItem]:
        by_code = {w.symbol_code: w for w in (prev_watchlist or [])}
        for cand in discovery.candidates:
            item = by_code.get(cand.symbol_code)
            if not item:
                item = WatchlistItem(
                    symbol_code=cand.symbol_code,
                    symbol_name=cand.symbol_name,
                    trade_date=trade_date,
                )
                by_code[cand.symbol_code] = item
            item.factors.append(dict(cand.factor or cand.technical_factor or {}))
            del item.factors[:-5]
            if not item.first_board_event:
                item.first_board_event = cand.first_board_event
                item.first_board_date = cand.first_board_date
                item.first_board_close = cand.first_board_close
                item.first_board_quality_score = cand.first_board_quality_score
                item.first_board_quality_grade = cand.first_board_quality_grade
                item.first_board_quality_reasons = list(cand.first_board_quality_reasons)
                item.candidate = cand.candidate_type
                item.sector_breadth_score = cand.sector_breadth_score
                item.sector_breadth_passed = cand.sector_breadth_passed
                item.sector_breadth_reason = cand.sector_breadth_reason
                item.upside_room_score = cand.upside_room_score
                item.upside_room_passed = cand.upside_room_passed
                item.upside_room_reason = cand.upside_room_reason
                item.gates = dict(cand.gates)
        return list(by_code.values())

    # ================= 生命周期 =================
    def detect_first_board(self, watchlist: List[WatchlistItem], trade_date: str) -> None:
        """从历史序列重建首板事件；已由 discover 标记的保持，未标记的尝试推导。"""
        for item in watchlist:
            if item.first_board_event:
                continue
            prev_limit = False
            for factor in item.factors:
                change = _num(factor.get("change_pct"))
                is_limit = _bool(factor.get("continuous_board") and _int(factor.get("continuous_board")) >= 1)
                if not is_limit and _is_limit_up_change(item.symbol_code, change):
                    is_limit = True
                report_date = str(factor.get("report_date") or item.trade_date)
                if is_limit:
                    if not prev_limit:
                        item.first_board_event = True
                        item.first_board_date = report_date
                        item.first_board_close = _num(factor.get("close"))
                        quality = self._compute_first_board_quality(factor)
                        item.first_board_quality_score = quality["score"]
                        item.first_board_quality_grade = quality["grade"]
                        item.first_board_quality_reasons = list(quality["reasons"])
                        sec = self._compute_sector_breadth_gate(factor)
                        up = self._compute_upside_room_gate(factor)
                        item.sector_breadth_score = sec["score"]
                        item.sector_breadth_passed = sec["passed"]
                        item.sector_breadth_reason = sec["reason"]
                        item.upside_room_score = up["score"]
                        item.upside_room_passed = up["passed"]
                        item.upside_room_reason = up["reason"]
                        item.gates = {"sector_breadth": sec, "upside_room": up}
                    prev_limit = True
                else:
                    prev_limit = False

    def _compute_first_board_continuation_gates(self, item: WatchlistItem, factor: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.config.confirmation or {}
        required = int(cfg.get("continuation_gates_required", 2) or 2)
        gate_names = cfg.get("continuation_gates") or [
            "未快速跌破关键位",
            "未异常放量砸盘",
            "收盘不深跌",
            "VWAP/MA5承接优先",
            "板块/入口评分合格",
        ]
        min_change = float(cfg.get("continuation_min_change_pct", -3.0) or -3.0)
        max_vol = float(cfg.get("continuation_max_volume_ratio", 4.0) or 4.0)
        key_level_pct = float(cfg.get("continuation_key_level_pct", -6.0) or -6.0)
        first_close = item.first_board_close
        change = _num(factor.get("change_pct"))
        vol = _num(factor.get("volume_ratio"))
        low = _num(factor.get("low"))
        close = _num(factor.get("close")) or _num(factor.get("close_price"))
        close_above_ma5 = _bool(factor.get("close_above_ma5"))
        vwap = _num(factor.get("vwap_20")) or _num(factor.get("vwap"))
        sector_ok = _bool(factor.get("sector_breadth_ok")) or _bool(factor.get("sector_confirmed"))
        key_ok = True
        if first_close and low is not None:
            key_ok = bool(low >= first_close * (1 + key_level_pct / 100.0))
        elif first_close and close is not None:
            key_ok = bool(close >= first_close * (1 + key_level_pct / 100.0))
        no_dump = True
        if change is not None and vol is not None:
            no_dump = bool(change >= min_change and vol <= max_vol)
        close_ok = bool(change is not None and change >= min_change)
        hold = False
        if vwap is not None and close is not None:
            hold = bool(close >= vwap)
        elif close_above_ma5:
            hold = True
        gates = {
            "未快速跌破关键位": key_ok,
            "未异常放量砸盘": no_dump,
            "收盘不深跌": close_ok,
            "VWAP/MA5承接优先": hold,
            "板块/入口评分合格": True if sector_ok else True,
        }
        detail = {}
        passed = 0
        for name in gate_names:
            val = bool(gates.get(name, False))
            detail[name] = val
            if val:
                passed += 1
        confirmed = bool(passed >= required)
        reasons = [f"{k}:{'是' if v else '否'}" for k, v in detail.items()]
        return {"confirmed": confirmed, "passed_count": passed, "required": required, "gates": detail, "reasons": reasons}

    def _compute_first_board_continuation_score(self, factor: Dict[str, Any]) -> float:
        score = 50.0
        change = _num(factor.get("change_pct"))
        vol = _num(factor.get("volume_ratio"))
        close = _num(factor.get("close")) or _num(factor.get("close_price"))
        vwap = _num(factor.get("vwap_20")) or _num(factor.get("vwap"))
        close_above_ma5 = _bool(factor.get("close_above_ma5"))
        if change is not None:
            if 0 <= change <= 7:
                score += 20
            elif 7 < change <= 9.5:
                score += 10
            elif change < 0:
                score -= 15
        if vwap is not None and close is not None and close >= vwap:
            score += 15
        if close_above_ma5:
            score += 10
        if vol is not None:
            if 1.0 <= vol <= 3.0:
                score += 10
            elif vol > 3.0:
                score -= 10
        return round(_clamp(score), 2)

    def advance_first_board_state(self, watchlist: List[WatchlistItem], trade_date: str) -> None:
        for item in watchlist:
            if not item.first_board_event:
                continue
            if item.first_board_continuation_confirmed:
                continue
            if item.first_board_date == trade_date:
                continue
            factor = item.latest_factor()
            if not factor:
                continue
            gate = self._compute_first_board_continuation_gates(item, factor)
            if gate["confirmed"]:
                item.first_board_continuation_confirmed = True
                item.first_board_continuation_gate_detail = gate
                item.first_board_continuation_reasons = list(gate["reasons"])
                item.first_board_continuation_score = self._compute_first_board_continuation_score(factor)
            else:
                item.first_board_continuation_reasons = list(gate["reasons"])
                item.first_board_continuation_score = self._compute_first_board_continuation_score(factor)

    # ================= Gate Pipeline（目标：P(MFE[T+1,T+3]>=+3%）最大化）=================
    def _compute_sector_breadth_gate(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.config.first_board or {}
        sector_ok = _bool(factor.get("sector_breadth_ok")) or _bool(factor.get("sector_confirmed"))
        sector_name = str(factor.get("sector_name") or factor.get("industry_name") or "").strip()
        sector_score_raw = _num(factor.get("sector_breadth_score"))
        score = float(sector_score_raw) if sector_score_raw is not None else (70.0 if sector_ok or sector_name else 50.0)
        reasons = []
        if sector_name:
            reasons.append(f"板块:{sector_name}")
        if sector_ok:
            reasons.append("板块共振/确认")
        elif sector_score_raw is not None:
            reasons.append(f"板块共振分{sector_score_raw:.0f}")
        if not sector_name and sector_score_raw is None:
            reasons.append("板块数据缺失，默认放行")
        min_score = float(cfg.get("min_sector_breadth_score", 50) or 50)
        passed = bool(score >= min_score or (not sector_name and sector_score_raw is None))
        reason = "; ".join(reasons) if reasons else ("通过" if passed else "板块共振不足")
        return {"score": round(float(score), 2), "passed": passed, "reason": reason, "detail": {"sector_name": sector_name, "sector_breadth_score": sector_score_raw, "sector_breadth_ok": sector_ok}}

    def _compute_upside_room_gate(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.config.first_board or {}
        min_room = float(cfg.get("min_upside_room_pct", 3.0) or 3.0)
        close_vs20 = _num(factor.get("close_vs_20d_high_pct"))
        close_vs60 = _num(factor.get("close_vs_60d_high_pct"))
        breakout20 = _bool(factor.get("breakout_20d"))
        breakout60 = _bool(factor.get("breakout_60d"))
        ma20dev = _num(factor.get("ma20_deviation_pct"))
        score = 50.0
        reasons = []
        nearest_resist_pct = None
        if close_vs20 is not None:
            if close_vs20 < 0:
                dist = -close_vs20
                nearest_resist_pct = dist if nearest_resist_pct is None else min(nearest_resist_pct, dist)
            elif close_vs20 >= 0:
                score = max(score, 90.0)
                reasons.append("贴近/突破20日高点，上方压力少")
        if close_vs60 is not None and close_vs60 < 0:
            dist = -close_vs60
            nearest_resist_pct = dist if nearest_resist_pct is None else min(nearest_resist_pct, dist)
        if breakout20:
            score = max(score, 75.0)
            reasons.append("20日突破")
        if breakout60:
            score = max(score, 95.0)
            reasons.append("60日突破")
        if nearest_resist_pct is not None and nearest_resist_pct < min_room:
            score = min(score, 30.0)
            reasons.append(f"距压力仅{nearest_resist_pct:.1f}%<{min_room:.1f}%")
        elif nearest_resist_pct is not None and nearest_resist_pct >= min_room:
            score = max(score, 60.0)
            reasons.append(f"距压力{nearest_resist_pct:.1f}%>={min_room:.1f}%")
        if ma20dev is not None and ma20dev > 35:
            score = min(score, 35.0)
            reasons.append("MA20偏离过大")
        passed = bool(score >= float(cfg.get("min_upside_room_score", 50) or 50))
        reason = "; ".join(reasons) if reasons else ("通过" if passed else "上行空间不足")
        return {"score": round(float(score), 2), "passed": passed, "reason": reason, "detail": {"close_vs_20d_high_pct": close_vs20, "close_vs_60d_high_pct": close_vs60, "breakout_20d": breakout20, "breakout_60d": breakout60, "min_room": min_room}}

    def _compute_market_regime_gate(self, trade_date: str) -> Dict[str, Any]:
        """市场环境 Gate：优先使用涨停池情绪温度，缺数据时为放行（避免回测误杀）。"""
        cfg = self.config.market or {}
        min_zt = int(cfg.get("min_limit_up_count", 30) or 30)
        score = 100.0 if not cfg.get("enabled", True) else 50.0
        passed = not bool(cfg.get("enabled", True))
        reasons = []
        if cfg.get("enabled", True):
            if ZT_SEAL_STORE is None:
                reasons.append("涨停池模块缺失，默认放行")
                return {"score": 50.0, "passed": True, "reason": "; ".join(reasons), "detail": {"market_regime_gates": {}}}
            try:
                df = ZT_SEAL_STORE.load(trade_date)
            except Exception:
                df = None
            if df is None or df.empty:
                reasons.append("涨停池数据缺失，默认放行")
                return {"score": 50.0, "passed": True, "reason": "; ".join(reasons), "detail": {"market_regime_gates": {}}}
            zt_count = int(len(df))
            reasons.append(f"涨停家数{zt_count}")
            if zt_count >= min_zt:
                score = max(score, 70.0)
            else:
                score = min(score, 35.0)
                reasons.append(f"涨停家数<{min_zt}")
            passed = bool(score >= float(cfg.get("min_market_score", 50) or 50))
        else:
            passed = True
        if not reasons:
            reasons.append("通过")
        return {"score": round(float(score), 2), "passed": passed, "reason": "; ".join(reasons), "detail": {"market_regime_gates": {}}}

    def _compute_risk_gate(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.config.holding or {}
        reasons = []
        score = 70.0
        name = str(factor.get("symbol_name") or "")
        ma20dev = _num(factor.get("ma20_deviation_pct"))
        vol = _num(factor.get("volume_ratio"))
        if "ST" in name.upper() or "退" in name:
            score = 0.0
            reasons.append("ST/退市风险")
        if ma20dev is not None and ma20dev > 40:
            score -= 20.0
            reasons.append("偏离MA20过高")
        if vol is not None and vol > float(cfg.get("max_volume_ratio", 6.0) or 6.0):
            score -= 15.0
            reasons.append("极端爆量")
        passed = score >= float(cfg.get("min_risk_score", 50) or 50)
        if not reasons:
            reasons.append("风险GATE通过")
        return {"score": round(float(score), 2), "passed": passed, "reason": "; ".join(reasons), "detail": {}}

    def compute_gates(self, item: WatchlistItem, factor: Dict[str, Any], trade_date: str) -> Dict[str, Any]:
        """生成7大Gate；BUY 只在 required gates 全部 PASS 时为 True。"""
        cfg = dict(self.config.confirmation or {})
        required = list(cfg.get("required_gates") or ["first_board_quality", "sector_breadth", "upside_room", "market_regime", "continuation", "entry_quality", "risk"])
        gates: Dict[str, Any] = {}
        fb_passed = bool(item.first_board_quality_score >= float((self.config.first_board or {}).get("min_first_board_quality_score", 60) or 60))
        gates["first_board_quality"] = {"name": "首板质量", "passed": fb_passed, "score": item.first_board_quality_score, "reason": f"首板质量{item.first_board_quality_score:.0f}/{item.first_board_quality_grade}", "detail": {}}
        sec = self._compute_sector_breadth_gate(factor)
        item.sector_breadth_score = sec["score"]
        item.sector_breadth_passed = sec["passed"]
        item.sector_breadth_reason = sec["reason"]
        gates["sector_breadth"] = sec
        up = self._compute_upside_room_gate(factor)
        item.upside_room_score = up["score"]
        item.upside_room_passed = up["passed"]
        item.upside_room_reason = up["reason"]
        gates["upside_room"] = up
        mrkt = self._compute_market_regime_gate(trade_date)
        item.market_regime_score = mrkt["score"]
        item.market_regime_passed = mrkt["passed"]
        item.market_regime_reason = mrkt["reason"]
        gates["market_regime"] = mrkt
        cont = {
            "name": "T+1延续确认",
            "passed": bool(item.first_board_continuation_confirmed),
            "score": item.first_board_continuation_score,
            "reason": "; ".join(item.first_board_continuation_reasons) if item.first_board_continuation_reasons else ("延续通过" if item.first_board_continuation_confirmed else "未通过延续"),
            "detail": item.first_board_continuation_gate_detail,
        }
        gates["continuation"] = cont
        entry = self._compute_entry_quality(factor)
        item.entry_quality_score = round(entry, 2)
        item.entry_quality_passed = bool(entry >= float(cfg.get("min_entry_quality_score", 70) or 70))
        gates["entry_quality"] = {"name": "入场质量", "passed": item.entry_quality_passed, "score": round(entry, 2), "reason": f"入场质量{entry:.0f}", "detail": {}}
        risk = self._compute_risk_gate(factor)
        item.risk_gate_passed = risk["passed"]
        item.risk_gate_reason = risk["reason"]
        gates["risk"] = risk
        all_pass = True
        first_failed = ""
        for k in required:
            g = gates.get(k)
            if not g or not bool(g.get("passed")):
                all_pass = False
                first_failed = first_failed or k
        item.gates = gates
        item.first_failed_gate = first_failed
        return gates

    def build_buy_signals(self, watchlist: List[WatchlistItem], trade_date: str) -> List[BuySignal]:
        cfg = self.config.confirmation or {}
        min_cont = float(cfg.get("min_continuation_score", 60) or 60)
        min_entry = float(cfg.get("min_entry_quality_score", 70) or 70)
        min_quality = float((self.config.first_board or {}).get("min_first_board_quality_score", 60) or 60)
        out = []
        for item in watchlist:
            factor = item.latest_factor()
            if not item.first_board_event or not item.first_board_continuation_confirmed or not factor:
                continue
            gates = self.compute_gates(item, factor, trade_date)
            entry = item.entry_quality_score
            cont = item.first_board_continuation_score
            gate_ready = bool(item.first_board_quality_score >= min_quality
                              and cont >= min_cont
                              and entry >= min_entry)
            # Gate 化核心：所有 required gate 通过才 BUY。
            required = list(cfg.get("required_gates") or ["first_board_quality", "sector_breadth", "upside_room", "market_regime", "continuation", "entry_quality", "risk"])
            all_pass = True
            first_failed = ""
            for k in required:
                g = gates.get(k)
                if not g or not bool(g.get("passed")):
                    all_pass = False
                    first_failed = first_failed or k
            ready = bool(gate_ready and all_pass)
            reasons = list(item.first_board_quality_reasons) + list(item.first_board_continuation_reasons)
            reasons.append(f"首板质量{item.first_board_quality_score:.1f}/{item.first_board_quality_grade}")
            reasons.append(f"延续分{cont:.1f}/{min_cont}")
            reasons.append(f"入场质量{entry:.1f}/{min_entry}")
            if not all_pass:
                reasons.append(f"Gate未全过:{first_failed}")
            item.buy_ready = ready
            item.first_failed_gate = first_failed
            out.append(BuySignal(
                symbol_code=item.symbol_code,
                symbol_name=item.symbol_name,
                trade_date=trade_date,
                lifecycle_state="T+1买入候选" if ready else "首板延续观察",
                pool_type="首板",
                divergence_mode="first_board",
                divergence_score=item.first_board_quality_score,
                candidate=item.candidate,
                entry_quality_score=round(entry, 2),
                entry_quality_passed=item.entry_quality_passed,
                weak_to_strong_score=0.0,
                first_board_continuation_score=round(cont, 2),
                first_board_quality_score=item.first_board_quality_score,
                first_board_quality_grade=item.first_board_quality_grade,
                first_board_continuation_confirmed=item.first_board_continuation_confirmed,
                first_board_event=item.first_board_event,
                first_board_continuation_reasons=list(item.first_board_continuation_reasons),
                gates=gates,
                sector_breadth_passed=item.sector_breadth_passed,
                upside_room_passed=item.upside_room_passed,
                market_regime_passed=item.market_regime_passed,
                risk_gate_passed=item.risk_gate_passed,
                first_failed_gate=first_failed,
                t1_buy_score=round((cont + entry) / 2.0, 2),
                buy_ready=ready,
                reasons=reasons,
            ))
        return out

    def _compute_entry_quality(self, factor: Dict[str, Any]) -> float:
        score = 50.0
        change = _num(factor.get("change_pct"))
        close = _num(factor.get("close")) or _num(factor.get("close_price"))
        open_price = _num(factor.get("open"))
        close_vs_20h = _num(factor.get("close_vs_20d_high_pct"))
        ma20_dev = _num(factor.get("ma20_deviation_pct"))
        if change is not None:
            if 0 <= change <= 7:
                score += 10
            elif 7 < change <= 9.5:
                score -= 5
            elif change < -2:
                score -= 12
        if open_price is not None and close is not None and close < open_price:
            score -= 8
        if close_vs_20h is not None and close_vs_20h <= -8:
            score -= 12
        elif close_vs_20h is not None and close_vs_20h >= -2:
            score += 8
        if ma20_dev is not None:
            if -3 <= ma20_dev <= 18:
                score += 6
            elif ma20_dev > 35:
                score -= 8
        return round(_clamp(score), 2)

    # ================= T+1~T+3 管理 =================
    def evaluate_exits(self, holdings: List[Holding]) -> List[ExitDecision]:
        cfg = self.config.holding or {}
        stop_loss = float(cfg.get("stop_loss_pct", -6.0) or -6.0)
        take_profit = float(cfg.get("take_profit_pct", 5.0) or 5.0)
        out = []
        for h in holdings:
            current = h.current_price
            if current is None:
                out.append(ExitDecision(h.symbol_code, h.symbol_name, action="hold", reason="价格数据缺失", current_return_pct=0.0))
                continue
            ret = (current - h.entry_price) / h.entry_price * 100.0 if h.entry_price else 0.0
            reasons = []
            score = 0.0
            if ret <= stop_loss:
                score += 50
                reasons.append(f"止损{stop_loss:.1f}%")
            if ret >= take_profit:
                score += 30
                reasons.append(f"止盈{take_profit:.1f}%")
            if h.holding_days > int(cfg.get("fast_exit_after", 3) or 3):
                score += 8
                reasons.append("超期")
            action = "sell" if score >= 50 else "hold"
            out.append(ExitDecision(
                symbol_code=h.symbol_code,
                symbol_name=h.symbol_name,
                action=action,
                reason=" | ".join(reasons) if reasons else "继续持有",
                exit_score=round(score, 2),
                current_return_pct=round(ret, 2),
                stop_loss_triggered=bool(ret <= stop_loss),
                take_profit_triggered=bool(ret >= take_profit),
            ))
        return out

    def _board_quality(self, factor: Dict[str, Any]) -> Dict[str, Any]:
        """Backward-compat: alias for _compute_first_board_quality."""
        return self._compute_first_board_quality(factor)

    # ================= 回测标签（P0） =================
    def compute_outcome_for_signal(
        self,
        symbol_code: str,
        entry_date: str,
        horizon_days: int = 3,
        positive_pct: float = 3.0,
        start_date: str = "",
    ) -> Optional[Any]:
        """Fetch historical OHLCV and compute Entry + MFE/MAE/CloseReturn labels.

        必须用实际可能买点（T+1 开盘），不能直接用首板后最高价。
        """
        from strategies.first_board_continue.outcome import compute_outcome_metrics, normalize_dates
        code = _normalize_code(symbol_code)
        if not code or not entry_date:
            return None
        # 用交易日期列表确定 未来 horizon_days 个交易日（回测标签用，不在当日触发逻辑中使用）。
        try:
            if not start_date:
                from utils.date_utils import get_trading_date_range
                start_date, _ = get_trading_date_range(end_date=entry_date, count=60, include_end=True)
            trade_dates = GLOBAL_MARKET_MANAGER.get_trade_date(market_name="CN-Stock")
            trade_dates = [str(d).replace("-", "").replace("/", "") for d in trade_dates]
            compact_entry = "".join(ch for ch in str(entry_date) if ch.isdigit())[:8]
            future = [d for d in sorted(trade_dates) if d > compact_entry][: horizon_days]
            if not future:
                return None
            end_future = future[-1]
            hist = get_stock_zh_a_hist(
                symbol=code[:6],
                start_date=start_date,
                end_date=end_future,
                adjust="qfq",
                verbose=False,
            )
            row_map = normalize_dates(hist)
            metrics = compute_outcome_metrics(row_map, compact_entry, horizon_days=horizon_days, positive_pct=positive_pct)
            return metrics.to_dict() if metrics else None
        except Exception:
            return None

    # ================= 导出 - 辅助 =================
    def _write_result(self, result: Dict[str, Any], output_dir: str) -> None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
