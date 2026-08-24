"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type {
  MtfDashboard,
  MtfExitDecision,
  MtfHolding,
  MtnCandidate,
  MtfT1Row,
} from "@/types/trading";

interface RealtimeSummary {
  ok: boolean;
  avg_return_pct: number;
  positions_count: number;
  sell_count: number;
  reduce_count: number;
  holdings: Array<{
    symbol_code?: string;
    symbol_name?: string;
    entry_price?: number;
    current_price?: number | null;
    return_pct?: number | null;
    exit_class?: string;
    exit_action?: string;
    reason?: string;
    realtime_source?: string | null;
  }>;
}

function num(value: unknown): number | null {
  if (value == null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function fmt(value: unknown, digits = 2): string {
  const n = num(value);
  if (n == null) return "—";
  return n.toFixed(digits);
}

function pct(value: unknown, digits = 1): string {
  const n = num(value);
  if (n == null) return "—";
  return `${n.toFixed(digits)}%`;
}

function statusColor(exitClass: string | undefined, action: string | undefined): string {
  const a = (action || "").toLowerCase();
  const c = (exitClass || "").toUpperCase();
  if (c.startsWith("SELL") || a === "sell" || a === "exit") return "#dc2626";
  if (c === "REDUCE" || a === "reduce") return "#d97706";
  if (c === "DECAY" || a === "decay") return "#a16207";
  if (c === "ADD" || a === "add") return "#059669";
  return "#2563eb";
}

function Card({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: "0.9rem", padding: "1rem 1.1rem", boxShadow: "0 1px 4px rgba(0,0,0,0.05)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
        <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>{title}</div>
        {right && <div style={{ fontSize: "0.75rem", color: "#64748b" }}>{right}</div>}
      </div>
      {children}
    </div>
  );
}

function MiniStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ background: "#f8fafc", borderRadius: "0.7rem", padding: "0.65rem 0.8rem", borderLeft: `3px solid ${color}` }}>
      <div style={{ fontSize: "0.7rem", color: "#64748b" }}>{label}</div>
      <div style={{ fontWeight: 800, fontSize: "1.05rem", color }}>{value}</div>
    </div>
  );
}

function SummaryCards({ d }: { d: MtfDashboard }) {
  const tday = d.tday_candidates;
  const t1 = d.t1_execution;
  const holdings = d.holdings?.rows || [];
  const exits = d.exit_decisions?.decisions || [];
  const sellCount = exits.filter((x) => x.action === "sell" || x.action === "exit" || (x.exit_class || "").toUpperCase().startsWith("SELL")).length;
  const reduceCount = exits.filter((x) => x.action === "reduce" || (x.exit_class || "").toUpperCase() === "REDUCE").length;
  const holdCount = holdings.length - sellCount - reduceCount;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: "0.65rem" }}>
      {[
        { label: "T日候选", value: tday?.count ?? 0, color: "#2563eb" },
        { label: "T+1 BUY", value: t1?.rows?.filter((r) => (r.action || "").toUpperCase() === "BUY").length ?? 0, color: "#059669" },
        { label: "持仓", value: holdings.length, color: "#2563eb" },
        { label: "HOLD", value: Math.max(0, holdCount), color: "#2563eb" },
        { label: "REDUCE", value: reduceCount, color: "#d97706" },
        { label: "SELL", value: sellCount, color: "#dc2626" },
      ].map((s) => (
        <div key={s.label} style={{ background: "#f8fafc", borderRadius: "0.7rem", padding: "0.65rem 0.8rem", borderLeft: `3px solid ${s.color}` }}>
          <div style={{ fontSize: "0.7rem", color: "#64748b" }}>{s.label}</div>
          <div style={{ fontWeight: 800, fontSize: "1.15rem", color: s.color }}>{s.value}</div>
        </div>
      ))}
    </div>
  );
}

