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

        await self._emit(queue, "stage", {
            "message": "Stage 1: Running Data Agents...",
            "stage": "data_agents",
            "total": len(self.data_agents),
        })
        data_factors = await self._run_data_agents_sse(queue, trigger_time)
        await self._emit(queue, "stage_complete", {
            "message": f"Data Agents completed: {len(data_factors)} factors",
            "stage": "data_agents",
            "count": len(data_factors),
        })

        await self._emit(queue, "stage", {
            "message": "Stage 2: Running Research Agents...",
            "stage": "research_agents",
            "total": len(self.research_agents),
        })
        research_signals = await self._run_research_agents_sse(queue, trigger_time, data_factors)
        await self._emit(queue, "stage_complete", {
            "message": f"Research Agents completed: {len(research_signals)} signals",
            "stage": "research_agents",
            "count": len(research_signals),
        })

        await self._emit(queue, "stage", {"message": "Stage 3: Selecting best signals...", "stage": "selection"})
        best_signals = self._select_best_signals(research_signals)
        await self._emit(queue, "stage_complete", {
            "message": f"Best signal selection completed: {len(best_signals)} signals",
            "stage": "selection",
            "count": len(best_signals),
        })

        result = {
            "trigger_time": trigger_time,
            "data_factors": data_factors,
            "research_signals": research_signals,
            "best_signals": best_signals,
        }
        await self._emit(queue, "complete", {
            "message": "Analysis Complete",
            "data_factors_count": len(data_factors),
            "research_signals_count": len(research_signals),
            "best_signals_count": len(best_signals),
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


@app.post("/api/start")
async def start_analysis(body: StartRequest):
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    streams[session_id] = queue
    trigger_time = body.trigger_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    asyncio.create_task(company.run_with_queue(queue, trigger_time))
    return {"session_id": session_id}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
