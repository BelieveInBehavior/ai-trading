export type AgentType = "data" | "research";

export type StrategyId = "swing" | "momentum";

export interface StrategyInfo {
  id: StrategyId;
  name: string;
  short_name?: string;
  description?: string;
  horizon?: string;
  style?: string;
  risk_note?: string;
  tags?: string[];
}

export type MessageKind =
  | "system"
  | "stage"
  | "stage_complete"
  | "agent_start"
  | "agent_result"
  | "agent_complete"
  | "agent_error"
  | "complete"
  | "result"
  | "stream_end"
  | "error";

export interface SseEvent {
  type: MessageKind;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface EvidenceRecord {
  description?: string;
  time?: string;
  from_source?: string;
  [key: string]: unknown;
}

export interface NextDayGateReport {
  passed?: boolean;
  failed_reasons?: string[];
  [key: string]: unknown;
}

export interface Signal {
  symbol_name?: string;
  symbol_code?: string;
  action?: string;
  buy_decision?: string;
  buy_score?: number;
  probability_value?: number;
  expected_return_t1_pct?: number;
  next_day_gate_report?: NextDayGateReport;
  probability?: string | number;
  evidence_list?: EvidenceRecord[] | unknown[];
  risk_flags?: string[];
  limitations?: string[];
  agent_id?: number;
  agent_name?: string;
  signal_index?: number;
  [key: string]: unknown;
}

export interface MarketContext {
  risk_sentiment?: string;
  has_sector_flow_data?: boolean;
  [key: string]: unknown;
}

export interface SystemHealth {
  tool_error_count?: number;
  agent_error_count?: number;
  warnings?: string[];
  [key: string]: unknown;
}

export interface AnalysisResult {
  trigger_time: string;
  strategy?: StrategyInfo;
  data_factors: DataFactor[];
  research_signals: Signal[];
  buy_signals?: Signal[];
  watchlist?: Signal[];
  best_signals: Signal[];
  market_context?: MarketContext;
  system_health?: SystemHealth;
  research_rounds?: number;
  require_min_buys?: number;
  require_min_buys_met?: boolean;
}

export interface DataFactor {
  agent_id?: number;
  agent_name?: string;
  source_name?: string;
  trigger_time?: string;
  context_string?: string;
  partial?: boolean;
}

export interface StepResult {
  key: string;
  title: string;
  detail: string;
  status: "running" | "complete" | "error";
  timestamp: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "system";
  text: string;
  agentType?: AgentType;
  agentName?: string;
  agentKey?: string;
  agentStatus?: "start" | "complete" | "error";
  timestamp: Date;
}

export interface HealthStatus {
  status: string;
  timestamp: string;
  agents: {
    data_agents: number;
    research_agents: number;
  };
}

export interface SystemStatus {
  server: string;
  version: string;
  timestamp: string;
  active_sessions: number;
}
