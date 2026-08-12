import type { AnalysisResult, Signal, StepResult } from "@/types/trading";

interface ResultsPanelProps {
  result: AnalysisResult | null;
  stepResults: StepResult[];
  running: boolean;
}

function StatCard({
  value,
  label,
  color,
}: {
  value: number;
  label: string;
  color: string;
}) {
  return (
    <div
      style={{
        background: "#f8fafc",
        borderRadius: "0.625rem",
        padding: "0.875rem 1rem",
        borderLeft: `3px solid ${color}`,
        textAlign: "center",
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

function SignalRow({ signal }: { signal: Signal }) {
  const action = signal.action?.toLowerCase() ?? "";
  const decision = signal.buy_decision?.toLowerCase() ?? "";
  const badge = signal.buy_decision
    ? signal.buy_decision.toUpperCase()
    : signal.action;
  const isBuy = decision === "buy" || (!decision && action.includes("buy"));
  const isSell = !decision && action.includes("sell");
  const failedReasons = signal.next_day_gate_report?.failed_reasons ?? [];

  return (
    <div
      style={{
        background: "white",
        border: "1px solid #e2e8f0",
        borderRadius: "0.625rem",
        padding: "0.8rem 1rem",
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = "#2563eb";
        (e.currentTarget as HTMLElement).style.boxShadow =
          "0 2px 8px rgba(37,99,235,0.1)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = "#e2e8f0";
        (e.currentTarget as HTMLElement).style.boxShadow = "none";
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "0.3rem",
        }}
      >
        <div>
          <span style={{ fontWeight: 600, fontSize: "0.9rem" }}>
            {signal.symbol_name ?? "N/A"}
          </span>
          {signal.symbol_code && (
            <span style={{ marginLeft: "0.4rem", color: "#64748b", fontSize: "0.78rem" }}>
              ({signal.symbol_code})
            </span>
          )}
        </div>
        {badge && (
          <span
            style={{
              padding: "0.18rem 0.6rem",
              borderRadius: "0.3rem",
              fontSize: "0.75rem",
              fontWeight: 700,
              background: isBuy ? "#d1fae5" : isSell ? "#fee2e2" : "#f1f5f9",
              color: isBuy ? "#065f46" : isSell ? "#991b1b" : "#475569",
            }}
          >
            {badge}
          </span>
        )}
      </div>
      <div style={{ fontSize: "0.75rem", color: "#94a3b8", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        {signal.agent_name && <span>Agent: {signal.agent_name}</span>}
        {signal.buy_score != null && <span>Score: {signal.buy_score}</span>}
        {signal.probability_value != null && <span>Probability: {signal.probability_value}</span>}
        {signal.probability_value == null && signal.probability != null && <span>Probability: {signal.probability}</span>}
        {signal.expected_return_t1_pct != null && <span>T+1: {signal.expected_return_t1_pct}%</span>}
        {signal.evidence_list != null && (
          <span>Evidence: {signal.evidence_list.length} items</span>
        )}
        {failedReasons.length > 0 && <span>Failed: {failedReasons.join(", ")}</span>}
      </div>
    </div>
  );
}

export default function ResultsPanel({ result, stepResults, running }: ResultsPanelProps) {
  const buySignals = result
    ? result.buy_signals ?? result.best_signals.filter((signal) => signal.buy_decision?.toLowerCase() === "buy")
    : [];
  const watchlist = result
    ? result.watchlist ?? result.best_signals.filter((signal) => signal.buy_decision?.toLowerCase() !== "buy")
    : [];

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      minHeight: 0,
      minWidth: 0,
      overflow: "hidden",
      background: "white",
    }}>
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
        }}
      >
        <div>
          <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>Analysis Results</div>
          <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: 2 }}>
            Trading signals and market insights
          </div>
        </div>
        {running && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              fontSize: "0.78rem",
              color: "#2563eb",
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: 11,
                height: 11,
                border: "2px solid #bfdbfe",
                borderTopColor: "#2563eb",
                borderRadius: "50%",
                animation: "spin 0.7s linear infinite",
              }}
            />
            Analyzing...
          </div>
        )}
      </div>

      {/* content */}
      <div style={{
        flex: "1 1 0",
        minHeight: 0,
        overflowX: "hidden",
        overflowY: "auto",
        overscrollBehavior: "contain",
        WebkitOverflowScrolling: "touch",
        padding: "1.25rem",
      }}>
        {!result && stepResults.length === 0 ? (
          <div style={{ textAlign: "center", color: "#94a3b8", paddingTop: "4rem" }}>
            <div style={{ fontSize: "3rem", marginBottom: "1rem", opacity: 0.35 }}>📊</div>
            <div style={{ fontSize: "0.875rem" }}>
              No results yet. Start an analysis to see trading signals.
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
            {stepResults.length > 0 && (
              <section
                style={{
                  background: "white",
                  border: "1px solid #e2e8f0",
                  borderRadius: "0.75rem",
                  padding: "1.25rem",
                  boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: "1rem", fontSize: "0.9rem" }}>
                  Step Results ({stepResults.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
                  {stepResults.map((step) => {
                    const color = step.status === "complete" ? "#10b981" : step.status === "error" ? "#ef4444" : "#2563eb";
                    return (
                      <div key={step.key} style={{ borderLeft: `3px solid ${color}`, background: "#f8fafc", borderRadius: "0.5rem", padding: "0.75rem 0.9rem" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                          <span style={{ fontWeight: 600, fontSize: "0.82rem" }}>{step.title}</span>
                          <span style={{ color, fontSize: "0.7rem", textTransform: "capitalize" }}>{step.status}</span>
                        </div>
                        <div style={{ color: "#64748b", fontSize: "0.75rem", lineHeight: 1.5, marginTop: "0.3rem", whiteSpace: "pre-wrap", maxHeight: "10rem", overflowY: "auto" }}>
                          {step.detail}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {result && (<>
            {/* stats */}
            <section
              style={{
                background: "white",
                border: "1px solid #e2e8f0",
                borderRadius: "0.75rem",
                padding: "1.25rem",
                boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: "1rem", fontSize: "0.9rem" }}>
                Summary
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(7rem, 1fr))",
                  gap: "0.75rem",
                }}
              >
                <StatCard value={result.data_factors.length} label="Data Factors" color="#2563eb" />
                <StatCard value={result.research_signals.length} label="Research Signals" color="#10b981" />
                <StatCard value={buySignals.length} label="Buy Signals" color="#10b981" />
                <StatCard value={watchlist.length} label="Watchlist" color="#f59e0b" />
              </div>
            </section>

            {/* signals */}
            {buySignals.length > 0 && (
              <section
                style={{
                  background: "white",
                  border: "1px solid #e2e8f0",
                  borderRadius: "0.75rem",
                  padding: "1.25rem",
                  boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: "1rem", fontSize: "0.9rem" }}>
                  Buy Signals ({buySignals.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
                  {buySignals.map((signal, i) => (
                    <SignalRow key={i} signal={signal} />
                  ))}
                </div>
              </section>
            )}

            {watchlist.length > 0 && (
              <section
                style={{
                  background: "white",
                  border: "1px solid #e2e8f0",
                  borderRadius: "0.75rem",
                  padding: "1.25rem",
                  boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: "1rem", fontSize: "0.9rem" }}>
                  Watchlist ({watchlist.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
                  {watchlist.map((signal, i) => (
                    <SignalRow key={i} signal={signal} />
                  ))}
                </div>
              </section>
            )}

            {/* Results stream in here as soon as each agent completes. */}
            {result.data_factors.length > 0 && (
              <section
                style={{
                  background: "white",
                  border: "1px solid #e2e8f0",
                  borderRadius: "0.75rem",
                  padding: "1.25rem",
                  boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: "1rem", fontSize: "0.9rem" }}>
                  Data Agent Results ({result.data_factors.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                  {result.data_factors.map((factor, i) => (
                    <div
                      key={`${factor.agent_name ?? "data"}-${i}`}
                      style={{
                        border: "1px solid #e2e8f0",
                        borderRadius: "0.625rem",
                        padding: "0.9rem 1rem",
                      }}
                    >
                      <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: "0.5rem" }}>
                        {factor.agent_name ?? `Data Agent ${i + 1}`}
                        {factor.source_name && (
                          <span style={{ color: "#64748b", fontWeight: 400 }}>
                            {` · ${factor.source_name}`}
                          </span>
                        )}
                        {factor.partial && (
                          <span style={{ marginLeft: "0.5rem", color: "#2563eb", fontSize: "0.72rem" }}>
                            Processing...
                          </span>
                        )}
                      </div>
                      <div style={{
                        color: "#475569",
                        fontSize: "0.78rem",
                        lineHeight: 1.6,
                        whiteSpace: "pre-wrap",
                        maxHeight: "16rem",
                        overflowY: "auto",
                      }}>
                        {factor.context_string || "Completed without a text summary."}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {result.research_signals.length > 0 && (
              <section
                style={{
                  background: "white",
                  border: "1px solid #e2e8f0",
                  borderRadius: "0.75rem",
                  padding: "1.25rem",
                  boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: "1rem", fontSize: "0.9rem" }}>
                  Research Agent Results ({result.research_signals.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
                  {result.research_signals.map((signal, i) => (
                    <SignalRow key={`${signal.agent_id ?? "research"}-${signal.signal_index ?? i}`} signal={signal} />
                  ))}
                </div>
              </section>
            )}

            <div style={{ fontSize: "0.72rem", color: "#94a3b8", textAlign: "right" }}>
              Analysis at: {result.trigger_time}
            </div>
            </>)}
          </div>
        )}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
