"""
Web Application for AI Trading System
FastAPI + SSE for real-time agent status updates
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from main_loop import SimpleTradeCompany
from config.strategies import get_strategy, get_strategies

app = FastAPI(title="AI Trading System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# session_id -> asyncio.Queue
streams: dict[str, asyncio.Queue] = {}
company: Optional["SseTradeCompany"] = None


class SseTradeCompany(SimpleTradeCompany):
    async def _emit(self, queue: asyncio.Queue, event_type: str, data: dict):
        await queue.put({
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        })

    async def run_with_queue(self, queue: asyncio.Queue, trigger_time: str):
        await self._emit(queue, "system", {"message": f"Starting analysis at {trigger_time}", "stage": "init"})

        strategy = self.strategy or {}
        await self._emit(queue, "stage", {
            "message": f"[{strategy.get('short_name','')}] Stage 1: Running Data Agents...",
            "stage": "data_agents",
            "total": len(self.data_agents),
            "strategy": strategy,
        })
        data_factors = await self._run_data_agents_sse(queue, trigger_time)
        await self._emit(queue, "stage_complete", {
            "message": f"Data Agents completed: {len(data_factors)} factors",
            "stage": "data_agents",
            "count": len(data_factors),
        })

        market_context = self._build_market_context(data_factors)

        require_min_buys, max_rounds = self._get_signal_selection_settings()
        await self._emit(queue, "stage", {
            "message": (
                f"Stage 2+3: Research + strict buy selection "
                f"(require_min_buys={require_min_buys}, max_rounds={max_rounds})..."
            ),
            "stage": "research_selection",
            "require_min_buys": require_min_buys,
            "max_research_rounds": max_rounds,
        })

        async def research_runner(trigger_time_arg: str, data_factors_arg: list):
            return await self._run_research_agents_sse(queue, trigger_time_arg, data_factors_arg)

        async def on_round_start(round_num: int, max_rounds_arg: int):
            await self._emit(queue, "stage", {
                "message": f"Research round {round_num}/{max_rounds_arg}...",
                "stage": "research_agents",
                "round": round_num,
                "max_rounds": max_rounds_arg,
                "total": len(self.research_agents),
            })

        async def on_round_complete(round_num: int, stats: dict):
            await self._emit(queue, "stage_complete", {
                "message": (
                    f"Round {round_num}: {stats['buy_count']} buys, "
                    f"{stats['watchlist_count']} watchlist, "
                    f"{stats['total_signals']} total signals"
                ),
                "stage": "research_agents",
                "round": round_num,
                **stats,
            })

        selection = await self._run_research_and_select_until_min_buys(
            trigger_time=trigger_time,
            data_factors=data_factors,
            market_context=market_context,
            research_runner=research_runner,
            on_round_start=on_round_start,
            on_round_complete=on_round_complete,
        )
        research_signals = selection["research_signals"]
        buy_signals = selection["buy_signals"]
        watchlist = selection["watchlist"]

        await self._emit(queue, "stage_complete", {
            "message": (
                f"Signal selection completed after {selection['research_rounds']} round(s): "
                f"{len(buy_signals)} buys, {len(watchlist)} watchlist"
            ),
            "stage": "selection",
            "count": len(buy_signals),
            "watchlist_count": len(watchlist),
            "research_rounds": selection["research_rounds"],
            "require_min_buys_met": selection["require_min_buys_met"],
        })

        result = {
            "trigger_time": trigger_time,
            "data_factors": data_factors,
            "research_signals": research_signals,
            "buy_signals": buy_signals,
            "watchlist": watchlist,
            "best_signals": buy_signals,
            "market_context": market_context,
            "system_health": self.system_health,
            "strategy": self.strategy,
            "research_rounds": selection["research_rounds"],
            "require_min_buys": selection["require_min_buys"],
            "require_min_buys_met": selection["require_min_buys_met"],
        }
        await self._emit(queue, "complete", {
            "message": "Analysis Complete",
            "data_factors_count": len(data_factors),
            "research_signals_count": len(research_signals),
            "buy_signals_count": len(buy_signals),
            "watchlist_count": len(watchlist),
            "best_signals_count": len(buy_signals),
            "research_rounds": selection["research_rounds"],
            "require_min_buys_met": selection["require_min_buys_met"],
        })
        await self._emit(queue, "result", {"result": result})
        await self._emit(queue, "stream_end", {"message": "Stream complete"})
        await queue.put(None)  # sentinel

    async def _run_data_agents_sse(self, queue: asyncio.Queue, trigger_time: str) -> list:
        tasks = []

        async def run_one(agent_id, pipeline):
            async def emit_source_result(result):
                await self._emit(queue, "agent_result", {
                    "agent_type": "data",
                    "agent_id": agent_id,
                    "agent_name": pipeline.agent_name,
                    "message": f"{pipeline.agent_name} produced a result",
                    "result": {**result, "agent_id": agent_id},
                })

            try:
                result = await pipeline.run(trigger_time, on_result=emit_source_result)
                return agent_id, pipeline, result, None
            except Exception as exc:
                return agent_id, pipeline, None, exc

        for agent_id, pipeline in self.data_agents.items():
            await self._emit(queue, "agent_start", {
                "agent_type": "data",
                "agent_id": agent_id,
                "agent_name": pipeline.agent_name,
                "message": f"Running {pipeline.agent_name}...",
            })
            tasks.append(asyncio.create_task(run_one(agent_id, pipeline)))

        results = []
        # Consume tasks in actual completion order so a fast agent is never
        # hidden behind an earlier, slower task.
        for completed in asyncio.as_completed(tasks):
            agent_id, pipeline, result, error = await completed
            if error is not None:
                await self._emit(queue, "agent_error", {
                    "agent_type": "data",
                    "agent_id": agent_id,
                    "agent_name": pipeline.agent_name,
                    "message": f"{pipeline.agent_name} failed: {str(error)}",
                })
                continue

            if result and result.get("context_string"):
                results.append(result)
                await self._emit(queue, "agent_complete", {
                    "agent_type": "data",
                    "agent_id": agent_id,
                    "agent_name": pipeline.agent_name,
                    "message": f"{pipeline.agent_name} completed",
                    "result": {
                        "agent_id": agent_id,
                        "agent_name": result.get("agent_name", pipeline.agent_name),
                        "trigger_time": result.get("trigger_time", trigger_time),
                        "context_string": result.get("context_string", ""),
                    },
                })
        return results

    async def _run_research_agents_sse(self, queue: asyncio.Queue, trigger_time: str, data_factors: list) -> list:
        from agents.research_agent_loop import ResearchAgentInput

        tasks = []

        async def run_one(agent_id, agent, input_data):
            try:
                return agent_id, agent, await agent.run(input_data), None
            except Exception as exc:
                return agent_id, agent, None, exc

        for agent_id, agent in self.research_agents.items():
            await self._emit(queue, "agent_start", {
                "agent_type": "research",
                "agent_id": agent_id,
                "agent_name": agent.config.agent_name,
                "belief": agent.config.belief,
                "message": f"Running {agent.config.agent_name}...",
            })
            background = agent.build_background_information(trigger_time, agent.config.belief, data_factors)
            input_data = ResearchAgentInput(trigger_time=trigger_time, background_information=background)
            tasks.append(asyncio.create_task(run_one(agent_id, agent, input_data)))

        all_signals = []
        for completed in asyncio.as_completed(tasks):
            agent_id, agent, result, error = await completed
            if error is not None:
                await self._emit(queue, "agent_error", {
                    "agent_type": "research",
                    "agent_id": agent_id,
                    "agent_name": agent.config.agent_name,
                    "message": f"{agent.config.agent_name} failed: {str(error)}",
                })
                continue

            if result and result.final_result:
                signals = self._parse_signals(result)
                agent_signals = signals[:5]
                for i, signal in enumerate(agent_signals):
                    signal["agent_id"] = agent_id
                    signal["agent_name"] = agent.config.agent_name
                    signal["signal_index"] = i + 1
                    all_signals.append(signal)
                await self._emit(queue, "agent_complete", {
                    "agent_type": "research",
                    "agent_id": agent_id,
                    "agent_name": agent.config.agent_name,
                    "message": f"{agent.config.agent_name} completed",
                    "signals_count": len(agent_signals),
                    "result": {"signals": agent_signals},
                })
        return all_signals


@app.on_event("startup")
async def startup_event():
    global company
    company = SseTradeCompany()


class StartRequest(BaseModel):
    trigger_time: str = ""
    strategy: str = "momentum"


@app.post("/api/start")
async def start_analysis(body: StartRequest):
    global company
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    streams[session_id] = queue
    trigger_time = body.trigger_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Rebuild company with selected strategy so all agents/gates use that config.
    strategy = get_strategy(body.strategy)
    company = SseTradeCompany(strategy=body.strategy)
    await company._emit(queue, "system", {
        "message": f"Strategy: {strategy.get('name')} · {strategy.get('short_name')}",
        "stage": "init",
        "strategy_id": strategy.get("id"),
        "strategy": strategy,
    })
    asyncio.create_task(company.run_with_queue(queue, trigger_time))
    return {"session_id": session_id, "strategy": strategy.get("id")}


@app.get("/api/stream/{session_id}")
async def stream_events(session_id: str):
    async def generate():
        queue = streams.get(session_id)
        if not queue:
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'Session not found'}})}\n\n"
            return
        stream_completed = False
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10.0)
                    if event is None:
                        stream_completed = True
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            # A browser/proxy connection can be reset while agents are still
            # running. Preserve the queue so EventSource can reconnect and
            # continue consuming this session instead of losing all results.
            if stream_completed:
                streams.pop(session_id, None)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/strategies")
async def list_strategies():
    """Return both trading strategies (swing / momentum) for the UI."""
    return {"strategies": get_strategies()}


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "agents": {
            "data_agents": len(company.data_agents) if company else 0,
            "research_agents": len(company.research_agents) if company else 0,
        },
    }


@app.get("/api/status")
async def get_status():
    return {
        "server": "AI Trading System",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(streams),
    }


# ===== Factor Store & Backtest APIs =====

@app.get("/api/factors/summary")
async def get_factor_summary():
    """获取所有因子存储的摘要"""
    from utils.factor_store import get_all_stores
    stores = get_all_stores()
    result = {}
    for name, store in stores.items():
        stats = store.get_stats()
        result[name] = stats
    return result


@app.get("/api/factors/{factor_name}/data")
async def get_factor_data(factor_name: str, start_date: str = "", end_date: str = ""):
    """获取某个因子的历史数据"""
    from utils.factor_store import get_all_stores
    stores = get_all_stores()
    if factor_name not in stores:
        return {"error": f"Factor '{factor_name}' not found"}

    store = stores[factor_name]
    if start_date and end_date:
        df = store.load_range(start_date, end_date)
    else:
        df = store.load_all()

    if df.empty:
        return {"data": [], "count": 0}

    records = df.to_dict(orient="records")
    return {"data": records, "count": len(records)}


@app.get("/api/factors/{factor_name}/dates")
async def get_factor_dates(factor_name: str):
    """获取某个因子的可用日期列表"""
    from utils.factor_store import get_all_stores
    stores = get_all_stores()
    if factor_name not in stores:
        return {"error": f"Factor '{factor_name}' not found"}
    return {"dates": stores[factor_name].get_available_dates()}


@app.post("/api/backtest/run")
async def run_backtest(factor_name: str = "all"):
    """运行因子回测"""
    from utils.factor_store import get_all_stores
    from tools.factor_backtest import FactorBacktester, FactorRecord

    stores = get_all_stores()
    backtester = FactorBacktester(horizons=[1, 3, 5])
    results = {}

    targets = stores.items() if factor_name == "all" else [(factor_name, stores.get(factor_name))]

    for name, store in targets:
        if store is None:
            results[name] = {"error": f"Factor '{name}' not found"}
            continue

        all_data = store.load_all()
        if all_data.empty:
            results[name] = {"error": "No data available", "total_signals": 0}
            continue

        records = []
        for _, row in all_data.iterrows():
            code = str(row.get("symbol_code", ""))
            if not code.isdigit() or len(code) != 6:
                continue
            records.append(FactorRecord(
                symbol_code=code,
                symbol_name=str(row.get("symbol_name", "")),
                factor_date=str(row.get("factor_date", "")),
                factor_name=name,
                factor_value=float(row.get("factor_value", 0)),
            ))

        if not records:
            results[name] = {"error": "No valid factor records", "total_signals": 0}
            continue

        result = backtester.run(records, name)
        results[name] = {
            "factor_name": result.factor_name,
            "total_signals": result.total_signals,
            "evaluated_signals": result.evaluated_signals,
            "horizons": result.horizons,
            "quintile_returns": result.quintile_returns,
            "ic_values": result.ic_values,
            "walk_forward": result.walk_forward,
        }

    return results


@app.get("/api/backtest/results")
async def get_backtest_results():
    """获取已有的回测结果"""
    from config.config import PROJECT_ROOT
    import json as json_mod

    results_dir = PROJECT_ROOT / "agents_workspace" / "backtest_results"
    if not results_dir.exists():
        return {"results": {}}

    all_results = {}
    for factor_dir in results_dir.iterdir():
        if not factor_dir.is_dir():
            continue
        summaries = sorted(factor_dir.glob("summary_*.json"), reverse=True)
        if summaries:
            with open(summaries[0], "r", encoding="utf-8") as f:
                all_results[factor_dir.name] = json_mod.load(f)

    return {"results": all_results}


@app.get("/api/performance/history")
async def get_performance_history():
    """获取信号绩效历史"""
    from config.config import PROJECT_ROOT
    import json as json_mod

    history_file = PROJECT_ROOT / "agents_workspace" / "performance" / "performance_history.json"
    pending_file = PROJECT_ROOT / "agents_workspace" / "performance" / "pending_signals.json"

    history = []
    pending = []
    if history_file.exists():
        with open(history_file, "r", encoding="utf-8") as f:
            history = json_mod.load(f)
    if pending_file.exists():
        with open(pending_file, "r", encoding="utf-8") as f:
            pending = json_mod.load(f)

    # Compute summary stats
    total = len(history)
    hits = sum(1 for r in history if r.get("hit"))
    win_rate = (hits / total * 100) if total > 0 else 0
    avg_return = sum(r.get("actual_return_pct", 0) for r in history) / total if total > 0 else 0

    return {
        "history": history,
        "pending": pending,
        "stats": {
            "total": total,
            "hits": hits,
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg_return, 2),
            "pending_count": len(pending),
        },
    }


# ===== Threshold Management APIs =====

@app.get("/api/thresholds")
async def get_thresholds():
    """获取所有阈值配置"""
    from utils.threshold_manager import THRESHOLD_MANAGER, THRESHOLD_METADATA
    return {
        "thresholds": THRESHOLD_MANAGER.get_all(),
        "metadata": THRESHOLD_METADATA,
    }


@app.post("/api/thresholds/{factor_name}")
async def update_thresholds(factor_name: str, body: dict):
    """更新某个因子的阈值"""
    from utils.threshold_manager import THRESHOLD_MANAGER
    updates = body.get("updates", {})
    if not updates:
        return {"error": "No updates provided"}
    THRESHOLD_MANAGER.update(factor_name, updates)
    return {"status": "ok", "thresholds": THRESHOLD_MANAGER.get(factor_name)}


@app.post("/api/thresholds/{factor_name}/reset")
async def reset_thresholds(factor_name: str):
    """重置某个因子的阈值到默认值"""
    from utils.threshold_manager import THRESHOLD_MANAGER
    THRESHOLD_MANAGER.reset(factor_name)
    return {"status": "ok", "thresholds": THRESHOLD_MANAGER.get(factor_name)}


@app.post("/api/thresholds/calibrate")
async def calibrate_thresholds():
    """基于回测结果自动校准所有因子阈值"""
    from utils.threshold_manager import THRESHOLD_MANAGER
    from utils.factor_store import get_all_stores
    from tools.factor_backtest import FactorBacktester, FactorRecord

    stores = get_all_stores()
    backtester = FactorBacktester(horizons=[1, 3, 5])
    calibration_results = {}

    for name, store in stores.items():
        all_data = store.load_all()
        if all_data.empty:
            calibration_results[name] = {"status": "no_data"}
            continue

        records = []
        for _, row in all_data.iterrows():
            code = str(row.get("symbol_code", ""))
            if not code.isdigit() or len(code) != 6:
                continue
            records.append(FactorRecord(
                symbol_code=code,
                symbol_name=str(row.get("symbol_name", "")),
                factor_date=str(row.get("factor_date", "")),
                factor_name=name,
                factor_value=float(row.get("factor_value", 0)),
            ))

        if len(records) < 10:
            calibration_results[name] = {"status": "insufficient_data", "count": len(records)}
            continue

        result = backtester.run(records, name)
        backtest_data = {
            "ic_values": result.ic_values,
            "horizons": result.horizons,
            "walk_forward": result.walk_forward,
        }
        cal_result = THRESHOLD_MANAGER.auto_calibrate(name, backtest_data)
        calibration_results[name] = cal_result

    return {
        "status": "ok",
        "calibration": calibration_results,
        "new_thresholds": THRESHOLD_MANAGER.get_all(),
    }


# ===== Main Trend Dashboard APIs =====

@app.get("/api/main_trend/dashboard")
async def main_trend_dashboard(date: str = ""):
    """主升浪 Dashboard：T日候选 / T+1执行 / 持仓 / 退出状态 汇总。"""
    from config.config import PROJECT_ROOT
    from strategies.main_trend.dashboard import build_dashboard

    base = PROJECT_ROOT / "agents_workspace_main_trend"
    return build_dashboard(base, date=date)


@app.get("/api/main_trend/dates")
async def main_trend_dates():
    """主升浪可用日期列表。"""
    from config.config import PROJECT_ROOT
    from strategies.main_trend.dashboard import list_day_dirs

    base = PROJECT_ROOT / "agents_workspace_main_trend"
    return {"ok": True, "dates": list_day_dirs(base)}


@app.get("/api/main_trend/holdings")
async def main_trend_holdings(date: str = ""):
    from config.config import PROJECT_ROOT
    from strategies.main_trend.dashboard import latest_holdings_payload

    base = PROJECT_ROOT / "agents_workspace_main_trend"
    if date:
        key = str(date).replace("-", "").replace("/", "")
        import json as json_mod
        from pathlib import Path as _Path
        latest = {}
        lp = base / key / "t2" / "latest.json"
        if lp.exists():
            latest = json_mod.loads(lp.read_text(encoding="utf-8"))
        t2h = _Path(latest["path"]) / "holdings.json" if latest.get("path") else None
        if t2h and t2h.exists():
            return json_mod.loads(t2h.read_text(encoding="utf-8"))
        hp = base / key / "holdings.json"
        if hp.exists():
            return json_mod.loads(hp.read_text(encoding="utf-8"))
        return {"present": False, "error": f"No holdings for {key}"}
    return latest_holdings_payload(base)


@app.get("/api/main_trend/exit_decisions")
async def main_trend_exit(date: str = ""):
    from config.config import PROJECT_ROOT
    from strategies.main_trend.dashboard import latest_exit_payload

    base = PROJECT_ROOT / "agents_workspace_main_trend"
    if date:
        key = str(date).replace("-", "").replace("/", "")
        import json as json_mod
        from pathlib import Path as _Path
        latest = {}
        lp = base / key / "t2" / "latest.json"
        if lp.exists():
            latest = json_mod.loads(lp.read_text(encoding="utf-8"))
        t2e = _Path(latest["path"]) / "exit_decisions.json" if latest.get("path") else None
        if t2e and t2e.exists():
            return json_mod.loads(t2e.read_text(encoding="utf-8"))
        ep = base / key / "exit_decisions.json"
        if ep.exists():
            return json_mod.loads(ep.read_text(encoding="utf-8"))
        return {"present": False, "error": f"No exit decisions for {key}"}
    return latest_exit_payload(base)


@app.get("/api/main_trend/candidates")
async def main_trend_candidates(date: str = ""):
    from config.config import PROJECT_ROOT
    from strategies.main_trend.dashboard import latest_tday_payload

    base = PROJECT_ROOT / "agents_workspace_main_trend"
    if date:
        key = str(date).replace("-", "").replace("/", "")
        cp = base / key / "tday_pool.json"
        if cp.exists():
            import json as json_mod
            return json_mod.loads(cp.read_text(encoding="utf-8"))
        return {"present": False, "error": f"No tday candidates for {key}"}
    return latest_tday_payload(base)


@app.post("/api/main_trend/holdings/init")
async def main_trend_holdings_init(body: dict = {}):
    """根据已有 t1_execution 初始化持仓文件。POST JSON {date, tday, t1}。"""
    from config.config import PROJECT_ROOT
    import json as json_mod
    from pathlib import Path as _Path
    from strategies.main_trend.holdings import build_from_t1

    base = PROJECT_ROOT / "agents_workspace_main_trend"
    date = str(body.get("date") or "").replace("-", "").replace("/", "")
    if not date:
        return {"error": "date required", "ok": False}
    tday_arg = str(body.get("tday") or "")
    t1_arg = str(body.get("t1") or "")

    tday_path = _Path(tday_arg).expanduser() if tday_arg else base / date / "tday_pool.json"
    t1_path = _Path(t1_arg).expanduser() if t1_arg else base / date / "t1_execution.json"
    if not tday_path.is_absolute():
        tday_path = PROJECT_ROOT / tday_path
    if not t1_path.is_absolute():
        t1_path = PROJECT_ROOT / t1_path
    # 兜底：在 date dir 找不到就在所有日期里找
    if not tday_path.exists():
        from strategies.main_trend.dashboard import latest_tday_payload, latest_t1_payload
        latest = latest_tday_payload(base)
        if latest.get("present"):
            tday_path = _Path(latest["path"])
    if not t1_path.exists():
        from strategies.main_trend.dashboard import latest_tday_payload, latest_t1_payload
        latest_t1 = latest_t1_payload(base)
        if latest_t1.get("present"):
            t1_path = _Path(latest_t1["path"])
    if not tday_path.exists() or not t1_path.exists():
        return {"ok": False, "error": f"tday/t1 not found: {tday_path} / {t1_path}", "tday": str(tday_path), "t1": str(t1_path)}

    tday = json_mod.loads(tday_path.read_text(encoding="utf-8"))
    t1 = json_mod.loads(t1_path.read_text(encoding="utf-8"))
    payload = build_from_t1(tday, t1, date=date)
    out_dir = base / date
    out_dir.mkdir(parents=True, exist_ok=True)
    hp = out_dir / "holdings.json"
    hp.write_text(json_mod.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "date": date, "count": payload["count"], "path": str(hp), "holdings": payload["holdings"]}



@app.get("/api/main_trend/realtime")
async def main_trend_realtime(date: str = ""):
    """实时拉取当日行情计算持仓收益，并跑状态机但不持久化。"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from config.config import PROJECT_ROOT
    from strategies.main_trend.dashboard import latest_holdings_payload, _payload_for_date
    from strategies.main_trend.engine import MainTrendConfig, MainTrendEngine
    from strategies.main_trend.schemas import Holding
    from utils.tencent_realtime import fetch_realtime_quote

    base = PROJECT_ROOT / "agents_workspace_main_trend"
    if date:
        key = str(date).replace("-", "").replace("/", "")
        payload = _payload_for_date(base, key, "holdings.json", "holdings") or {}
    else:
        payload = latest_holdings_payload(base) or {}
    if not payload.get("present"):
        return {"ok": False, "error": "no holdings", "holdings_present": False}
    rows = [dict(r) for r in (payload.get("rows") or []) if r.get("symbol_code")]
    if not rows:
        return {"ok": False, "error": "no holdings rows"}

    engine = MainTrendEngine(MainTrendConfig.from_yaml())

    def _one(r: dict) -> dict:
        code = str(r.get("symbol_code") or "")
        q = fetch_realtime_quote(code, prefer="tencent", timeout=3.0)
        out = dict(r)
        if q and q.price:
            out["realtime_price"] = q.price
            out["current_price"] = q.price
            out["realtime_source"] = q.source
            out["realtime_timestamp"] = q.timestamp
            rt = dict(out.get("realtime_quote") or {})
            qd = q.to_dict()
            rt["vwap_state"] = "Above" if (q.vwap and q.price >= q.vwap) else rt.get("vwap_state", "")
            rt["atr"] = q.detail.get("atr") if q.detail.get("atr") else rt.get("atr")
            rt["order_flow_score"] = rt.get("order_flow_score") or 50.0
            for k in ("bid", "ask", "bid_volume", "ask_volume", "active_buy_pct", "bid_ask_ratio", "bid_ask_imbalance", "bids", "asks", "external_volume", "internal_volume", "volume_ratio", "amount_wan"):
                if k in ("bids", "asks") or qd.get(k) is not None:
                    rt[k] = qd.get(k)
            if q.prev_close is not None:
                rt["prev_close"] = q.prev_close
            out["realtime_quote"] = rt
        return out

    with ThreadPoolExecutor(max_workers=12) as pool:
        new_rows = list(pool.map(_one, rows))
    # 实时报价的 prev_close 与当前价统一，避免因原文 prev_close 与腾讯 return 口径不一致导致箭头判断错误
    for r in new_rows:
        rt = r.get("realtime_quote") or {}
        q_prev = None
        qd = rt
        if qd.get("prev_close") is not None:
            q_prev = qd.get("prev_close")
        if q_prev is None:
            q_prev = (rt.get("detail") or {}).get("prev_close")
        if q_prev is not None:
            r["prev_close"] = q_prev

    def _float(v):
        try:
            return float(v)
        except Exception:
            return None

    holdings = []
    for r in new_rows:
        try:
            holdings.append(Holding(
                symbol_code=str(r.get("symbol_code") or ""),
                symbol_name=str(r.get("symbol_name") or ""),
                entry_date=str(r.get("entry_date") or ""),
                entry_price=float(r.get("entry_price") or 0),
                quantity=int(r.get("quantity") or 0),
                holding_days=int(r.get("holding_days") or 0),
                highest_price=_float(r.get("highest_price")) or _float(r.get("entry_price")) or 0.0,
                highest_close=_float(r.get("highest_close")),
                current_price=_float(r.get("current_price")),
                buy_score=float(r.get("buy_score") or 0),
                signal_tier=str(r.get("signal_tier") or "A"),
                trade_plan=r.get("trade_plan") or {},
                stop_loss_price=_float(r.get("stop_loss_price")),
                atr_trailing_stop=_float(r.get("atr_trailing_stop")),
                prev_close=_float(r.get("prev_close")),
                ma10=_float(r.get("ma10")),
                ma20=_float(r.get("ma20")),
                prev_ma20=_float(r.get("prev_ma20")),
                event_catalyst=r.get("event_catalyst") or {},
                realtime_quote=r.get("realtime_quote") or {},
                order_flow_score=float(r.get("order_flow_score") or 50),
            ))
        except Exception:
            continue

    if not holdings:
        return {"ok": False, "error": "no parseable holdings"}

    decisions = [d.to_dict() for d in engine.evaluate_exits(holdings, refresh_factors=True, trade_date=payload.get("trade_date") or date or "")]
    rows_by_code = {str(r.get("symbol_code") or ""): r for r in new_rows}
    # 返回收益统计
    total = 0.0
    count = 0
    for h in holdings:
        if h.current_price:
            total += (h.current_price / h.entry_price - 1.0) * 100.0
            count += 1
    avg_return = total / count if count else 0.0
    sells = [d for d in decisions if d.get("action") in ("sell", "exit")]
    reduces = [d for d in decisions if d.get("action") == "reduce"]
    # 构建完整持仓行：原始字段 + 实时价 + 实时收益 + 退出状态
    full_holdings = []
    for h, d in zip(holdings, decisions):
        row = dict(h.__dict__)  # Holding dataclass 字段
        orig = rows_by_code.get(h.symbol_code) or {}
        row["suggested_position_pct"] = orig.get("suggested_position_pct")
        row["raw_position_pct"] = orig.get("raw_position_pct")
        if row.get("realtime_quote") is None:
            row["realtime_quote"] = {}
        row["symbol_code"] = h.symbol_code
        row["symbol_name"] = h.symbol_name
        row["current_price"] = h.current_price
        row["return_pct"] = round((h.current_price / h.entry_price - 1.0) * 100.0, 2) if h.entry_price and h.current_price else 0.0
        row["current_return_pct"] = row["return_pct"]
        row["entry_price"] = h.entry_price
        row["exit_class"] = d.get("exit_class")
        row["exit_action"] = d.get("action")
        row["position_state"] = d.get("state") or d.get("position_state") or ""
        from strategies.main_trend.holdings import compute_display_status
        row["display_status"] = compute_display_status(row)
        row["exit_level"] = d.get("exit_level")
        row["exit_reason"] = d.get("reason")
        row["exit_reasons"] = d.get("reasons") or []
        row["trailing_stop_price"] = d.get("trailing_stop_price")
        row["target_price_1"] = d.get("target_price_1") or (h.trade_plan or {}).get("target_price_1")
        row["target_price_2"] = d.get("target_price_2") or (h.trade_plan or {}).get("target_price_2")
        row["profit_protect_price"] = d.get("profit_protect_price") or (h.trade_plan or {}).get("profit_protect_price")
        row["profit_protect_level"] = d.get("profit_protect_level") or (h.trade_plan or {}).get("profit_protect_level")
        row["profit_protect_reason"] = d.get("profit_protect_reason") or (h.trade_plan or {}).get("profit_protect_reason")
        row["reason"] = d.get("reason")
        row["realtime_source"] = orig.get("realtime_source") if orig.get("realtime_source") else (h.realtime_quote.get("source") if isinstance(h.realtime_quote, dict) else None)
        full_holdings.append(row)
    return {
        "ok": True,
        "as_of_date": payload.get("trade_date") or "",
        "positions_count": len(decisions),
        "avg_return_pct": round(avg_return, 2),
        "realtime_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "sell_count": len(sells),
        "reduce_count": len(reduces),
        "holdings": full_holdings,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
