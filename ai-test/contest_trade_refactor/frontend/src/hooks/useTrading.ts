"use client";

import { useState, useCallback, useRef } from "react";
import type { ChatMessage, AnalysisResult, SseEvent, StepResult } from "@/types/trading";

let seq = 0;
const uid = () => String(++seq);

/**
 * Builds a stable key for upserting agent status messages in chat.
 * @generated AI Assistant - 2026-08-07 15:40:00
 */
function buildAgentKey(agentType: string, agentId: unknown): string {
  return `${agentType}_${String(agentId ?? "unknown")}`;
}

export function useTrading() {
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: uid(),
      role: "system",
      text: "Welcome to AI Trading System. Click Start Analysis to begin.",
      timestamp: new Date(),
    },
  ]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [stepResults, setStepResults] = useState<StepResult[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const streamFinishedRef = useRef(false);

  const push = useCallback((msg: Omit<ChatMessage, "id" | "timestamp">) => {
    setMessages((prev) => [...prev, { ...msg, id: uid(), timestamp: new Date() }]);
  }, []);

  const upsertStepResult = useCallback((step: StepResult) => {
    setStepResults((previous) => {
      const index = previous.findIndex((item) => item.key === step.key);
      if (index < 0) return [...previous, step];
      const updated = [...previous];
      updated[index] = step;
      return updated;
    });
  }, []);

  /**
   * Upserts an agent message so start/complete/error update the same bubble.
   * @generated AI Assistant - 2026-08-07 15:40:00
   */
  const upsertAgentMessage = useCallback(
    (agentKey: string, msg: Omit<ChatMessage, "id" | "timestamp" | "agentKey">) => {
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.agentKey === agentKey);
        if (idx >= 0) {
          const updated = [...prev];
          updated[idx] = {
            ...updated[idx],
            ...msg,
            agentKey,
            timestamp: new Date(),
          };
          return updated;
        }
        return [...prev, { ...msg, id: uid(), agentKey, timestamp: new Date() }];
      });
    },
    []
  );

  /**
   * Closes SSE connection and resets running state.
   * @generated AI Assistant - 2026-08-07 15:40:00
   */
  const closeStream = useCallback((finished: boolean) => {
    streamFinishedRef.current = finished;
    esRef.current?.close();
    esRef.current = null;
    setRunning(false);
    setConnected(false);
  }, []);

  const startAnalysis = useCallback(
    async (triggerTime?: string) => {
      if (running) return;
      setRunning(true);
      setResult(null);
      setStepResults([]);
      streamFinishedRef.current = false;

      push({ role: "user", text: `Start analysis at ${triggerTime || "now"}` });

      const res = await fetch("/api/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger_time: triggerTime ?? "" }),
      });

      if (!res.ok) {
        push({ role: "system", text: "Failed to start analysis." });
        setRunning(false);
        return;
      }

      const { session_id } = await res.json();

      esRef.current?.close();
      const es = new EventSource(`/api/stream/${session_id}`);
      esRef.current = es;
      setConnected(true);

      es.onopen = () => {
        setConnected(true);
      };

      es.onmessage = (ev) => {
        const event: SseEvent = JSON.parse(ev.data);
        const { type, data } = event;
        const timestamp = event.timestamp ?? new Date().toISOString();

        switch (type) {
          case "system":
            push({ role: "system", text: String(data.message ?? "") });
            upsertStepResult({
              key: `system:${String(data.stage ?? "init")}`,
              title: "Analysis initialized",
              detail: String(data.message ?? ""),
              status: "running",
              timestamp,
            });
            break;

          case "stage":
            push({ role: "system", text: String(data.message ?? "") });
            upsertStepResult({
              key: `stage:${String(data.stage ?? "unknown")}`,
              title: String(data.message ?? "Processing"),
              detail: data.total != null ? `${String(data.total)} agents` : "Processing...",
              status: "running",
              timestamp,
            });
            break;

          case "stage_complete":
            push({ role: "system", text: String(data.message ?? "") });
            upsertStepResult({
              key: `stage:${String(data.stage ?? "unknown")}`,
              title: String(data.stage ?? "Stage").replaceAll("_", " "),
              detail: String(data.message ?? "Completed"),
              status: "complete",
              timestamp,
            });
            break;

          case "complete":
            push({ role: "system", text: String(data.message ?? "") });
            upsertStepResult({
              key: "analysis:complete",
              title: "Analysis workflow completed",
              detail: `${String(data.data_factors_count ?? 0)} data factors · ${String(data.research_signals_count ?? 0)} research signals · ${String(data.best_signals_count ?? 0)} best signals`,
              status: "complete",
              timestamp,
            });
            break;

          case "agent_start": {
            const agentType = data.agent_type as "data" | "research";
            const agentName = String(data.agent_name ?? "Agent");
            const agentKey = buildAgentKey(agentType, data.agent_id);
            upsertAgentMessage(agentKey, {
              role: "system",
              text: `${agentName} 开始工作`,
              agentType,
              agentName,
              agentStatus: "start",
            });
            upsertStepResult({
              key: `agent:${agentKey}`,
              title: agentName,
              detail: "Agent is working",
              status: "running",
              timestamp,
            });
            break;
          }

          case "agent_result": {
            const agentResult = data.result as AnalysisResult["data_factors"][number] | undefined;
            if (!agentResult) break;

            upsertStepResult({
              key: `source:${agentResult.agent_id ?? "unknown"}:${agentResult.source_name ?? "source"}`,
              title: `${agentResult.agent_name ?? "Data Agent"} · ${agentResult.source_name ?? "Data source"}`,
              detail: agentResult.context_string || "Content received",
              status: "complete",
              timestamp,
            });

            setResult((current) => {
              const next: AnalysisResult = current ?? {
                trigger_time: triggerTime || new Date().toLocaleString(),
                data_factors: [],
                research_signals: [],
                best_signals: [],
              };
              const resultKey = `${agentResult.agent_id ?? "unknown"}:${agentResult.source_name ?? "source"}`;
              const existingIndex = next.data_factors.findIndex(
                (factor) => `${factor.agent_id ?? "unknown"}:${factor.source_name ?? "source"}` === resultKey
              );
              const dataFactors = [...next.data_factors];
              if (existingIndex >= 0) dataFactors[existingIndex] = agentResult;
              else dataFactors.push(agentResult);
              return { ...next, data_factors: dataFactors };
            });
            break;
          }

          case "agent_complete": {
            const agentType = data.agent_type as "data" | "research";
            const agentName = String(data.agent_name ?? "Agent");
            const agentKey = buildAgentKey(agentType, data.agent_id);
            upsertAgentMessage(agentKey, {
              role: "system",
              text: `${agentName} 已完成`,
              agentType,
              agentName,
              agentStatus: "complete",
            });
            upsertStepResult({
              key: `agent:${agentKey}`,
              title: agentName,
              detail: agentType === "research"
                ? `${String(data.signals_count ?? 0)} signals produced`
                : "Final agent result produced",
              status: "complete",
              timestamp,
            });

            // Show this agent's output immediately; do not wait for the whole
            // workflow's final `result` event.
            setResult((current) => {
              const next: AnalysisResult = current ?? {
                trigger_time: triggerTime || new Date().toLocaleString(),
                data_factors: [],
                research_signals: [],
                best_signals: [],
              };
              const agentResult = data.result as Record<string, unknown> | undefined;

              if (agentType === "data" && agentResult) {
                const completedAgentId = agentResult.agent_id;
                return {
                  ...next,
                  data_factors: [
                    ...next.data_factors.filter(
                      (factor) => factor.agent_id !== completedAgentId
                    ),
                    agentResult,
                  ],
                };
              }

              if (agentType === "research" && agentResult) {
                const signals = Array.isArray(agentResult.signals)
                  ? (agentResult.signals as AnalysisResult["research_signals"])
                  : [];
                return {
                  ...next,
                  research_signals: [...next.research_signals, ...signals],
                };
              }

              return next;
            });
            break;
          }

          case "agent_error": {
            const agentType = data.agent_type as "data" | "research";
            const agentName = String(data.agent_name ?? "Agent");
            const agentKey = buildAgentKey(agentType, data.agent_id);
            upsertAgentMessage(agentKey, {
              role: "system",
              text: `${agentName} 执行失败：${String(data.message ?? "")}`,
              agentType,
              agentName,
              agentStatus: "error",
            });
            upsertStepResult({
              key: `agent:${agentKey}`,
              title: agentName,
              detail: String(data.message ?? "Agent failed"),
              status: "error",
              timestamp,
            });
            break;
          }

          case "result": {
            const finalResult = data.result as AnalysisResult;
            upsertStepResult({
              key: "result:final",
              title: "Final result",
              detail: `${finalResult.data_factors.length} data factors · ${finalResult.research_signals.length} research signals · ${finalResult.best_signals.length} best signals`,
              status: "complete",
              timestamp,
            });
            setResult(finalResult);
            push({ role: "system", text: "分析完成，结果已更新。" });
            closeStream(true);
            break;
          }

          case "stream_end":
            closeStream(true);
            break;

          case "error":
            push({ role: "system", text: String(data.message ?? "Error occurred") });
            closeStream(true);
            break;
        }
      };

      es.onerror = () => {
        if (streamFinishedRef.current) {
          esRef.current = null;
          return;
        }
        // EventSource reconnects automatically. Keep the analysis running and
        // retain the session instead of turning a temporary proxy reset into
        // a permanent failure.
        setConnected(false);
      };
    },
    [running, push, upsertAgentMessage, upsertStepResult, closeStream]
  );

  return { connected, running, messages, result, stepResults, startAnalysis };
}
