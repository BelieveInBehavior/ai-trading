export type AgentType = "data" | "research";

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

export interface Signal {
  symbol_name?: string;
  symbol_code?: string;
  action?: string;
  probability?: string | number;
  evidence_list?: unknown[];
  agent_id?: number;
  agent_name?: string;
  signal_index?: number;
}

export interface AnalysisResult {
  trigger_time: string;
  data_factors: DataFactor[];
  research_signals: Signal[];
  best_signals: Signal[];
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
