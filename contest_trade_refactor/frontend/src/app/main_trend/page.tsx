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
    current_return_pct?: number | null;
    realtime_quote?: Record<string, unknown>;
    exit_class?: string;
    exit_action?: string;
    reason?: string;
    realtime_source?: string | null;
    high_volume_class?: string;
    high_volume_reason?: string;
    add_setup_class?: string;
    sector_source?: string;
    rs_source?: string;
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

function factorBadge(row: MtfHolding): string {
  const hv = row.high_volume_class || "";
  const add = row.add_setup_class || "";
  const sector = row.sector_source || "";
  const rs = row.rs_source || "";
  const parts: string[] = [];
  if (hv) parts.push(`HV:${hv}`);
  if (row.next_day_guard_break_vwap) parts.push("破昨VWAP");
  const hvReason = row.high_volume_reason || "";
  if (hvReason) parts.push(hvReason.replace(";", "|"));
  if (add) parts.push(`Add:${add}`);
  if (sector) parts.push(`Sec:${sector.split("_")[0]}`);
  if (rs) parts.push(`RS:${rs.split("_")[0]}`);
  return parts.join(" ");
}

function displayStatus(row: {
  exit_class?: string;
  exit_action?: string;
  position_state?: string;
  display_status?: string;
  action?: string;
  state?: string;
}): string {
  const a = (row.exit_action || row.action || "").toLowerCase();
  const c = (row.exit_class || "").toUpperCase();
  const p = (row.position_state || row.state || "").toUpperCase();
  if (c.startsWith("SELL") || a === "sell" || a === "exit" || p === "EXIT") return "SELL";
  if (c === "REDUCE" || a === "reduce" || p === "REDUCE") return "REDUCE";
  if (p === "ADD" || a === "add") return "ADD";
  if (c === "DECAY" || a === "decay" || p === "DECAY") return "DECAY";
  if (row.display_status) return String(row.display_status).toUpperCase();
  return "HOLD";
}

function statusColor(exitClass: string | undefined, action: string | undefined): string {
  const label = displayStatus({ exit_class: exitClass, exit_action: action, action });
  if (label === "SELL") return "#dc2626";
  if (label === "REDUCE") return "#d97706";
  if (label === "DECAY") return "#ca8a04";
  if (label === "ADD") return "#059669";
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

function SummaryCards({
  rows,
  t1,
  realtime,
  tdayCount,
}: {
  rows: MtfHolding[];
  t1: MtfT1Row[];
  realtime: RealtimeSummary | null;
  tdayCount?: number;
}) {
  const statuses = rows.map((r) => displayStatus(r));
  const sell = statuses.filter((s) => s === "SELL").length;
  const reduce = statuses.filter((s) => s === "REDUCE").length;
  const add = statuses.filter((s) => s === "ADD").length;
  const decay = statuses.filter((s) => s === "DECAY").length;
  const hold = statuses.filter((s) => s === "HOLD").length;
  const buys = t1.filter((r) => (r.action || "").toUpperCase() === "BUY").length;
  const avg = realtime?.avg_return_pct;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: "0.65rem" }}>
      {rows.length > 0 ? (
        <>
          <MiniStat label="9:30 BUY" value={String(buys || rows.length)} color="#2563eb" />
          <MiniStat label="持仓" value={String(rows.length)} color="#2563eb" />
          <MiniStat label="HOLD" value={String(hold)} color="#2563eb" />
          <MiniStat label="DECAY" value={String(decay)} color="#ca8a04" />
          <MiniStat label="ADD" value={String(add)} color="#059669" />
          <MiniStat label="REDUCE" value={String(reduce)} color="#d97706" />
          <MiniStat label="SELL" value={String(sell)} color="#dc2626" />
        </>
      ) : (
        <>
          <MiniStat label="T日候选" value={String(tdayCount ?? 0)} color="#2563eb" />
          <MiniStat label="T+1 BUY" value={String(buys)} color="#059669" />
          <MiniStat label="状态" value="待9:30" color="#64748b" />
        </>
      )}
      {avg != null && rows.length > 0 && (
        <MiniStat label="实时平均收益" value={`${avg.toFixed(2)}%`} color={avg >= 0 ? "#dc2626" : "#059669"} />
      )}
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

