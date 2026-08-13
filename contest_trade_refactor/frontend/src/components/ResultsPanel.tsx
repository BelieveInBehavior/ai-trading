"use client";

import { useState } from "react";
import type {
  AnalysisResult,
  EvidenceRecord,
  MarketContext,
  Signal,
  StepResult,
  SystemHealth,
} from "@/types/trading";

interface ResultsPanelProps {
  result: AnalysisResult | null;
  analysisHistory: AnalysisResult[];
  stepResults: StepResult[];
  running: boolean;
}

type TabId = "current" | "history";

const card: React.CSSProperties = {
  background: "white",
  border: "1px solid #e2e8f0",
  borderRadius: "0.75rem",
  padding: "1.1rem 1.25rem",
  boxShadow: "0 1px 4px rgba(0, 0, 0, 0.05)",
};

function SectionTitle({ title, count }: { title: string; count?: number }) {
  return (
    <div style={{ fontWeight: 600, fontSize: "0.92rem", marginBottom: "0.75rem" }}>
      {title}
      {count != null && (
        <span style={{ color: "#64748b", fontWeight: 400, marginLeft: "0.35rem" }}>
          ({count})
        </span>
      )}
    </div>
  );
}

function twoDec(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(2);
}

function toPercent(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n <= 1 && n >= 0) return `${Math.round(n * 100)}%`;
  return `${Math.round(n)}%`;
}

function getEvidenceList(signal: Signal): EvidenceRecord[] {
  if (!signal.evidence_list || !Array.isArray(signal.evidence_list)) return [];
  return signal.evidence_list as EvidenceRecord[];
}

function getRiskFlags(signal: Signal): string[] {
  if (Array.isArray(signal.risk_flags) && signal.risk_flags.length) {
    return signal.risk_flags.filter(Boolean) as string[];
  }
  if (Array.isArray(signal.limitations) && signal.limitations.length) {
    return (signal.limitations as string[]).slice(0, 4);
  }
  return [];
}

function getFailedReasons(signal: Signal): string[] {
  return signal.next_day_gate_report?.failed_reasons ?? [];
}

function StatCard({ value, label, color }: { value: number | string; label: string; color: string }) {
  return (
    <div
      style={{
        background: "#f8fafc",
        borderRadius: "0.625rem",
        padding: "0.875rem 1rem",
        borderLeft: `3px solid ${color}`,
        textAlign: "center",
        minWidth: "6.5rem",
      }}
    >
      <div style={{ fontSize: "1.75rem", fontWeight: 700, color, lineHeight: 1.1 }}>
        {value}
      </div>
      <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.3rem" }}>
        {label}
      </div>
    </div>
  );
}

function riskSentimentMeta(sentiment?: string): { label: string; color: string; bg: string } {
  const s = (sentiment ?? "neutral").toLowerCase();
  if (s.includes("risk_on")) return { label: "Risk On 偏多", color: "#065f46", bg: "#d1fae5" };
  if (s.includes("risk_off")) return { label: "Risk Off 避险", color: "#991b1b", bg: "#fee2e2" };
  return { label: "Neutral 中性", color: "#92400e", bg: "#fef3c7" };
}

function MetricBar({
  label,
  value,
  display,
  color,
  max = 1,
}: {
  label: string;
  value: unknown;
  display?: string;
  color?: string;
  max?: number;
}) {
  const numeric = Number(value);
  const safe = Number.isFinite(numeric) ? Math.max(0, Math.min(max, numeric)) : 0;
  const width = `${Math.min(100, Math.round((safe / max) * 100))}%`;
  return (
    <div style={{ flex: 1, minWidth: "7rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "0.72rem",
          color: "#64748b",
          marginBottom: "0.2rem",
        }}
      >
        <span>{label}</span>
        <span style={{ fontWeight: 600, color: "#475569" }}>{display ?? twoDec(numeric)}</span>
      </div>
      <div style={{ height: 6, background: "#e2e8f0", borderRadius: 99, overflow: "hidden" }}>
        <div
          style={{
            height: "100%",
            width,
            background: color ?? "#2563eb",
            borderRadius: "inherit",
            transition: "width 0.3s",
          }}
        />
      </div>
    </div>
  );
}

