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
        return FirstBoardCandidate(
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
            entry = self._compute_entry_quality(factor)
            item.entry_quality_score = round(entry, 2)
            cont = item.first_board_continuation_score
            ready = bool(cont >= min_cont and entry >= min_entry and item.first_board_quality_score >= min_quality)
            reasons = list(item.first_board_quality_reasons) + list(item.first_board_continuation_reasons)
            reasons.append(f"首板质量{item.first_board_quality_score:.1f}/{item.first_board_quality_grade}")
            reasons.append(f"延续分{cont:.1f}/{min_cont}")
            reasons.append(f"入场质量{entry:.1f}/{min_entry}")
            if not ready:
                reasons.append("延续或入场质量不足")
            item.buy_ready = ready
            out.append(BuySignal(
                symbol_code=item.symbol_code,
                symbol_name=item.symbol_name,
                trade_date=trade_date,
                lifecycle_state="T+1买入候选" if ready else "首板延续观察",
                pool_type="首板",
                divergence_mode="first_board",
                divergence_score=item.first_board_quality_score,
                entry_quality_score=round(entry, 2),
                weak_to_strong_score=0.0,
                first_board_continuation_score=round(cont, 2),
                first_board_quality_score=item.first_board_quality_score,
                first_board_quality_grade=item.first_board_quality_grade,
                first_board_continuation_confirmed=item.first_board_continuation_confirmed,
                first_board_event=item.first_board_event,
                first_board_continuation_reasons=list(item.first_board_continuation_reasons),
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

    # ================= 导出辅助 =================
    def _write_result(self, result: Dict[str, Any], output_dir: str) -> None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