function formatOrderBook(value: unknown): string {
  const n = num(value);
  if (n == null) return "—";
  return `${n.toFixed(1)}%`;
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
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>盘口</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>移动止损</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>初始止损</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>目标1/2</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>保护价</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>理由</th>
            <th style={{ padding: "0.35rem", borderBottom: "1px solid #e2e8f0" }}>持仓%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h) => {
            const hh = h as MtfHolding & RealtimeSummary["holdings"][number];
            const status = displayStatus(hh);
            const color = statusColor(status, hh.exit_action);
            const rr = hh.return_pct ?? hh.current_return_pct ?? 0;
            const hq = (hh as { realtime_quote?: Record<string, unknown> }).realtime_quote || {};
            const qPrev = typeof hq.prev_close === "number" ? hq.prev_close : null;
            const prev = qPrev ?? hh.prev_close;
            const realtimePrice = typeof hh.current_price === "number" ? hh.current_price : null;
            const dayMove = realtimePrice != null && prev != null && prev !== 0 ? ((realtimePrice / prev - 1) * 100) : null;
            const dayUp = dayMove != null && dayMove > 0;
            const dayDown = dayMove != null && dayMove < 0;
            const dayArrow = dayUp ? "▲" : dayDown ? "▼" : "—";
            const dayColor = dayUp ? "#dc2626" : dayDown ? "#059669" : "#64748b";
            // 持仓表当前价的箭头/颜色：以“相对买入价”的持仓盈亏为准（和收益列一致）
            const isUp = rr > 0;
            const isDown = rr < 0;
            const arrow = isUp ? "▲" : isDown ? "▼" : "—";
            const arrowColor = isUp ? "#dc2626" : isDown ? "#059669" : "#64748b";
            const rrUp = rr > 0;
            const rrColor = rrUp ? "#dc2626" : rr < 0 ? "#059669" : "#64748b";
            const bid = typeof hq.bid === "number" ? hq.bid : null;
            const ask = typeof hq.ask === "number" ? hq.ask : null;
            const activeBuy = typeof hq.active_buy_pct === "number" ? hq.active_buy_pct : null;
            const bidAskRatio = typeof hq.bid_ask_ratio === "number" ? hq.bid_ask_ratio : null;
            return (
              <tr key={hh.symbol_code}>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 600 }}>
                  {hh.symbol_name}<span style={{ color: "#94a3b8", marginLeft: "0.25rem", fontSize: "0.7rem" }}>{hh.symbol_code}</span>
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>
                  <span style={{ padding: "0.14rem 0.5rem", borderRadius: "0.35rem", fontWeight: 700, background: "#f1f5f9", color }}>
                    {status}
                  </span>
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 600, color: arrowColor }}>
                  <div>{arrow} {fmt(hh.current_price)}</div>
                  {dayMove != null ? (
                    <div style={{ fontSize: "0.65rem", color: dayColor, fontWeight: 400 }}>
                      今{dayArrow} {dayMove >= 0 ? "+" : ""}{dayMove.toFixed(2)}%
                    </div>
                  ) : null}
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 600 }}>{fmt(hh.entry_price)}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 600, color: rrColor }}>
                  {pct(rr)}
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontSize: "0.72rem", color: "#475569", maxWidth: 150 }}>
                  {bid != null && ask != null ? `买${bid} · 卖${ask}` : <span style={{ color: "#94a3b8" }}>—</span>}
                  {activeBuy != null || bidAskRatio != null ? (
                    <div style={{ fontSize: "0.65rem", color: "#94a3b8" }}>
                      {activeBuy != null ? `盘口买占比 ${formatOrderBook(activeBuy)}` : ""}
                      {bidAskRatio != null ? ` 委比${bidAskRatio > 0 ? "+" : ""}${(bidAskRatio * 100 - 100).toFixed(0)}%` : ""}
                    </div>
                  ) : null}
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>{fmt(hh.trailing_stop_price ?? hh.atr_trailing_stop)}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9" }}>{fmt(hh.stop_loss_price)}</td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", color: "#7c3aed", fontWeight: 600 }}>
                  {fmt(hh.target_price_1)}/{fmt(hh.target_price_2)}
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", color: "#b45309", fontWeight: 600 }}>
                  <div>{fmt(hh.profit_protect_price)}</div>
                  {hh.profit_protect_level ? <div style={{ fontSize: "0.65rem", color: "#92400e", fontWeight: 400 }}>{hh.profit_protect_level}</div> : null}
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", maxWidth: 300, color: "#64748b", fontSize: "0.72rem" }}>
                  <div>{(typeof hh.exit_reason === "string" ? hh.exit_reason : (hh.exit_reasons || []).join("；")) || "—"}</div>
                  {factorBadge(hh as MtfHolding) ? (
                    <div style={{ marginTop: "0.2rem", color: "#7c3aed", fontWeight: 500 }}>{factorBadge(hh as MtfHolding)}</div>
                  ) : null}
                </td>
                <td style={{ padding: "0.35rem", borderBottom: "1px solid #f1f5f9", fontWeight: 700, color: "#1e40af" }}>
                  {fmt(hh.suggested_position_pct ?? hh.raw_position_pct, 2)}%
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
        if (json.error === "no holdings" || json.error?.includes("no holdings")) {
          setRealtime(null);
          setRealtimeMsg("");
        } else {
          setRealtimeMsg(`${json.error || "实时行情失败"}`);
        }
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
  const displayHoldings = useMemo(() => {
    if (realtimeRows.length === 0) return holdings;
    const rtByCode = new Map(realtimeRows.map((r) => [r.symbol_code, r]));
    return holdings.map((h) => {
      const rt = rtByCode.get(h.symbol_code);
      if (!rt) return h;
      return {
        ...h,
        current_price: rt.current_price ?? h.current_price,
        return_pct: rt.return_pct ?? rt.current_return_pct ?? h.current_return_pct,
        current_return_pct: rt.current_return_pct ?? rt.return_pct ?? h.current_return_pct,
        realtime_quote: { ...(h.realtime_quote || {}), ...(rt.realtime_quote || {}) },
        realtime_source: rt.realtime_source ?? h.realtime_source,
      };
    });
  }, [holdings, realtimeRows]);
  const exits = data?.exit_decisions?.decisions ?? [];
  const t1rows = data?.t1_execution?.rows ?? [];
  const tdayRows = data?.tday_candidates?.rows ?? [];
  const candidates = data?.t1_execution?.present && t1rows.length > 0 ? t1rows : tdayRows;
  const tdayCount = data?.tday_candidates?.count ?? tdayRows.length;
  const showT1Pending = Boolean(tdayCount > 0 && !data?.t1_execution?.present);
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
        {showT1Pending && (
          <div style={{ background: "#dbeafe", color: "#1e40af", padding: "0.6rem 0.9rem", borderRadius: "0.6rem", fontSize: "0.85rem" }}>
            明天 T+1 开盘候选：<strong>{tdayCount}</strong> 只（T日 {data?.tday_candidates?.trade_date || data?.as_of_date || "—"} 收盘扫描，全部 WAIT，待 9:30 执行打分）
          </div>
        )}
        {data?.t2?.present && (
          <div style={{ background: "#ecfdf5", color: "#065f46", padding: "0.6rem 0.9rem", borderRadius: "0.6rem", fontSize: "0.85rem" }}>
            T+2 持有第二天（{data.t2.logged_at || data.t2.wave}）：SELL {data.t2.counts?.SELL ?? 0} · REDUCE {data.t2.counts?.REDUCE ?? 0} · HOLD {data.t2.counts?.HOLD ?? 0}
            {data.t2.avg_return_pct != null ? ` · 平均收益 ${data.t2.avg_return_pct.toFixed(2)}%` : ""}
            。未与今日 9:30 新买入合并。
          </div>
        )}
        <SummaryCards rows={displayHoldings as MtfHolding[]} t1={t1rows} realtime={realtime} tdayCount={tdayCount} />

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

        <Stack title="持仓状态机 HOLD / REDUCE / SELL" count={displayHoldings.length}>
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
          {d.profit_protect_price != null ? (
            <span style={{ fontSize: "0.7rem", color: "#b45309", fontWeight: 700 }}>保护 {fmt(d.profit_protect_price)}</span>
          ) : null}
          {d.target_price_1 != null ? (
            <span style={{ fontSize: "0.7rem", color: "#7c3aed", fontWeight: 700 }}>目标 {fmt(d.target_price_1)}/{fmt(d.target_price_2)}</span>
          ) : null}
          <span style={{ marginLeft: "auto", fontSize: "0.75rem", fontWeight: 700, color: (d.current_return_pct ?? 0) >= 0 ? "#dc2626" : "#059669" }}>{pct(d.current_return_pct)}</span>
        </div>
      ))}
    </div>
  );
}