function CandidateTable({ rows }: { rows: MtfT1Row[] | MtnCandidate[] }) {
  if (!rows || rows.length === 0) return <div style={{ color: "#94a3b8", fontSize: "0.85rem" }}>暂无候选</div>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
        <thead>
          <tr style={{ color: "#64748b", textAlign: "left" }}>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>股票</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>主题</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>Trend</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>Sector</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>Pre</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>T+1</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>参考价</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>初始止损</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isBuy = (r.action || "").toUpperCase() === "BUY";
            return (
              <tr key={r.symbol_code || `${r.symbol_name}`}>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 600 }}>
                  {r.symbol_name}<span style={{ color: "#94a3b8", marginLeft: "0.25rem", fontSize: "0.7rem" }}>{r.symbol_code}</span>
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>{r.theme}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>{r.trend_grade}/{r.trend_state}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>{r.sector_grade}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 700 }}>{fmt((r as MtfT1Row).final_score ?? (r as MtnCandidate).pre_score)}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>
                  <span style={{ padding: "0.14rem 0.45rem", borderRadius: "0.35rem", fontSize: "0.7rem", fontWeight: 700, background: isBuy ? "#d1fae5" : "#f1f5f9", color: isBuy ? "#065f46" : "#475569" }}>
                    {(r as MtfT1Row).execution_grade ?? (r as MtnCandidate).t1_state ?? "WAIT"}
                  </span>
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>{fmt(r.entry_price ?? r.reference_price)}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>{fmt(r.initial_stop)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HoldingsTable({ rows }: { rows: MtfHolding[] }) {
  if (!rows || rows.length === 0) return <div style={{ color: "#94a3b8", fontSize: "0.85rem" }}>暂无持仓</div>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
        <thead>
          <tr style={{ color: "#64748b", textAlign: "left" }}>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>股票</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>状态</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>当前价</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>买入价</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>收益</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>移动止损</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>初始止损</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>理由</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>持仓%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h) => {
            const status = h.exit_class || h.position_state || "HOLD";
            const color = statusColor(h.exit_class, h.exit_action);
            const rr = h.return_pct ?? h.current_return_pct ?? 0;
            const up = rr > 0;
            return (
              <tr key={h.symbol_code}>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 600 }}>
                  {h.symbol_name}<span style={{ color: "#94a3b8", marginLeft: "0.25rem", fontSize: "0.7rem" }}>{h.symbol_code}</span>
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>
                  <span style={{ padding: "0.14rem 0.5rem", borderRadius: "0.35rem", fontWeight: 700, background: "#f1f5f9", color }}>
                    {status}
                  </span>
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 600, color: up ? "#dc2626" : "#059669" }}>
                  {up ? "▲" : "▼"} {fmt(h.current_price)}
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 600 }}>{fmt(h.entry_price)}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 600, color: up ? "#dc2626" : "#059669" }}>
                  {pct(rr)}
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>{fmt(h.trailing_stop_price ?? h.atr_trailing_stop)}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>{fmt(h.stop_loss_price)}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", maxWidth: 260, color: "#64748b", fontSize: "0.72rem" }}>
                  {(typeof h.exit_reason === "string" ? h.exit_reason : (h.exit_reasons || []).join("；")) || "—"}
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 700, color: "#1e40af" }}>
                  {fmt(h.suggested_position_pct ?? h.raw_position_pct, 2)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function MainTrendPage() {
  const [data, setData] = useState<MtfDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [initMsg, setInitMsg] = useState("");
  const [initLoading, setInitLoading] = useState(false);
  const [realtime, setRealtime] = useState<RealtimeSummary | null>(null);
  const [realtimeLoading, setRealtimeLoading] = useState(false);
  const [realtimeMsg, setRealtimeMsg] = useState("");
  const [selectedDate, setSelectedDate] = useState("");
  const [availableDates, setAvailableDates] = useState<string[]>([]);

  const refreshRealtime = async (dateArg?: string) => {
    if (realtimeLoading) return;
    setRealtimeLoading(true);
    setRealtimeMsg("");
    try {
      const target = dateArg ?? selectedDate;
      const url = target ? `/api/main_trend/realtime?date=${encodeURIComponent(target)}` : "/api/main_trend/realtime";
      const res = await fetch(url, { cache: "no-store" });
      const json = await res.json();
      if (!res.ok || !json.ok) {
        setRealtimeMsg(`${json.error || "实时行情失败"}`);
      } else {
        setRealtime(json);
        setRealtimeMsg(`已刷新：平均 ${json.avg_return_pct}% · SELL ${json.sell_count} · REDUCE ${json.reduce_count}`);
      }
    } catch (e) {
      setRealtimeMsg(`失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRealtimeLoading(false);
    }
  };

  const initHoldings = async () => {
    setInitLoading(true);
    setInitMsg("");
    try {
      const candidateDate = data?.tday_candidates?.trade_date || data?.as_of_date || "";
      const t1 = data?.t1_execution;
      const res = await fetch("/api/main_trend/holdings/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          date: candidateDate,
          tday: data?.tday_candidates?.path || "",
          t1: t1?.path || "",
        }),
      });
      const json = await res.json();
      if (json.ok) setInitMsg(`已生成 ${json.count} 个持仓 → ${json.path}`);
      else setInitMsg(`失败：${json.error || "未知错误"}`);
    } catch (e) {
      setInitMsg(`失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setInitLoading(false);
    }
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const url = selectedDate ? `/api/main_trend/dashboard?date=${encodeURIComponent(selectedDate)}` : "/api/main_trend/dashboard";
    fetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((json: MtfDashboard) => {
        if (alive) { setData(json); setError(""); }
      })
      .catch((e: unknown) => {
        if (alive) setError(String(e instanceof Error ? e.message : e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, [refresh, selectedDate]);

  // 页面首次加载可用日期
  useEffect(() => {
    let alive = true;
    fetch("/api/main_trend/dates", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((json: { ok?: boolean; dates?: string[] }) => {
        if (alive) setAvailableDates(json?.dates ?? []);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // 进入页面自动加载实时收益（首次默认最新；之后跟随 selectedDate）
  useEffect(() => {
    refreshRealtime(selectedDate || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDate]);

  const holdings = data?.holdings?.rows ?? [];
  const realtimeRows = realtime?.holdings ?? [];
  const displayHoldings = realtimeRows.length > 0 ? realtimeRows : holdings;
  const exits = data?.exit_decisions?.decisions ?? [];
  const t1rows = data?.t1_execution?.rows ?? [];
  const candidates = t1rows.length ? t1rows : (data?.tday_candidates?.rows ?? []);
  const sellDecisions = useMemo(() => {
    if (!exits || exits.length === 0) return [];
    return exits.filter((x) => x.action === "sell" || x.action === "exit" || (x.exit_class || "").toUpperCase().startsWith("SELL"));
  }, [exits]);
  const reduceDecisions = useMemo(() => exits.filter((x) => x.action === "reduce" || (x.exit_class || "").toUpperCase() === "REDUCE"), [exits]);

  return (
    <div style={{ minHeight: "100vh", background: "#f1f5f9", color: "#0f172a" }}>
      <header style={{ background: "linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)", color: "white", padding: "0.9rem 1.5rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <span style={{ fontSize: "1.5rem" }}>📈</span>
          <div>
            <div style={{ fontWeight: 700, fontSize: "1.05rem" }}>主升浪持仓系统</div>
            <div style={{ fontSize: "0.7rem", opacity: 0.75 }}>T日候选 → T+1 执行 → HOLD / REDUCE / SELL</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
          <Link href="/" style={{ color: "white", textDecoration: "none", fontSize: "0.8rem" }}>← Dashboard</Link>
          <label style={{ fontSize: "0.75rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
            日期
            <select
              value={selectedDate || data?.requested_date || ""}
              onChange={(e) => { setSelectedDate(e.target.value); setRealtime(null); }}
              style={{ background: "rgba(255,255,255,0.95)", color: "#0f172a", border: "none", borderRadius: "0.5rem", padding: "0.32rem 0.5rem", fontSize: "0.78rem", cursor: "pointer" }}
            >
              <option value="">最新</option>
              {(availableDates.length ? availableDates : (data?.available_dates ?? [])).map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>
          <span style={{ fontSize: "0.8rem", opacity: 0.9 }}>{data?.as_of_date || "—"}</span>
          <button
            onClick={initHoldings}
            disabled={initLoading || !data?.t1_execution?.present}
            style={{ background: "rgba(255,255,255,0.12)", border: "none", color: "#fff", borderRadius: "0.5rem", padding: "0.4rem 0.8rem", cursor: "pointer", fontSize: "0.8rem" }}
            title="从已有 t1_execution 生成持仓 holdings.json"
          >
            {initLoading ? "生成中…" : "生成持仓"}
          </button>
          <button
            onClick={() => refreshRealtime(selectedDate || undefined)}
            disabled={realtimeLoading}
            style={{ background: "rgba(255,255,255,0.18)", border: "none", color: "#fff", borderRadius: "0.5rem", padding: "0.4rem 0.8rem", cursor: "pointer", fontSize: "0.8rem" }}
            title="实时调用腾讯财经，计算当前整体收益和状态"
          >
            {realtimeLoading ? "实时获取中…" : "实时收益"}
          </button>
          <button onClick={() => setRefresh((x) => x + 1)} disabled={loading} style={{ background: "rgba(255,255,255,0.12)", border: "none", color: "#fff", borderRadius: "0.5rem", padding: "0.4rem 0.8rem", cursor: "pointer", fontSize: "0.8rem" }}>
            {loading ? "加载中…" : "刷新"}
          </button>
        </div>
      </header>

      <main style={{ padding: "1rem", display: "flex", flexDirection: "column", gap: "0.9rem", maxWidth: 1200, margin: "0 auto" }}>
        {error && <div style={{ background: "#fee2e2", color: "#991b1b", padding: "0.6rem 0.9rem", borderRadius: "0.6rem", fontSize: "0.85rem" }}>{error}</div>}
        {initMsg && <div style={{ background: "#dbeafe", color: "#1e40af", padding: "0.6rem 0.9rem", borderRadius: "0.6rem", fontSize: "0.85rem" }}>{initMsg}</div>}
        {realtimeMsg && <div style={{ background: "#fef9c3", color: "#713f12", padding: "0.6rem 0.9rem", borderRadius: "0.6rem", fontSize: "0.85rem" }}>{realtimeMsg}</div>}
        {realtime && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: "0.65rem" }}>
            <MiniStat label="实时平均收益" value={`${realtime.avg_return_pct.toFixed(2)}%`} color={realtime.avg_return_pct >= 0 ? "#dc2626" : "#059669"} />
            <MiniStat label="持仓数" value={String(realtime.positions_count)} color="#2563eb" />
            <MiniStat label="SELL" value={String(realtime.sell_count)} color="#dc2626" />
            <MiniStat label="REDUCE" value={String(realtime.reduce_count)} color="#d97706" />
          </div>
        )}

        {data && <SummaryCards d={data} />}

        {(sellDecisions.length > 0 || reduceDecisions.length > 0) && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "0.9rem" }}>
            {sellDecisions.length > 0 && (
              <Stack title="🔴 待卖出 / 已触发 SELL" count={sellDecisions.length}>
                <DecisionList decisions={sellDecisions} />
              </Stack>
            )}
            {reduceDecisions.length > 0 && (
              <Stack title="🟠 建议减仓 / REDUCE" count={reduceDecisions.length}>
                <DecisionList decisions={reduceDecisions} />
              </Stack>
            )}
          </div>
        )}

        <Stack title="持仓状态机 HOLD / REDUCE / SELL" count={holdings.length}>
          <HoldingsTable rows={displayHoldings as MtfHolding[]} />
        </Stack>

        <Stack title="T日候选 / T+1执行" right={`候选 ${data?.tday_candidates?.count ?? 0} · T+1 Result ${data?.t1_execution?.present ? "有" : "无"}`}>
          <CandidateTable rows={candidates} />
        </Stack>
      </main>
    </div>
  );
}

function Stack({ title, count, right, children }: { title: string; count?: number; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: "0.9rem", padding: "1rem 1.1rem", boxShadow: "0 1px 4px rgba(0,0,0,0.05)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
        <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>
          {title}
          {count != null && <span style={{ color: "#64748b", fontWeight: 400, marginLeft: "0.4rem" }}>({count})</span>}
        </div>
        {right && <div style={{ fontSize: "0.75rem", color: "#64748b" }}>{right}</div>}
      </div>
      {children}
    </div>
  );
}

function DecisionList({ decisions }: { decisions: MtfExitDecision[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      {decisions.map((d) => (
        <div key={d.symbol_code} style={{ display: "flex", gap: "0.6rem", alignItems: "center", background: "#f8fafc", borderRadius: "0.6rem", padding: "0.5rem 0.7rem" }}>
          <span style={{ fontWeight: 700, minWidth: 90 }}>{d.symbol_name}<span style={{ color: "#94a3b8", fontSize: "0.7rem", marginLeft: "0.2rem" }}>{d.symbol_code}</span></span>
          <span style={{ fontSize: "0.75rem", color: "#475569" }}>{d.reason || d.exit_class || d.state}</span>
          <span style={{ marginLeft: "auto", fontSize: "0.75rem", fontWeight: 700, color: (d.current_return_pct ?? 0) >= 0 ? "#dc2626" : "#059669" }}>{pct(d.current_return_pct)}</span>
        </div>
      ))}
    </div>
  );
}
