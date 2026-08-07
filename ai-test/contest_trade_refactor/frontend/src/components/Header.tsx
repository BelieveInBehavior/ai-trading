interface HeaderProps {
  connected: boolean;
  agentCounts: { data: number; research: number } | null;
}

export default function Header({ connected, agentCounts }: HeaderProps) {
  return (
    <header
      style={{
        background: "linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)",
        color: "white",
        padding: "0 1.5rem",
        height: 64,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        boxShadow: "0 2px 12px rgba(0,0,0,0.15)",
        flexShrink: 0,
        gap: "1rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "0.875rem" }}>
        <span style={{ fontSize: "1.75rem", lineHeight: 1 }}>📈</span>
        <div>
          <div style={{ fontWeight: 700, fontSize: "1.1rem", letterSpacing: "-0.01em" }}>
            AI Trading System
          </div>
          <div style={{ fontSize: "0.72rem", opacity: 0.75, marginTop: 1 }}>
            Real-time Market Analysis
          </div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "1.5rem" }}>
        {agentCounts && (
          <div style={{ display: "flex", gap: "1rem", fontSize: "0.78rem", opacity: 0.9 }}>
            <span>Data agents: <strong>{agentCounts.data}</strong></span>
            <span>Research agents: <strong>{agentCounts.research}</strong></span>
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.82rem" }}>
          <span
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: connected ? "#4ade80" : "#f87171",
              boxShadow: connected ? "0 0 0 3px rgba(74,222,128,0.3)" : "none",
              animation: connected ? "pulse 2s infinite" : "none",
            }}
          />
          <span>{connected ? "Streaming" : "Idle"}</span>
        </div>
      </div>
    </header>
  );
}
