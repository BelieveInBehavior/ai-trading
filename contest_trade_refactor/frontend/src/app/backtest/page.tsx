"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";

interface FactorStats {
  factor_name: string;
  total_dates: number;
  date_range: string;
  store_path: string;
}

interface HorizonStat {
  hit_rate: number | null;
  avg_return: number | null;
  avg_alpha: number | null;
  sharpe: number | null;
  count: number;
  win_count: number;
  loss_count: number;
  max_return: number | null;
  min_return: number | null;
  median_return: number | null;
}

interface QuintileItem {
  quintile: string;
  count: number;
  avg_return: number | null;
  hit_rate: number | null;
}

interface BacktestResult {
  factor_name: string;
  total_signals: number;
  evaluated_signals: number;
  horizons: Record<string, HorizonStat>;
  quintile_returns: Record<string, QuintileItem[]>;
  ic_values: Record<string, number | null>;
  error?: string;
}

interface PerformanceStats {
  total: number;
  hits: number;
  win_rate: number;
  avg_return: number;
  pending_count: number;
}

interface PerformanceRecord {
  trigger_time: string;
  symbol_code: string;
  symbol_name: string;
  action: string;
  actual_return_pct: number;
  hit: boolean;
}

interface ThresholdMeta {
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
}

const FACTOR_LABELS: Record<string, string> = {
  individual_fund_flow: "个股主力资金流",
  margin_trading: "融资融券",
  block_trade: "大宗交易",
  sector_fund_flow: "板块资金流向",
  zt_seal_strength: "涨停封单强度",
};

function pct(val: number | null | undefined, digits = 2): string {
  if (val == null) return "N/A";
  return `${(val * 100).toFixed(digits)}%`;
}

function IcBadge({ ic }: { ic: number | null }) {
  if (ic == null) return <span style={{ color: "#94a3b8" }}>N/A</span>;
  const abs = Math.abs(ic);
  let color = "#94a3b8";
  let label = "无效";
  if (abs > 0.05) { color = ic > 0 ? "#10b981" : "#ef4444"; label = ic > 0 ? "有效" : "反向"; }
  else if (abs > 0.03) { color = "#f59e0b"; label = "弱有效"; }
  return (
    <span style={{ fontWeight: 700, color }}>
      {ic.toFixed(4)} <span style={{ fontSize: "0.7rem", fontWeight: 400 }}>({label})</span>
    </span>
  );
}

