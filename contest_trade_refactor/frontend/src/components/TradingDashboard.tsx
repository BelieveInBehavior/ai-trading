"use client";
import { useState } from "react";

import Header from "@/components/Header";
import ChatPanel from "@/components/ChatPanel";
import ResultsPanel from "@/components/ResultsPanel";
import { useTrading } from "@/hooks/useTrading";
import type { HealthStatus, StrategyId, SystemStatus } from "@/types/trading";

interface TradingDashboardProps {
  initialHealth: HealthStatus | null;
  initialStatus: SystemStatus | null;
}

export default function TradingDashboard({
  initialHealth,
}: TradingDashboardProps) {
  const { connected, running, messages, result, analysisHistory, stepResults, startAnalysis, strategies } = useTrading();
  const [strategy, setStrategy] = useState<StrategyId>("momentum");

  const agentCounts = initialHealth
    ? {
        data: initialHealth.agents.data_agents,
        research: initialHealth.agents.research_agents,
      }
    : null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
      }}
    >
      <Header connected={connected} agentCounts={agentCounts} />

      <div
        style={{
          flex: 1,
          display: "grid",
          gridTemplateColumns: "44% 1fr",
          gap: "1px",
          background: "#e2e8f0",
          overflow: "hidden",
          minHeight: 0,
        }}
      >
        <ChatPanel
          messages={messages}
          running={running}
          strategy={strategy}
          strategies={strategies}
          onStrategyChange={setStrategy}
          onStart={startAnalysis}
        />
        <ResultsPanel
          result={result}
          analysisHistory={analysisHistory}
          stepResults={stepResults}
          running={running}
        />
      </div>
    </div>
  );
}
