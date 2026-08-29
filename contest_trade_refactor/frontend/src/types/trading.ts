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

// ===== Main Trend following =====
export interface MtnCandidate {
  symbol_code?: string;
  symbol_name?: string;
  trade_date?: string;
  trend_state?: string;
  trend_grade?: string;
  trend_score?: number;
  sector_name?: string;
  sector_grade?: string;
  sector_score?: number;
  catalyst_grade?: string;
  catalyst_score?: number;
  pre_score?: number;
  theme?: string;
  reference_price?: number;
  entry_price?: number | null;
  initial_stop?: number;
  initial_stop_pct?: number;
  trailing_stop?: number;
  target_price_1?: number | null;
  target_price_2?: number | null;
  target_method?: string;
  current_stop?: number;
  ma20?: number | null;
  atr?: number;
  raw_position_pct?: number;
  t1_state?: string;
  action?: string;
  suggested_position_pct?: number;
  portfolio_state?: string;
}

export interface MtfT1Row extends MtnCandidate {
  final_score?: number;
  execution_grade?: string;
  gap_pct?: number;
  vwap_state?: string;
  bid_support?: string;
  reasons?: string[];
}

export interface MtfHolding {
  symbol_code?: string;
  symbol_name?: string;
  entry_date?: string;
  entry_price?: number;
  quantity?: number;
  holding_days?: number;
  highest_price?: number;
  highest_close?: number;
  current_price?: number | null;
  buy_score?: number;
  signal_tier?: string;
  high_volume_class?: string;
  high_volume_reason?: string;
  add_setup_class?: string;
  sector_source?: string;
  rs_source?: string;
  next_day_guard_break_vwap?: boolean;
  next_day_guard_vwap?: number | null;
  next_day_guard_high?: number | null;
  target_price_1?: number | null;
  target_price_2?: number | null;
  profit_protect_price?: number | null;
  profit_protect_level?: string;
  profit_protect_reason?: string;
  stop_loss_price?: number | null;
  atr_trailing_stop?: number | null;
  ma10?: number | null;
  ma20?: number | null;
  prev_ma20?: number | null;
  prev_close?: number | null;
  current_return_pct?: number;
  return_pct?: number | null;
  suggested_position_pct?: number;
  raw_position_pct?: number;
  exit_action?: string;
  exit_class?: string;
  exit_level?: string;
  exit_reason?: string;
  exit_reasons?: string[];
  trailing_stop_price?: number | null;
  reduce_pct?: number;
  position_state?: string;
  [key: string]: unknown;
}

export interface MtfExitDecision {
  symbol_code?: string;
  symbol_name?: string;
  action?: string;
  reason?: string;
  exit_level?: string;
  exit_class?: string;
  state?: string;
  position_state?: string;
  current_return_pct?: number;
  stop_loss_triggered?: boolean;
  reduce_triggered?: boolean;
  add_allowed?: boolean;
  add_setup?: boolean;
  add_confirmation?: boolean;
  add_setup_class?: string;
  add_signal?: string;
  add_size_pct?: number;
  add_reason?: string;
  reduce_pct?: number;
  trailing_stop_price?: number | null;
  target_price_1?: number | null;
  target_price_2?: number | null;
  profit_protect_price?: number | null;
  profit_protect_level?: string;
  profit_protect_reason?: string;
  high_volume_class?: string;
  high_volume_reason?: string;
  [key: string]: unknown;
}

export interface MtfDashboard {
  as_of_date?: string;
  generated_at?: string;
  tday_candidates?: {
    present?: boolean;
    trade_date?: string;
    count?: number;
    rows?: MtnCandidate[];
    themes?: Array<{ theme?: string; names?: number; gross_pct?: number; kept_pct?: number }>;
    path?: string;
  };
  t1_execution?: {
    present?: boolean;
    trade_date?: string;
    rows?: MtfT1Row[];
    index_change_pct?: number | null;
    path?: string;
  };
  holdings?: {
    present?: boolean;
    trade_date?: string;
    rows?: MtfHolding[];
    count?: number;
    last_run?: string;
    path?: string;
    phase?: string;
    wave?: string;
  };
  t2?: {
    present?: boolean;
    wave?: string;
    logged_at?: string;
    avg_return_pct?: number | null;
    counts?: Record<string, number>;
    path?: string;
  };
  exit_decisions?: {
    present?: boolean;
    as_of_date?: string;
    positions_count?: number;
    decisions?: MtfExitDecision[];
    path?: string;
  };
  requested_date?: string;
  requested_day_present?: boolean;
  available_dates?: string[];
}
