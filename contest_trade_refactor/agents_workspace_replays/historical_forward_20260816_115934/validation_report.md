# Forward Opportunity Refactor — Full-Rerun Validation Report

Generated: 2026-08-16 12:31:21
Replay dir: `agents_workspace_replays/historical_forward_20260816_115934`

## Commands / Pipeline
- Reran full-market momentum replay for the same 22 trading dates as old `historical_pilot_clean` (20260715–20260813), strategy `momentum`, `CONTEST_TRADE_ASOF_DATE` set per day.
- Used `scripts/replay_historical_no_future.py --no-audit` so raw decision JSONs could be future-leak audited without pre-redaction.
- Ran `scripts/audit_future_leak.py` on raw decisions.
- Ran `scripts/backtest_signal_closed_loop.py` and `scripts/portfolio_simulator.py` on the new replay outputs.

## 1. End-to-End Stability
- All 22 date directories produced a `results/trade_decisions/*.json` and a status=ok `replay_manifest.jsonl`.
- No fatal LLM parsing failure; warnings observed:
  - `thx_news_crawl` frontend/Playwright launch failure (non-fatal).
  - `search_web` Doubao/Volcengine API returns `code=%s message=%s` (non-fatal).
  - occasional `Tool selection error` in research agents.
- Excerpt: non-fatal warnings, not fatal errors.

## 2. Candidate Generation Did Rerun With New Logic
- Every new decision JSON contains `quantitative_candidates` (80 per day).
- New candidates expose new fields:
  - `forward_opportunity_score` present on all 80 candidates each day.
  - `legacy_trend_score` present (`None` in old artifacts).
- Candidate pool composition changed materially vs old candidate pool:
  - Overlap across 22 dates: 943/1680 (56%); new-only 737 (44%).
  - Old candidate names that produced signals/buys are often absent from the new candidate pool (see below).

## 3. Signal Volume Collapsed
| metric | old replay | new replay |
|---|---:|---:|
| research_signals | 24 | 4 |
| buy_signals | 2 | 0 |
| watchlist | 11 | 3 |
| candidate avg fwd score | n/a (old had no fwd) | ~80 / day |
- New candidate pool contains 80/day, but research agents only emitted 4 signals total across 22 days.
- The new universe screener changes the pool to mostly high `core_buy` names with high forward_opportunity_score that are NOT the topics/theme stocks the LLM agents actively pursue (e.g., AI/光模块/通信). The agents' researched names are often filtered out, so output becomes nearly zero.
- Examples:
  - 20260722 old `688072.SH` (拓荆科技) was a buy signal; it is NOT in new candidate pool.
  - 20260810 old `600183.SH` (生益科技) was a buy signal; it is NOT in new candidate pool.
  - 20260721 old watch `300502.SZ` (新易盛) is NOT in new candidate pool.
  - New top candidates for 20260722 are 威龙股份、新集能源、沃森生物、粤高速Ａ、羚锐制药 etc., not the AI/momentum theme agents target.

## 4. Future-Leak Audit (raw, no pre-redaction)
- 2 decision files out of 22 flag literal future dates:
  - `20260715` `data_factors[9]` = `web_search_market_supplement_agent` contains `2026-08-03 15:30`.
  - `20260811` `data_factors[2]` = `northbound_flow_agent` contains `2026-08-12` and `2026-08-13` text in the summary.
- All other 20 decision files had no raw future-leak findings.
- `scripts/replay_historical_no_future.py` normally pre-redacts these before audit, which would hide them. This raw audit shows web-search/northbound data sources still leak obvious literal future dates on these two dates.
- The future-leak audit only catches literal timestamps, not LLM world knowledge or cache contamination, so the result is still conservative but not bullet-proof.

## 5. Closed-Loop Backtest (new signal set only)
- 4 unique signals loaded, all mature:
  - cons column: 000938 watch, 002185 consensus, 002384 watch, 000938 watch again.
- Overall T1: N=4, win 25%, avg -0.79%
- T3 avg -8.74%, T5 avg -4.34%.
- No buy_passed group.

## 6. Portfolio Simulation (corrected executor)
- New replay signals -> 0 tradable buy signals; simulated 0 trades.
- Portfolio return / max drawdown / profit factor all 0.0 because no buys were generated.
- Comparing to old baseline via same executor: baseline had 2 buy signals with 1 trade, -0.64% return, 0.0 profit factor. So the new candidate generation does NOT improve performance; it produces zero trades on this old 20-day window.

## 7. Candidate-Pool Forward-Return Probe (top20 on 4 dates)
Data using T+1/T+3/T+5 open->close (A-share):

| Date | Pool | t1_avg | t3_avg | t5_avg | t5_best | t1_win% |
|---|---|---|---|---|---|---|
| 20260715 | old | -1.20 | -10.72 | -8.76 | 11.0 | 25% |
| 20260715 | new | -0.11 | -11.00 | -7.42 | 11.0 | 30% |
| 20260716 | old | -7.65 | -7.50 | -10.02 | 9.91 | 10% |
| 20260716 | new | -8.06 | -8.63 | -10.33 | 14.12 | 10% |
| 20260728 | old | 1.18 | 0.15 | 2.63 | 21.35 | 70% |
| 20260728 | new | 0.72 | 0.61 | 1.78 | 21.35 | 65% |
| 20260810 | old | -0.58 | -1.08 | n/a | n/a | 30% |
| 20260810 | new | -0.94 | -1.32 | n/a | n/a | 40% |

The new forward-opportunity screening did NOT systematically improve realized top-20 candidate forward returns in this sample. It sometimes improved T1 hit rate but did not beat old pool's T5 best/avg at meaningful margin.

## 8. Acceptance vs Validation Plan
- End-to-end full replay: PASS (22/22 ok).
- Raw future-leak zero: FAIL for 2 files (07-15, 08-11) unless redacted.
- Candidate pool captures more future winners: NOT observed in probe; overlap changes materially but does not improve average/realized forward returns.
- Buy signals perform better than watch/research: N/A / IGN because 0 buy signals.
- Positive out-of-sample Spearman IC: not enough signals; cannot robustly evaluate.
- Portfolio max drawdown not worse: 0 trades => not tradeable; 0.0 drawdown on new but no alpha.
- Profit factor improves: FAIL (no trades / no improvement).
- Trade count not inflated: PASS (actually deflated to 0).

## Conclusion
The refactor is structurally working end-to-end and the universe screening definitely runs with the new forward-scoring fields, but on this 20-day same-executor comparison it fails the acceptance bar:
- It drops the old-buy names that were actually tradable in this window.
- It produces almost no research/watch/buy signals.
- No portfolio trades were generated, so there is no evidence of improved forward-return generation.
- There are still 2 raw future-leak artifacts from web/northbound data sources.
Additionally, the new forward-score routine adds enough risk: it may be too focused on room-score/extension (which favors low-vol defensive names) and breaks the intended momentum/短线 theme alignment with the LLM research agents.