export default function BacktestPage() {
  const [factorSummary, setFactorSummary] = useState<Record<string, FactorStats>>({});
  const [backtestResults, setBacktestResults] = useState<Record<string, BacktestResult>>({});
  const [performance, setPerformance] = useState<{ stats: PerformanceStats; history: PerformanceRecord[] } | null>(null);
  const [thresholds, setThresholds] = useState<Record<string, Record<string, number>>>({});
  const [thresholdMeta, setThresholdMeta] = useState<Record<string, Record<string, ThresholdMeta>>>({});
  const [loading, setLoading] = useState(false);
  const [runningBacktest, setRunningBacktest] = useState(false);
  const [calibrating, setCalibrating] = useState(false);
  const [calibrationResult, setCalibrationResult] = useState<Record<string, unknown> | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "thresholds">("overview");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryRes, resultsRes, perfRes, threshRes] = await Promise.all([
        fetch("/api/factors/summary"),
        fetch("/api/backtest/results"),
        fetch("/api/performance/history"),
        fetch("/api/thresholds"),
      ]);
      if (summaryRes.ok) setFactorSummary(await summaryRes.json());
      if (resultsRes.ok) {
        const data = await resultsRes.json();
        setBacktestResults(data.results || {});
      }
      if (perfRes.ok) {
        const data = await perfRes.json();
        setPerformance({ stats: data.stats, history: data.history || [] });
      }
      if (threshRes.ok) {
        const data = await threshRes.json();
        setThresholds(data.thresholds || {});
        setThresholdMeta(data.metadata || {});
      }
    } catch (e) {
      console.error("Failed to fetch data:", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const runBacktest = async () => {
    setRunningBacktest(true);
    try {
      const res = await fetch("/api/backtest/run?factor_name=all", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setBacktestResults(data);
      }
    } catch (e) {
      console.error("Backtest failed:", e);
    }
    setRunningBacktest(false);
  };

  const autoCalibrate = async () => {
    setCalibrating(true);
    try {
      const res = await fetch("/api/thresholds/calibrate", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setCalibrationResult(data.calibration || {});
        setThresholds(data.new_thresholds || {});
      }
    } catch (e) {
      console.error("Calibration failed:", e);
    }
    setCalibrating(false);
  };

  const updateThreshold = async (factorName: string, key: string, value: number) => {
    const newThresholds = { ...thresholds };
    if (!newThresholds[factorName]) newThresholds[factorName] = {};
    newThresholds[factorName][key] = value;
    setThresholds(newThresholds);

    try {
      await fetch(`/api/thresholds/${factorName}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates: { [key]: value } }),
      });
    } catch (e) {
      console.error("Update failed:", e);
    }
  };

  const resetThresholds = async (factorName: string) => {
    try {
      const res = await fetch(`/api/thresholds/${factorName}/reset`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setThresholds(prev => ({ ...prev, [factorName]: data.thresholds }));
      }
    } catch (e) {
      console.error("Reset failed:", e);
    }
  };

  const totalDates = Object.values(factorSummary).reduce((sum, s) => sum + (s.total_dates || 0), 0);
  const hasData = totalDates > 0;
  const hasResults = Object.keys(backtestResults).length > 0;

  return (
    <div style={{ minHeight: "100vh", background: "#f1f5f9" }}>
      {/* Header */}
      <header style={{
        background: "white",
        borderBottom: "1px solid #e2e8f0",
        padding: "0.875rem 1.5rem",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <Link href="/" style={{ color: "#2563eb", textDecoration: "none", fontSize: "0.85rem" }}>
            ← Dashboard
          </Link>
          <h1 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0 }}>因子回测系统</h1>
        </div>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button
            onClick={autoCalibrate}
            disabled={calibrating || !hasData}
            style={{
              padding: "0.45rem 1rem",
              borderRadius: "0.375rem",
              border: "1px solid #f59e0b",
              background: hasData ? "#fffbeb" : "#f8fafc",
              color: hasData ? "#92400e" : "#94a3b8",
              cursor: hasData ? "pointer" : "not-allowed",
              fontSize: "0.8rem",
            }}
          >
            {calibrating ? "校准中..." : "自动校准阈值"}
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            style={{
              padding: "0.45rem 1rem",
              borderRadius: "0.375rem",
              border: "1px solid #e2e8f0",
              background: "white",
              cursor: "pointer",
              fontSize: "0.8rem",
            }}
          >
            {loading ? "加载中..." : "刷新数据"}
          </button>
          <button
            onClick={runBacktest}
            disabled={runningBacktest || !hasData}
            style={{
              padding: "0.45rem 1rem",
              borderRadius: "0.375rem",
              border: "none",
              background: hasData ? "#2563eb" : "#94a3b8",
              color: "white",
              cursor: hasData ? "pointer" : "not-allowed",
              fontSize: "0.8rem",
              fontWeight: 600,
            }}
          >
            {runningBacktest ? "回测中..." : "运行回测"}
          </button>
        </div>
      </header>

      {/* Tabs */}
      <div style={{ background: "white", borderBottom: "1px solid #e2e8f0", padding: "0 1.5rem" }}>
        <div style={{ display: "flex", gap: "0" }}>
          {(["overview", "thresholds"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: "0.75rem 1.25rem",
                border: "none",
                background: "none",
                cursor: "pointer",
                fontSize: "0.85rem",
                fontWeight: activeTab === tab ? 600 : 400,
                color: activeTab === tab ? "#2563eb" : "#64748b",
                borderBottom: activeTab === tab ? "2px solid #2563eb" : "2px solid transparent",
              }}
            >
              {tab === "overview" ? "回测概览" : "阈值配置"}
            </button>
          ))}
        </div>
      </div>

      <main style={{ padding: "1.5rem", maxWidth: "1400px", margin: "0 auto" }}>
        {activeTab === "overview" ? (
        <>
        {/* Calibration result banner */}
        {calibrationResult && (
          <div style={{
            marginBottom: "1rem",
            padding: "0.875rem 1rem",
            background: "#f0fdf4",
            border: "1px solid #bbf7d0",
            borderRadius: "0.5rem",
            fontSize: "0.8rem",
          }}>
            <strong>自动校准完成：</strong>
            {Object.entries(calibrationResult).map(([name, result]) => {
              const r = result as Record<string, unknown>;
              return (
                <span key={name} style={{ marginLeft: "1rem" }}>
                  {FACTOR_LABELS[name] || name}: {r.status === "calibrated"
                    ? `已调整 (IC=${typeof r.ic_t1 === 'number' ? (r.ic_t1 as number).toFixed(4) : 'N/A'})`
                    : String(r.status)}
                </span>
              );
            })}
          </div>
        )}
        {/* Factor Store Status */}
        <section style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "0.75rem" }}>
            因子数据存储状态
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "0.75rem" }}>
            {Object.entries(factorSummary).map(([name, stats]) => (
              <div key={name} style={{
                background: "white",
                borderRadius: "0.625rem",
                padding: "1rem",
                border: "1px solid #e2e8f0",
                borderLeft: `3px solid ${stats.total_dates > 0 ? "#10b981" : "#94a3b8"}`,
              }}>
                <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: "0.4rem" }}>
                  {FACTOR_LABELS[name] || name}
                </div>
                <div style={{ fontSize: "0.78rem", color: "#64748b" }}>
                  <div>数据天数: <strong>{stats.total_dates}</strong></div>
                  <div>日期范围: {stats.date_range}</div>
                </div>
              </div>
            ))}
          </div>
          {!hasData && (
            <div style={{
              marginTop: "1rem",
              padding: "1rem",
              background: "#fffbeb",
              border: "1px solid #fde68a",
              borderRadius: "0.5rem",
              fontSize: "0.8rem",
              color: "#92400e",
            }}>
              还没有积累因子数据。请先运行主系统采集数据（<code>.venv/bin/python main_loop.py</code>），每次运行会自动存储结构化因子。积累 3-5 天后即可运行回测。
            </div>
          )}
        </section>

        {/* Performance Overview */}
        {performance && (
          <section style={{ marginBottom: "1.5rem" }}>
            <h2 style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "0.75rem" }}>
              信号绩效概览
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "0.75rem" }}>
              <StatCard value={String(performance.stats.total)} label="总信号数" color="#2563eb" />
              <StatCard value={String(performance.stats.hits)} label="命中数" color="#10b981" />
              <StatCard value={`${performance.stats.win_rate}%`} label="胜率" color={performance.stats.win_rate > 50 ? "#10b981" : "#ef4444"} />
              <StatCard value={`${performance.stats.avg_return}%`} label="平均收益" color={performance.stats.avg_return > 0 ? "#10b981" : "#ef4444"} />
              <StatCard value={String(performance.stats.pending_count)} label="待验证" color="#f59e0b" />
            </div>

            {/* Recent history table */}
            {performance.history.length > 0 && (
              <div style={{ marginTop: "1rem", background: "white", borderRadius: "0.625rem", border: "1px solid #e2e8f0", overflow: "hidden" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
                  <thead>
                    <tr style={{ background: "#f8fafc" }}>
                      <th style={thStyle}>日期</th>
                      <th style={thStyle}>股票</th>
                      <th style={thStyle}>操作</th>
                      <th style={thStyle}>实际收益</th>
                      <th style={thStyle}>命中</th>
                    </tr>
                  </thead>
                  <tbody>
                    {performance.history.slice(-20).reverse().map((r, i) => (
                      <tr key={i} style={{ borderTop: "1px solid #f1f5f9" }}>
                        <td style={tdStyle}>{r.trigger_time?.split(" ")[0]}</td>
                        <td style={tdStyle}>{r.symbol_name}({r.symbol_code})</td>
                        <td style={tdStyle}>{r.action}</td>
                        <td style={{ ...tdStyle, color: r.actual_return_pct > 0 ? "#10b981" : "#ef4444", fontWeight: 600 }}>
                          {r.actual_return_pct?.toFixed(2)}%
                        </td>
                        <td style={tdStyle}>
                          <span style={{ color: r.hit ? "#10b981" : "#ef4444" }}>{r.hit ? "✓" : "✗"}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {/* Backtest Results */}
        {hasResults && (
          <section>
            <h2 style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "0.75rem" }}>
              因子回测结果
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              {Object.entries(backtestResults).map(([name, result]) => (
                <FactorResultCard key={name} name={name} result={result} />
              ))}
            </div>
          </section>
        )}
        </>
        ) : (
        /* Thresholds Tab */
        <section>
          <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
            {Object.entries(thresholds).map(([factorName, values]) => {
              const meta = thresholdMeta[factorName] || {};
              const factorLabel = (meta as Record<string, unknown>)._label as string || FACTOR_LABELS[factorName] || factorName;
              return (
                <div key={factorName} style={{
                  background: "white",
                  borderRadius: "0.75rem",
                  padding: "1.25rem",
                  border: "1px solid #e2e8f0",
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
                    <h3 style={{ fontSize: "0.95rem", fontWeight: 700, margin: 0 }}>{factorLabel}</h3>
                    <button
                      onClick={() => resetThresholds(factorName)}
                      style={{
                        padding: "0.3rem 0.75rem",
                        borderRadius: "0.3rem",
                        border: "1px solid #fca5a5",
                        background: "#fef2f2",
                        color: "#dc2626",
                        fontSize: "0.72rem",
                        cursor: "pointer",
                      }}
                    >
                      重置默认
                    </button>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "0.75rem" }}>
                    {Object.entries(values).map(([key, value]) => {
                      const keyMeta = meta[key] as ThresholdMeta | undefined;
                      if (!keyMeta) return null;
                      return (
                        <ThresholdSlider
                          key={key}
                          factorName={factorName}
                          paramKey={key}
                          value={value as number}
                          meta={keyMeta}
                          onChange={updateThreshold}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
        )}
      </main>
    </div>
  );
}

function StatCard({ value, label, color }: { value: string; label: string; color: string }) {
  return (
    <div style={{
      background: "white",
      borderRadius: "0.625rem",
      padding: "0.875rem 1rem",
      borderLeft: `3px solid ${color}`,
      textAlign: "center",
      border: "1px solid #e2e8f0",
    }}>
      <div style={{ fontSize: "1.5rem", fontWeight: 700, color, lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: "0.72rem", color: "#64748b", marginTop: "0.3rem" }}>{label}</div>
    </div>
  );
}

function FactorResultCard({ name, result }: { name: string; result: BacktestResult }) {
  if (result.error) {
    return (
      <div style={{ background: "white", borderRadius: "0.625rem", padding: "1rem", border: "1px solid #e2e8f0" }}>
        <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>{FACTOR_LABELS[name] || name}</div>
        <div style={{ color: "#94a3b8", fontSize: "0.8rem", marginTop: "0.5rem" }}>{result.error}</div>
      </div>
    );
  }

  return (
    <div style={{ background: "white", borderRadius: "0.75rem", padding: "1.25rem", border: "1px solid #e2e8f0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>{FACTOR_LABELS[name] || name}</div>
          <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
            总信号 {result.total_signals} · 有效评估 {result.evaluated_signals}
          </div>
        </div>
        <div style={{ display: "flex", gap: "1rem" }}>
          {Object.entries(result.ic_values || {}).map(([horizon, ic]) => (
            <div key={horizon} style={{ textAlign: "center" }}>
              <div style={{ fontSize: "0.65rem", color: "#94a3b8", textTransform: "uppercase" }}>IC {horizon}</div>
              <IcBadge ic={ic} />
            </div>
          ))}
        </div>
      </div>

      {/* Horizon stats table */}
      {result.horizons && Object.keys(result.horizons).length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem", marginBottom: "1rem" }}>
          <thead>
            <tr style={{ background: "#f8fafc" }}>
              <th style={thStyle}>Horizon</th>
              <th style={thStyle}>胜率</th>
              <th style={thStyle}>平均收益</th>
              <th style={thStyle}>超额收益</th>
              <th style={thStyle}>Sharpe</th>
              <th style={thStyle}>样本数</th>
              <th style={thStyle}>最大收益</th>
              <th style={thStyle}>最大亏损</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(result.horizons).map(([horizon, stats]) => (
              <tr key={horizon} style={{ borderTop: "1px solid #f1f5f9" }}>
                <td style={{ ...tdStyle, fontWeight: 600 }}>{horizon}</td>
                <td style={{ ...tdStyle, color: (stats.hit_rate ?? 0) > 0.5 ? "#10b981" : "#ef4444" }}>
                  {pct(stats.hit_rate)}
                </td>
                <td style={{ ...tdStyle, color: (stats.avg_return ?? 0) > 0 ? "#10b981" : "#ef4444" }}>
                  {pct(stats.avg_return)}
                </td>
                <td style={{ ...tdStyle, color: (stats.avg_alpha ?? 0) > 0 ? "#10b981" : "#ef4444" }}>
                  {pct(stats.avg_alpha)}
                </td>
                <td style={tdStyle}>{stats.sharpe?.toFixed(2) ?? "N/A"}</td>
                <td style={tdStyle}>{stats.count ?? 0}</td>
                <td style={{ ...tdStyle, color: "#10b981" }}>{pct(stats.max_return)}</td>
                <td style={{ ...tdStyle, color: "#ef4444" }}>{pct(stats.min_return)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Quintile returns */}
      {result.quintile_returns && Object.keys(result.quintile_returns).length > 0 && (
        <div>
          <div style={{ fontWeight: 600, fontSize: "0.82rem", marginBottom: "0.5rem" }}>分组收益（因子值低→高）</div>
          {Object.entries(result.quintile_returns).map(([horizon, quintiles]) => (
            <div key={horizon} style={{ marginBottom: "0.75rem" }}>
              <div style={{ fontSize: "0.72rem", color: "#64748b", marginBottom: "0.3rem" }}>{horizon}</div>
              <div style={{ display: "flex", gap: "0.4rem" }}>
                {quintiles.map((q) => {
                  const ret = q.avg_return;
                  const bg = ret == null ? "#f1f5f9" : ret > 0 ? `rgba(16,185,129,${Math.min(0.3, Math.abs(ret) * 10)})` : `rgba(239,68,68,${Math.min(0.3, Math.abs(ret) * 10)})`;
                  return (
                    <div key={q.quintile} style={{
                      flex: 1,
                      background: bg,
                      borderRadius: "0.375rem",
                      padding: "0.5rem",
                      textAlign: "center",
                      fontSize: "0.72rem",
                    }}>
                      <div style={{ fontWeight: 600, marginBottom: "0.2rem" }}>{q.quintile}</div>
                      <div style={{ color: (ret ?? 0) > 0 ? "#065f46" : "#991b1b" }}>
                        {pct(ret)}
                      </div>
                      <div style={{ color: "#64748b", fontSize: "0.65rem" }}>n={q.count}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: "0.5rem 0.75rem",
  textAlign: "left",
  fontWeight: 600,
  fontSize: "0.72rem",
  color: "#64748b",
};

const tdStyle: React.CSSProperties = {
  padding: "0.45rem 0.75rem",
  textAlign: "left",
};

function ThresholdSlider({
  factorName,
  paramKey,
  value,
  meta,
  onChange,
}: {
  factorName: string;
  paramKey: string;
  value: number;
  meta: ThresholdMeta;
  onChange: (factorName: string, key: string, value: number) => void;
}) {
  const formatValue = (v: number) => {
    if (meta.unit === "元") {
      if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(1)}亿`;
      if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
      return String(v);
    }
    return `${v}${meta.unit}`;
  };

  return (
    <div style={{ padding: "0.5rem 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.3rem" }}>
        <label style={{ fontSize: "0.78rem", color: "#374151" }}>{meta.label}</label>
        <span style={{ fontSize: "0.78rem", fontWeight: 600, color: "#2563eb" }}>
          {formatValue(value)}
        </span>
      </div>
      <input
        type="range"
        min={meta.min}
        max={meta.max}
        step={meta.step}
        value={value}
        onChange={(e) => onChange(factorName, paramKey, Number(e.target.value))}
        style={{ width: "100%", accentColor: "#2563eb" }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.65rem", color: "#94a3b8" }}>
        <span>{formatValue(meta.min)}</span>
        <span>{formatValue(meta.max)}</span>
      </div>
    </div>
  );
}