function SignalCard({ signal, defaultExpanded = false }: { signal: Signal; defaultExpanded?: boolean }) {
  const [open, setOpen] = useState(defaultExpanded);
  const evidence = getEvidenceList(signal);
  const risks = getRiskFlags(signal);
  const failedReasons = getFailedReasons(signal);
  const decisionText = (signal.buy_decision ?? signal.action ?? "").toLowerCase();
  const isBuy =
    decisionText.includes("buy") ||
    (signal.buy_score != null && !Number.isNaN(Number(signal.buy_score)) && Number(signal.buy_score) >= 60);
  const badgeText = (signal.buy_decision ? signal.buy_decision : signal.action ?? "SIGNAL").toUpperCase();
  const probability =
    signal.probability_value != null
      ? signal.probability_value
      : signal.probability != null
        ? signal.probability
        : NaN;

  return (
    <div
      style={{
        background: "white",
        border: `1px solid ${isBuy ? "#bbf7d0" : "#fde68a"}`,
        borderRadius: "0.7rem",
        padding: "0.85rem 1rem",
        boxShadow: "0 1px 5px rgba(0,0,0,0.06)",
      }}
    >
      {/* identity + badges */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
        <div style={{ minWidth: 0 }}>
          <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "#0f172a" }}>
            {signal.symbol_name ?? "N/A"}
          </span>
          {signal.symbol_code && (
            <span style={{ marginLeft: "0.4rem", color: "#64748b", fontSize: "0.75rem", fontWeight: 500 }}>
              {signal.symbol_code}
            </span>
          )}
          {signal.agent_name && (
            <span style={{ marginLeft: "0.5rem", fontSize: "0.7rem", color: "#94a3b8" }}>
              Agent: {signal.agent_name}
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
          <span
            style={{
              padding: "0.14rem 0.5rem",
              borderRadius: "0.3rem",
              fontSize: "0.72rem",
              fontWeight: 700,
              background: isBuy ? "#d1fae5" : "#fef3c7",
              color: isBuy ? "#065f46" : "#92400e",
            }}
          >
            {badgeText}
          </span>
          {signal.buy_score != null && (
            <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "#1e40af" }}>
              {twoDec(signal.buy_score)}
            </span>
          )}
        </div>
      </div>

      {/* metrics */}
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
        <MetricBar label="Prob" value={probability} display={toPercent(probability)} color={isBuy ? "#10b981" : "#f59e0b"} />
        <MetricBar
          label="T+1 预期"
          value={signal.expected_return_t1_pct}
          display={signal.expected_return_t1_pct != null ? `${twoDec(signal.expected_return_t1_pct)}%` : "—"}
          color="#2563eb"
          max={10}
        />
        {evidence.length > 0 && (
          <span style={{ fontSize: "0.72rem", color: "#94a3b8", alignSelf: "center" }}>
            Evidence: {evidence.length} 条
          </span>
        )}
      </div>

      {/* risks / gate */}
      {(failedReasons.length > 0 || risks.length > 0) && (
        <div style={{ marginTop: "0.55rem", display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          {failedReasons.length > 0 && (
            <div style={{ fontSize: "0.72rem", color: "#991b1b", background: "#fee2e2", padding: "0.35rem 0.6rem", borderRadius: "0.35rem" }}>
              <strong>Gate 未通过：</strong>
              {failedReasons.join("；")}
            </div>
          )}
          {risks.length > 0 && (
            <div style={{ fontSize: "0.72rem", color: "#92400e", background: "#fef3c7", padding: "0.35rem 0.6rem", borderRadius: "0.35rem" }}>
              <strong>风险：</strong>
              {risks.join("；")}
            </div>
          )}
        </div>
      )}

      {/* evidence expander */}
      {evidence.length > 0 && (
        <div style={{ marginTop: "0.5rem" }}>
          <button
            onClick={() => setOpen(!open)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "#2563eb",
              fontSize: "0.78rem",
              fontWeight: 600,
              padding: 0,
            }}
          >
            {open ? "收起证据 ▲" : "展开证据 ▼"}
          </button>
          {open && (
            <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
              {evidence.map((ev, i) => (
                <div
                  key={i}
                  style={{
                    fontSize: "0.75rem",
                    lineHeight: 1.5,
                    color: "#475569",
                    background: "#f8fafc",
                    borderRadius: "0.4rem",
                    padding: "0.5rem 0.7rem",
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{ev.description ?? "—"}</div>
                  {(ev.time || ev.from_source) && (
                    <div style={{ marginTop: "0.2rem", color: "#94a3b8", display: "flex", gap: "0.6rem" }}>
                      {ev.time && <span>🗓 {ev.time}</span>}
                      {ev.from_source && <span>📡 {ev.from_source}</span>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SummaryStatsSection({ result }: { result: AnalysisResult }) {
  return (
    <section style={card}>
      <SectionTitle title="执行摘要" />
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <StatCard value={result.data_factors.length ?? 0} label="Data Factors" color="#2563eb" />
        <StatCard value={result.research_signals.length ?? 0} label="Research" color="#10b981" />
        <StatCard value={result.buy_signals?.length ?? 0} label="Buy Signals" color="#059669" />
        <StatCard value={result.watchlist?.length ?? 0} label="Watchlist" color="#f59e0b" />
        {result.research_rounds != null && (
          <StatCard value={result.research_rounds} label="Research Rounds" color="#7c3aed" />
        )}
        {result.best_signals?.length != null && result.best_signals.length > 0 && (
          <StatCard value={result.best_signals.length} label="Best" color="#2563eb" />
        )}
      </div>
      <div style={{ marginTop: "0.6rem", fontSize: "0.72rem", color: "#94a3b8" }}>
        Trigger time: {result.trigger_time}
        {result.require_min_buys_met != null && (
          <span style={{ marginLeft: "0.5rem" }}>minBuys 达标: {result.require_min_buys_met ? "是" : "否"}</span>
        )}
        {result.strategy && (
          <span style={{ display: "block", marginTop: "0.3rem", color: "#1e40af", fontWeight: 600 }}>
            策略: {result.strategy.name} · {result.strategy.horizon ?? ""} · {result.strategy.style ?? ""}
            {result.strategy.risk_note && <span style={{ color: "#92400e", marginLeft: "0.4rem" }}>{result.strategy.risk_note}</span>}
          </span>
        )}
      </div>
    </section>
  );
}

function MarketContextStrip({ market, health }: { market?: MarketContext; health?: SystemHealth }) {
  const risk = riskSentimentMeta(market?.risk_sentiment);
  const warnings = Array.isArray(health?.warnings) ? (health!.warnings as string[]) : [];
  const toolErrors = Number(health?.tool_error_count ?? 0);
  const agentErrors = Number(health?.agent_error_count ?? 0);

  return (
    <section style={{ ...card, display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center" }}>
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "0.4rem",
          padding: "0.25rem 0.7rem",
          borderRadius: "0.4rem",
          background: risk.bg,
          color: risk.color,
          fontSize: "0.8rem",
          fontWeight: 600,
        }}
      >
        {risk.label}
      </div>
      <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
        Sector flow: {market?.has_sector_flow_data === false ? "不可用" : "可用"}
      </div>
      <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
        Tool errors: {toolErrors} · Agent errors: {agentErrors}
      </div>
      {warnings.length > 0 && (
        <div
          style={{
            fontSize: "0.72rem",
            color: "#92400e",
            background: "#fef3c7",
            padding: "0.3rem 0.6rem",
            borderRadius: "0.35rem",
            maxWidth: "100%",
          }}
        >
          {warnings.join("；")}
        </div>
      )}
    </section>
  );
}

function SignalSection({
  title,
  signals,
  accent,
}: {
  title: string;
  signals: Signal[];
  accent: "buy" | "watch";
}) {
  if (signals.length === 0) return null;
  return (
    <section style={{ ...card, borderTop: `3px solid ${accent === "buy" ? "#10b981" : "#f59e0b"}` }}>
      <SectionTitle title={title} count={signals.length} />
      <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
        {signals.map((signal, i) => (
          <SignalCard key={`${signal.symbol_code ?? ""}-${signal.agent_id ?? "sig"}-${i}`} signal={signal} />
        ))}
      </div>
    </section>
  );
}

function DataFactorSection({ result }: { result: AnalysisResult }) {
  if (!result.data_factors?.length) return null;
  return (
    <details style={{ ...card, marginTop: "0.75rem" }}>
      <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: "0.88rem", color: "#0f172a" }}>
        Data Agent Results ({result.data_factors.length})
      </summary>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem", marginTop: "0.75rem" }}>
        {result.data_factors.map((factor, i) => (
          <div
            key={`${factor.agent_name ?? "data"}-${i}`}
            style={{ border: "1px solid #eef2f7", borderRadius: "0.5rem", padding: "0.6rem 0.8rem", background: "#f8fafc" }}
          >
            <div style={{ fontWeight: 600, fontSize: "0.8rem", marginBottom: "0.25rem" }}>
              {factor.agent_name ?? `Data Agent ${i + 1}`}
              {factor.source_name && <span style={{ color: "#64748b", fontWeight: 400 }}> · {factor.source_name}</span>}
              {factor.partial && <span style={{ color: "#2563eb", fontSize: "0.7rem", marginLeft: "0.4rem" }}>Processing…</span>}
            </div>
            <div style={{ color: "#475569", fontSize: "0.74rem", lineHeight: 1.5, whiteSpace: "pre-wrap", maxHeight: "12rem", overflowY: "auto" }}>
              {factor.context_string || "Completed without a text summary."}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

function ResearchSignalsSection({ result }: { result: AnalysisResult }) {
  if (!result.research_signals?.length) return null;
  return (
    <details style={{ ...card, marginTop: "0.75rem" }}>
      <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: "0.88rem", color: "#0f172a" }}>
        Research Signals ({result.research_signals.length})
      </summary>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem", marginTop: "0.75rem" }}>
        {result.research_signals.map((signal, i) => (
          <SignalCard
            key={`${signal.agent_id ?? "research"}-${signal.signal_index ?? i}`}
            signal={signal}
            defaultExpanded={false}
          />
        ))}
      </div>
    </details>
  );
}

function CurrentResultPanel({
  result,
  stepResults,
  running,
}: {
  result: AnalysisResult;
  stepResults: StepResult[];
  running: boolean;
}) {
  const buySignals = result.buy_signals?.length
    ? result.buy_signals
    : result.best_signals.filter((s) => (s.buy_decision ?? "").toLowerCase() === "buy");
  const watchlist = result.watchlist?.length
    ? result.watchlist
    : result.best_signals.filter((s) => (s.buy_decision ?? "").toLowerCase() !== "buy");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem", padding: "1.25rem", overflowY: "auto" }}>
      <SummaryStatsSection result={result} />
      <MarketContextStrip market={result.market_context} health={result.system_health} />
      <SignalSection title="买入信号 Buy" signals={buySignals} accent="buy" />
      <SignalSection title="观察池 Watchlist" signals={watchlist} accent="watch" />
      <DataFactorSection result={result} />
      <ResearchSignalsSection result={result} />

      {stepResults.length > 0 && (
        <details style={card}>
          <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: "0.88rem", color: "#0f172a" }}>
            Pipeline 步骤 ({stepResults.length})
          </summary>
          <div style={{ marginTop: "0.75rem", display: "flex", flexDirection: "column", gap: "0.55rem" }}>
            {stepResults.map((step) => {
              const color = step.status === "complete" ? "#10b981" : step.status === "error" ? "#ef4444" : "#2563eb";
              return (
                <div
                  key={step.key}
                  style={{ borderLeft: `3px solid ${color}`, background: "#f8fafc", borderRadius: "0.45rem", padding: "0.55rem 0.7rem" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "0.6rem" }}>
                    <span style={{ fontWeight: 600, fontSize: "0.8rem" }}>{step.title}</span>
                    <span style={{ color, fontSize: "0.68rem", textTransform: "capitalize" }}>{step.status}</span>
                  </div>
                  <div style={{ color: "#64748b", fontSize: "0.72rem", marginTop: "0.2rem", whiteSpace: "pre-wrap", maxHeight: "8rem", overflowY: "auto" }}>
                    {step.detail}
                  </div>
                </div>
              );
            })}
          </div>
        </details>
      )}
    </div>
  );
}

function HistoryPanel({ history }: { history: AnalysisResult[] }) {
  if (history.length === 0) {
    return (
      <div style={{ padding: "2rem", textAlign: "center", color: "#94a3b8", fontSize: "0.85rem" }}>
        还没有历史分析记录。完成一次分析后会显示在这里。
      </div>
    );
  }

  const sorted = [...history].reverse();
  return (
    <div style={{ padding: "1.25rem", display: "flex", flexDirection: "column", gap: "1rem", overflowY: "auto" }}>
      {sorted.map((item, idx) => {
        const buys = item.buy_signals?.length ?? 0;
        const watch = item.watchlist?.length ?? 0;
        const research = item.research_signals?.length ?? 0;
        const sentiment = item.market_context?.risk_sentiment ?? "—";
        return (
          <section key={`${item.trigger_time}-${history.length - idx}`} style={card}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", marginBottom: "0.4rem", flexWrap: "wrap" }}>
              <span style={{ fontWeight: 700, fontSize: "0.9rem" }}>
                #{history.length - idx} · {item.trigger_time || "unknown time"}
              </span>
              <span style={{ fontSize: "0.72rem", color: "#64748b" }}>sentiment: {sentimentLabel(sentiment)}</span>
            </div>
            <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", fontSize: "0.75rem", color: "#475569" }}>
              <span>Buy {buys}</span>
              <span>Watch {watch}</span>
              <span>Research {research}</span>
              <span>Data {item.data_factors?.length ?? 0}</span>
              {item.research_rounds != null && <span>Rounds {item.research_rounds}</span>}
            </div>
            <div style={{ marginTop: "0.55rem" }}>
              {(item.buy_signals?.length ? item.buy_signals : item.best_signals ?? [])
                .slice(0, 5)
                .map((s, i) => (
                  <div
                    key={i}
                    style={{ fontSize: "0.76rem", color: "#334155", display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.2rem" }}
                  >
                    <span style={{ fontWeight: 600 }}>{s.symbol_name ?? "—"}</span>
                    {s.symbol_code && <span style={{ color: "#64748b" }}>{s.symbol_code}</span>}
                    {s.buy_decision && (
                      <span style={{ color: s.buy_decision.toLowerCase() === "buy" ? "#059669" : "#b45309", fontWeight: 700 }}>
                        {s.buy_decision.toUpperCase()}
                      </span>
                    )}
                    {s.buy_score != null && <span style={{ color: "#1e40af" }}>{twoDec(s.buy_score)}</span>}
                  </div>
                ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function sentimentLabel(sentiment?: string): string {
  const s = (sentiment ?? "").toLowerCase();
  if (s.includes("risk_on")) return "Risk On";
  if (s.includes("risk_off")) return "Risk Off";
  return s || "Neutral";
}

export default function ResultsPanel({ result, analysisHistory, stepResults, running }: ResultsPanelProps) {
  const [tab, setTab] = useState<TabId>("current");

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        minWidth: 0,
        overflow: "hidden",
        background: "white",
      }}
    >
      {/* header */}
      <div
        style={{
          padding: "0.875rem 1.25rem",
          borderBottom: "1px solid #e2e8f0",
          background: "#f8fafc",
          display: "flex",
          flexShrink: 0,
          justifyContent: "space-between",
          alignItems: "center",
          gap: "0.6rem",
        }}
      >
        <div>
          <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>Trading Decision Board</div>
          <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: 2 }}>Buy / Watchlist / Evidence</div>
        </div>
        <div style={{ display: "flex", gap: "0.25rem" }}>
          <button
            onClick={() => setTab("current")}
            style={{
              padding: "0.3rem 0.7rem",
              borderRadius: "0.45rem",
              border: "1px solid #e2e8f0",
              background: tab === "current" ? "#2563eb" : "white",
              color: tab === "current" ? "white" : "#475569",
              cursor: "pointer",
              fontSize: "0.75rem",
              fontWeight: 600,
            }}
          >
            {running ? "本次(Running)" : "本次结果"}
          </button>
          <button
            onClick={() => setTab("history")}
            style={{
              padding: "0.3rem 0.7rem",
              borderRadius: "0.45rem",
              border: "1px solid #e2e8f0",
              background: tab === "history" ? "#2563eb" : "white",
              color: tab === "history" ? "white" : "#475569",
              cursor: "pointer",
              fontSize: "0.75rem",
              fontWeight: 600,
            }}
          >
            历史 ({analysisHistory.length})
          </button>
        </div>
      </div>

      {tab === "current" ? (
        result ? (
          <CurrentResultPanel result={result} stepResults={stepResults} running={running} />
        ) : (
          <div style={{ textAlign: "center", color: "#94a3b8", paddingTop: "5rem" }}>
            <div style={{ fontSize: "3.5rem", marginBottom: "1rem", opacity: 0.3 }}>📊</div>
            <div style={{ fontSize: "0.9rem" }}>
              {running ? "正在分析，结果会实时出现在这里…" : "还没有结果。点击左侧 Start Analysis 开始。"}
            </div>
          </div>
        )
      ) : (
        <HistoryPanel history={analysisHistory} />
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
