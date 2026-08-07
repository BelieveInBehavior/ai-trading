"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/types/trading";

interface ChatPanelProps {
  messages: ChatMessage[];
  running: boolean;
  onStart: (triggerTime?: string) => void;
}

const agentBadge: Record<string, { bg: string; color: string; label: string }> = {
  data: { bg: "#dbeafe", color: "#1e40af", label: "Data" },
  research: { bg: "#d1fae5", color: "#065f46", label: "Research" },
};

const statusConfig: Record<string, { icon: string; color: string }> = {
  start: { icon: "⟳", color: "#2563eb" },
  complete: { icon: "✓", color: "#059669" },
  error: { icon: "✗", color: "#dc2626" },
};

/**
 * Formats a Date as HH:MM:SS to avoid SSR/client locale mismatches.
 * @generated AI Assistant - 2026-08-07 14:51:00
 */
function formatMessageTime(date: Date): string {
  const hours = date.getHours().toString().padStart(2, "0");
  const minutes = date.getMinutes().toString().padStart(2, "0");
  const seconds = date.getSeconds().toString().padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  const badge = msg.agentType ? agentBadge[msg.agentType] : null;
  const status = msg.agentStatus ? statusConfig[msg.agentStatus] : null;
  const isAgentRunning = msg.agentStatus === "start";

  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        animation: "fadeSlide 0.22s ease-out",
      }}
    >
      <div style={{ maxWidth: "88%" }}>
        <div
          style={{
            padding: "0.55rem 0.9rem",
            borderRadius: isUser ? "1rem 1rem 0.2rem 1rem" : "1rem 1rem 1rem 0.2rem",
            background: isUser ? "#2563eb" : isAgentRunning ? "#f0f9ff" : "#ffffff",
            color: isUser ? "white" : "#0f172a",
            border: isUser ? "none" : isAgentRunning ? "1px solid #bae6fd" : "1px solid #e2e8f0",
            boxShadow: "0 1px 4px rgba(0,0,0,0.07)",
            fontSize: "0.85rem",
            lineHeight: 1.55,
          }}
        >
          {badge && (
            <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", marginBottom: "0.25rem" }}>
              <span
                style={{
                  display: "inline-block",
                  padding: "0.1rem 0.45rem",
                  borderRadius: "0.25rem",
                  fontSize: "0.7rem",
                  fontWeight: 700,
                  background: badge.bg,
                  color: badge.color,
                }}
              >
                {badge.label}
              </span>
              {msg.agentName && (
                <span
                  style={{
                    fontSize: "0.72rem",
                    fontWeight: 600,
                    color: "#475569",
                    fontFamily: "ui-monospace, monospace",
                  }}
                >
                  {msg.agentName}
                </span>
              )}
              {status && (
                <span
                  style={{
                    fontSize: "0.72rem",
                    fontWeight: 700,
                    color: status.color,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.2rem",
                  }}
                >
                  {isAgentRunning ? (
                    <span
                      style={{
                        display: "inline-block",
                        width: 10,
                        height: 10,
                        border: "2px solid #bfdbfe",
                        borderTopColor: status.color,
                        borderRadius: "50%",
                        animation: "spin 0.7s linear infinite",
                      }}
                    />
                  ) : (
                    status.icon
                  )}
                </span>
              )}
            </div>
          )}
          {msg.text}
        </div>
        <div
          style={{
            fontSize: "0.68rem",
            color: "#94a3b8",
            marginTop: "0.2rem",
            textAlign: isUser ? "right" : "left",
            paddingInline: "0.25rem",
          }}
        >
          {formatMessageTime(msg.timestamp)}
        </div>
      </div>
    </div>
  );
}

export default function ChatPanel({ messages, running, onStart }: ChatPanelProps) {
  const [triggerTime, setTriggerTime] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleStart = () => onStart(triggerTime || undefined);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "white" }}>
      {/* header */}
      <div
        style={{
          padding: "0.875rem 1.25rem",
          borderBottom: "1px solid #e2e8f0",
          background: "#f8fafc",
        }}
      >
        <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>Analysis Control</div>
        <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: 2 }}>
          Real-time agent activity feed
        </div>
      </div>

      {/* messages */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "1rem 1.125rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.55rem",
        }}
      >
        {messages.map((m) => (
          <MessageBubble key={m.agentKey ?? m.id} msg={m} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* input */}
      <div
        style={{
          padding: "0.875rem 1.125rem",
          borderTop: "1px solid #e2e8f0",
          background: "white",
        }}
      >
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <input
            type="text"
            value={triggerTime}
            onChange={(e) => setTriggerTime(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !running && handleStart()}
            placeholder="Trigger time (leave empty for now)"
            disabled={running}
            style={{
              flex: 1,
              padding: "0.6rem 0.875rem",
              border: "1px solid #e2e8f0",
              borderRadius: "0.5rem",
              fontSize: "0.85rem",
              outline: "none",
              background: running ? "#f8fafc" : "white",
              color: "#0f172a",
            }}
          />
          <button
            onClick={handleStart}
            disabled={running}
            style={{
              padding: "0.6rem 1.1rem",
              background: running ? "#93c5fd" : "#2563eb",
              color: "white",
              border: "none",
              borderRadius: "0.5rem",
              fontWeight: 600,
              fontSize: "0.85rem",
              cursor: running ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              whiteSpace: "nowrap",
              transition: "background 0.15s",
            }}
          >
            {running ? (
              <>
                <span
                  style={{
                    display: "inline-block",
                    width: 13,
                    height: 13,
                    border: "2px solid rgba(255,255,255,0.35)",
                    borderTopColor: "white",
                    borderRadius: "50%",
                    animation: "spin 0.7s linear infinite",
                  }}
                />
                Running
              </>
            ) : (
              "Start Analysis"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
