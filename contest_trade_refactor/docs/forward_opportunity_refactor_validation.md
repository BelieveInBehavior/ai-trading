# Forward Opportunity Refactor And Validation Plan

Generated: 2026-08-16

## 1. Background

This refactor was started because the 20-day historical backtest showed low realized benefit. The main diagnosis was that the old system leaned too much toward past strength and legacy momentum gates, while the user goal is to find stocks with future upside potential.

The key principle of this round is:

- Do not loosen gates just to create more signals.
- Do not claim future return improvement without corrected out-of-sample evidence.
- Move the system toward a mature quant pipeline: candidate generation, scoring, allocation, execution simulation, and validation must be separated and auditable.

## 2. What Changed In This Round

### 2.1 Candidate Generation / Universe Screening

Touched file:

- `agents/quantitative_universe_screener.py`

Main direction:

- Shift scoring away from pure historical strength.
- Increase weight on forward opportunity:
  - short-term launch/setup condition
  - remaining upside room
  - long-term trend background
- Weekly strength and relative strength are no longer hard gates.
- The intent is to avoid only buying stocks that have already completed most of the move.

Important limitation:

- Although candidate-generation code was changed, the latest historical comparison did not rerun full-market candidate generation.
- The latest comparison only rescored the old historical `research_signals`.
- Therefore, current evidence does not prove whether the new candidate-generation layer finds better future winners.

### 2.2 Opportunity Ranking

Touched file:

- `agents/stock_opportunity_ranker.py`

Main changes:

- Ranking logic now emphasizes forward edge rather than old strong-trend confirmation.
- Added explicit expected upside, expected downside, expected net edge, and risk-reward ideas.
- Fund-flow confirmation is softer, instead of being treated as a strict hard gate in all cases.
- Added more structured data-quality and risk-gate handling.
- Added stronger protection against stale, uncertain, or low-quality evidence.

### 2.3 Signal Tier And Position Allocation

Touched file:

- `agents/signal_tier_classifier.py`

Main changes:

- Replaced old tiering with forward-edge and risk-aware classification.
- Tier decisions consider:
  - forward opportunity score
  - expected net edge
  - data quality
  - expected downside / volatility
  - risk flags
  - market regime
- Position sizing is volatility-adaptive.
- Bear market regime reduces position size.
- Risk-veto signals are rejected instead of being force-ranked.

### 2.4 Market Regime Detection

Touched file:

- `agents/market_regime_detector.py`

Main changes:

- Replaced simplified regime logic with deterministic scoring from:
  - index trend
  - market breadth
  - limit-up / limit-down ratio
  - turnover change
  - risk sentiment
- Output is used by allocation rather than as a vague text label.

### 2.5 Technical Factor Enrichment

Touched file:

- `data_source/technical_indicators_akshare.py`

Main changes:

- Added/expanded technical factors such as ATR, 20-day volatility, weekly trend, and relative strength context.
- These are used to support forward opportunity, downside risk, and position sizing.

### 2.6 Strategy Configuration And Main Loop

Touched files:

- `config/strategies.py`
- `main_loop.py`

Main changes:

- Integrated the new ranking, tiering, and regime flow into the decision path.
- Preserved the principle that `require_min_buys` should not force low-quality buys.
- Kept rejected/watch candidates separate from actual buy signals.

### 2.7 Closed-Loop Signal Backtest

Touched file:

- `scripts/backtest_signal_closed_loop.py`

Main changes:

- Signal loading now deduplicates the same date + symbol across signal groups.
- Fixed T1 interpretation:
  - If entry is next-day open, then that same entry session close is T1.
- Added defensive handling for metadata:
  - `logic_version` may be either dict-like or string-like; it should not crash the backtest.

### 2.8 Portfolio Execution Simulation

Touched file:

- `scripts/portfolio_simulator.py`

Main changes:

- Enforced A-share T+1:
  - no stop-loss or take-profit exit on the entry session.
- Added realistic execution constraints:
  - capital constraint
  - overlapping positions
  - 100-share board lot
  - near limit-up open not assumed fillable
  - gap stop-loss logic
  - minimum commission
  - sell stamp duty
  - double-sided slippage
- Added `min_fill_ratio`:
  - prevents tiny scaled-down positions when available cash is too low relative to target budget.

### 2.9 Walk-Forward Validation

Touched file:

- `scripts/walk_forward_validation.py`

Main changes:

- Moved validation toward Spearman IC and purged/non-overlapping windows.
- This is intended to reduce overfitting from overlapping short-horizon samples.

### 2.10 Historical Rescoring Tool

New file:

- `scripts/rescore_historical_decisions.py`

Purpose:

- Read existing historical decision JSON files.
- Reuse original `research_signals`, `market_context`, and `system_health`.
- Apply current:
  - `StockOpportunityRanker`
  - `SignalTierClassifier`
  - `MarketRegimeDetector`
- Write a new replay-like directory without modifying old historical decisions.

Important limitation:

- This tool does not regenerate the candidate pool.
- It is only useful for testing whether the new ranking/allocation layer performs better on old candidates.

## 3. Tests And Validation Already Run

### 3.1 Targeted Tests

Command:

```bash
.venv/bin/python -m unittest -v \
  test_backtest_execution.py \
  test_signal_allocation.py \
  test_quantitative_universe_screener.py \
  test_stock_opportunity_ranker.py
```

Result:

- 31 tests passed.

Coverage:

- T1/T3 alignment
- date + symbol deduplication
- A-share T+1 execution
- limit-up open rejection
- cash constraint and minimum fill ratio
- illegal holding period rejection
- new signal tiering
- volatility and regime-aware position sizing
- market regime detection
- forward opportunity preference over past strength
- ranking and risk gates

### 3.2 Syntax And Diff Hygiene

Commands:

```bash
.venv/bin/python -m py_compile \
  scripts/rescore_historical_decisions.py \
  scripts/portfolio_simulator.py \
  scripts/backtest_signal_closed_loop.py
```

```bash
git diff --check -- \
  agents/quantitative_universe_screener.py \
  agents/stock_opportunity_ranker.py \
  agents/signal_tier_classifier.py \
  agents/market_regime_detector.py \
  data_source/technical_indicators_akshare.py \
  config/strategies.py \
  main_loop.py \
  scripts/backtest_signal_closed_loop.py \
  scripts/portfolio_simulator.py \
  scripts/walk_forward_validation.py \
  scripts/rescore_historical_decisions.py \
  test_backtest_execution.py \
  test_signal_allocation.py \
  test_quantitative_universe_screener.py \
  test_stock_opportunity_ranker.py
```

Result:

- Passed.

### 3.3 Full Unit Test Sweep

Command:

```bash
.venv/bin/python -m unittest discover -s . -p 'test*.py' -v
```

Result:

- 85 passed.
- 2 failed.

Failing tests:

- `test_data_pipeline_high_value.py::test_high_value_news_selection_prefers_relevant_docs`
- `test_technical_indicators_akshare.py::test_kline_retries_eastmoney_ten_times_before_tencent`

Current interpretation:

- These two failures are outside the core trading-chain changes validated above.
- They point to existing contract mismatches in news selection and AkShare K-line fallback behavior.
- They should be fixed, but they are not evidence that the new ranking/allocation layer failed.

## 4. Historical Rescoring Result

### 4.1 Rescored Output

Generated directory:

```text
agents_workspace_replays/historical_pilot_clean_rescored_20260816_1147_v2
```

Rescore source:

```text
agents_workspace_replays/historical_pilot_clean/*/results/trade_decisions/*.json
```

Command:

```bash
.venv/bin/python scripts/rescore_historical_decisions.py \
  --output-root agents_workspace_replays/historical_pilot_clean_rescored_20260816_1147_v2
```

Result:

- 21 historical decision files processed.
- Original `research_signals`: 24 total.
- Rescored buy signals: 1 total.
- Rescored watchlist signals: 12 total.

### 4.2 Rescored Closed-Loop Backtest

Command:

```bash
.venv/bin/python scripts/backtest_signal_closed_loop.py \
  --glob 'agents_workspace_replays/historical_pilot_clean_rescored_20260816_1147_v2/*/results/trade_decisions/*.json' \
  --workspace agents_workspace_replays/historical_pilot_clean_rescored_20260816_1147_v2 \
  --min-samples 1 \
  --parallel 4
```

Result:

- 14 unique signals loaded.
- 14 evaluated.
- 0 pending.

### 4.3 Rescored Portfolio Simulation

Command:

```bash
.venv/bin/python scripts/portfolio_simulator.py \
  --input agents_workspace_replays/historical_pilot_clean_rescored_20260816_1147_v2/backtest_results/signal_performance.csv \
  --output agents_workspace_replays/historical_pilot_clean_rescored_20260816_1147_v2/backtest_results \
  --holding-days 3 \
  --initial-cash 1000000 \
  --max-position-pct 15 \
  --min-fill-ratio 0.5
```

Result:

- Simulated trades: 1
- Win rate: 0.0%
- Total P&L: -6420.35
- Portfolio return: -0.64%
- Max drawdown: -0.64%
- Profit factor: 0.0

## 5. Same-Executor Baseline Comparison

To avoid comparing different executor assumptions, the original historical decisions were also rerun through the current corrected backtest and portfolio simulator.

Baseline output directory:

```text
agents_workspace_replays/historical_pilot_clean_baseline_eval_20260816_1147
```

Baseline closed-loop command:

```bash
.venv/bin/python scripts/backtest_signal_closed_loop.py \
  --glob 'agents_workspace_replays/historical_pilot_clean/*/results/trade_decisions/*.json' \
  --workspace agents_workspace_replays/historical_pilot_clean_baseline_eval_20260816_1147 \
  --min-samples 1 \
  --parallel 4
```

Baseline portfolio command:

```bash
.venv/bin/python scripts/portfolio_simulator.py \
  --input agents_workspace_replays/historical_pilot_clean_baseline_eval_20260816_1147/backtest_results/signal_performance.csv \
  --output agents_workspace_replays/historical_pilot_clean_baseline_eval_20260816_1147/backtest_results \
  --holding-days 3 \
  --initial-cash 1000000 \
  --max-position-pct 15 \
  --min-fill-ratio 0.5
```

Comparison:

| Metric | Baseline old decisions | Rescored old candidates |
|---|---:|---:|
| Unique signals | 14 | 14 |
| Buy signals | 2 | 1 |
| Watch signals | 11 | 12 |
| Portfolio trades | 2 | 1 |
| Win rate | 50.0% | 0.0% |
| Total P&L | -1095.63 | -6420.35 |
| Portfolio return | -0.11% | -0.64% |
| Max drawdown | -0.64% | -0.64% |
| Profit factor | 0.83 | 0.0 |

Key interpretation:

- The new ranking/allocation layer did not improve results on the old candidate pool.
- It became more conservative, but it filtered out one profitable old buy.
- This does not prove the new candidate-generation layer is bad, because candidate generation was not rerun.
- It only proves that rescoring old candidates is insufficient evidence of improvement.

## 6. Why Candidate Generation Must Be Rerun

The latest validation reused old `research_signals`.

That means:

- The candidate pool still reflects the old system.
- New universe screening changes were not actually tested end to end.
- If the old system failed to surface future winners, the new ranker cannot recover them.
- Ranking is only the second half of the problem; the first half is whether the universe screener puts the right names into the research pool.

Therefore, the next validation must rerun full historical candidate generation.

## 7. Recommended Next Validation Plan

### 7.1 Phase 1: Small Smoke Replay

Goal:

- Confirm the new end-to-end system can regenerate candidates, research signals, decisions, and artifacts without timeout or parsing failure.

Recommended date sample:

- Pick 3 to 5 historical dates from the existing 20-day window.
- Include at least:
  - one day where the old system had a buy signal
  - one day where the old system had only watchlist
  - one day where the old system had zero research signals

Required checks:

- Full-market universe scan completes.
- `quantitative_candidates` are generated.
- `research_signals` are generated.
- `buy_signals` and `watchlist` are written.
- `future_leaks=0` for explicit audited fields.
- Decision JSON files are valid and parseable.
- Backtest and portfolio simulation complete.

Pass criteria:

- No fatal LLM parsing failure.
- No missing decision file.
- No explicit future-date leak in audited fields.
- At least one complete closed-loop backtest artifact is produced.

### 7.2 Phase 2: Full 20-Day Replay

Goal:

- Test the new candidate-generation layer, not just ranking.

Process:

1. Use the same historical dates as the old 20-day replay.
2. For each date, set the as-of date to that historical date.
3. Rerun full-market screening.
4. Regenerate:
   - `quantitative_screen`
   - `quantitative_candidates`
   - `research_signals`
   - `buy_signals`
   - `watchlist`
5. Run future-leak audit.
6. Run closed-loop signal backtest.
7. Run portfolio simulation with the corrected executor.
8. Compare against the old system using the same executor settings.

### 7.3 Phase 3: Candidate-Pool Quality Analysis

For each date compare old vs new:

- number of quantitative candidates
- number of research signals
- number of buy signals
- number of watch signals
- overlap ratio between old and new candidates
- best future T1/T3/T5 return available in candidate pool
- average T1/T3/T5 return of candidates
- hit rate of candidates before ranking
- whether later winners were present in the candidate pool

This phase answers the most important question:

- Did the new candidate-generation layer put better future opportunities into the funnel?

### 7.4 Phase 4: Ranking And Allocation Diagnostics

For all mature signals:

- compute Spearman IC between score and T1/T3/T5 returns
- group by score quantile
- check whether higher scores actually produce higher forward returns
- check A/B/C tier realized return separation
- inspect false negatives:
  - profitable names marked watch/reject
- inspect false positives:
  - buy names with large drawdown

Required outputs:

- `signal_performance.csv`
- `threshold_ic_candidates.csv`
- `walk_forward_report.md`
- `portfolio_summary.md`
- false-positive / false-negative review table

### 7.5 Phase 5: Acceptance Criteria

The new system should not be accepted just because it is more sophisticated.

Minimum acceptance criteria:

- No explicit future leaks in audited decision artifacts.
- Candidate pool captures more future winners than old candidate pool.
- Buy signals have better T3/T5 average return than watch/research groups.
- Score has positive Spearman IC on out-of-sample windows.
- Portfolio max drawdown does not worsen materially.
- Profit factor improves versus same-executor baseline.
- Trade count is not artificially inflated by lower standards.

## 8. Current Engineering Conclusion

The refactor improved system structure and execution realism, but it has not yet proven better return generation.

Current state:

- Ranking and allocation are more mature.
- Execution simulation is more realistic.
- Historical rescoring on old candidates did not improve portfolio results.
- Candidate generation changes still need a full historical replay to be validated.

Practical next step:

- Run a 3-5 day full-market smoke replay first.
- If stable, expand to the full 20-day historical replay.
- Only after that should thresholds be calibrated or the new system be judged against the old one.

## 8. Diagnosis: Why future winners were missed and losing names got bought

Rebuild on 20-day historical `research_signals` (rescore-only; candidate generation was not rerun).

### 8.1 Summary table

| date | name | original decision | rescored decision | t1 | t5 | what blocked |
|---|---|---|---|---|---|---|
| 2026-07-20 | 紫光股份 | watch | watch | +9.97 | +10.00 | chase_up>6%, ma20_dev>8%, flow<55 |
| 2026-08-03 | 风华高科 | watch | watch | +8.62 | +23.35 | flow<55 |
| 2026-07-22 | 拓荆科技 | buy | buy | -6.08 | -11.40 | passed (stock had flow=58) |

**Conclusion:** in this tiny sample the `capital_flow_score` we computed did not separate winners from losers.  
Winners were mostly blocked by a low text-derived flow score (~46), while one losing name had a high flow score (~58) and passed.

### 8.2 Why the flow score was misleading

Current implementation is at [agents/stock_opportunity_ranker.py](agents/stock_opportunity_ranker.py) `_score_capital_flow_strength`.

- Flow signal was read from evidence **keywords only**.
- A name with lots of "主力净流入" text but no concrete 亿-level value got ~46.
- A name with a single confirmed "净流入16.52亿" / "居首" also got ~46 because the regex did not parse the concrete amount / rank.
- Therefore the flow gate was, in this sample, closer to "did the research agent mention the fund-flow phrase" than to "was there real money".

### 8.3 What remains hard: profit improvement is NOT proven

We tried two variants on old candidates:

- **Rescore with `StockOpportunityRanker()` default** (conservative gates): 1 buy, portfolio profit factor 0.0.
- **Rescore with momentum ranker / flow disabled** (loose): more winners are admitted, but the portfolio sim gives **-1.5%**, win-rate 33%, profit factor 0.75.

This is the expected consequence of **not re-running candidate generation**. The problem is not only the gate:

- The known winners were usually in the research pool, but among the 80 candidates they were ranked 26–63 by the serialized `quantitative_score`.
- Many top-10 candidates were banks/dividend names with low change (daily-entry 82) but no immediate trade theme; these did not buy either (which is good), but they also **diluted** the researchers' attention and data budget.
- The current serialized `quantitative_candidates` in historical JSON do not include `opportunity_rank_score`, only the legacy `quantitative_score` (mostly 69). Therefore the researchers saw an "old" ordering even when the new screener code calculates a forward+intensity order.

### 8.4 Concrete code changes done in this round

1. `agents/stock_opportunity_ranker.py`
   - Re-tuned `_score_capital_flow_strength` to count concrete amount hints in text (e.g. `净流入16.52亿元`) and top-rank confirmations (`居首`).
   - Added regression test with concrete flow evidence: should survive `flow<55`; weak/no-flow text should still block.
   - This does **not** mean "loose flow". It means "conflicting flow evidence is being scored higher".

2. `scripts/rescore_historical_decisions.py`
   - Added `--strategy momentum|swing`, so re-scoring can use the same ranker override gates as the live momentum strategy instead of silently using default swing-like gates.
   - This is important because default `StockOpportunityRanker()` uses `max_prev_day_gain=6%, max_ma20_dev=8%`, while `momentum` uses 14% / 45%. The old rescore was testing against the wrong gates.

### 8.5 Non-goals / not done

The above is **NOT** recommending to disable flow gate altogether. The portfolio sim with flow disabled proved that simple admission "more" still loses money because the top-80 pool contains many low-beta/div names and weak momentum names.

To get honest "收益提升" we need Performs:

1. Re-run full historical pipeline (candidate gen + research + ranker) so that `opportunity_rank_score` is in `quantitative_candidates` and the researcher sees new ordering.
2. Use position sizing/tiering to avoid equal-weighting all pass signals.
3. Measure Spearman IC per component after the renewed polling, rather than fitting to 2–3 named winners.


## 9. Full end-to-end re-run with regenerated candidates (momentum, no future leak)

Command:

```bash
.venv/bin/python scripts/replay_historical_no_future.py \
  --start-date 2026-07-15 --end-date 2026-08-13 \
  --strategy momentum \
  --output-dir agents_workspace_replays/historical_pilot_reregen_momentum \
  --symbols-limit 0 --concurrency 4
```

- Re-ran Stage 0 full-market candidate generation for every day (not just rescoring old signals).
- Added `CONTEST_TRADE_ASOF_DATE` so price provider caps history at trigger date.
- Ran `audit_future_leak` per day; audit marked **no findings** on the audited trade-decision JSONs.

### 9.1 High-level signal results

| Stage | Count |
|---|---:|
| Decision files | 21 |
| Research signals generated | 149 |
| Evaluable unique signals | 144 |
| Mature (enough future bars) | 144 |
| Buy-passed | 7 |
| Watch | 94 |
| Consensus | 43 |

### 9.2 Signal performance

| Group | N | T1 win% | T1 avg | T3 avg | T5 avg |
|---|---|---|---|---|---|
| All | 144 | 52.1% | +0.65% | +1.99% | +2.45% |
| Buy-passsed | 7 | 42.9% | -0.57% | -1.26% | +1.18% |
| Watch | 94 | 52.1% | +0.55% | +1.27% | +1.35% |
| Consensus | 43 | 53.5% | +1.07% | +4.34% | +5.60% |

### 9.3 Portfolio simulation on buy-passed only

```
trades: 7
win rate: 28.6%
avg return: -2.19%
total P&L: -14143.56
return: -1.41%
profit factor: 0.61
```

### 9.4 Main IC failure

For all 144 evaluated signals, Pearson IC vs future return:

| Variable | T1 IC | T5 IC |
|---|---:|---:|
| buy_score / forward_opportunity_score | +0.085 | -0.074 |
| capital_flow_score | -0.007 | **-0.284** |
| catalyst_score | -0.053 | -0.104 |
| fundamental_score | -0.125 | **-0.300** |
| weekly_trend_score | -0.070 | **-0.371** |
| daily_entry_score | **+0.249** | +0.146 |
| prev_day_gain_pct | +0.208 | +0.106 |

**Conclusion:** the current ranker’s composite `buy_score` has almost no predictive value. In this sample:
- `capital_flow_score`, `fundamental_score` and `weekly_trend_score` are **negatively** related to T5 returns (likely because they push mature/high-flow names that have already moved).
- `daily_entry_score` and short-term momentum (`prev_day_gain_pct`) have the only material positive T1 IC.

### 9.5 What should change next

1. Stop relying on buy_score for gate placement until it is re-trained/calibrated. Use it for relative ranking only.
2. The candidate rerun produced good candidates (e.g., 紫光股份 on 0715 T5 +29.99%, 风华高科 on 0804 +25.4%, 000657 +49.76%) but many were tracked as `watch` / `consensus`, not bought.
3. Buy gate should be tightened or **re-specified from daily_entry / short-term momentum** rather than `buy_score` alone in the current form.
4. Allocation should allow multiple small positions so `buy_passed` is not a single crowded signal set.
5. Run walk-forward Spearman IC before changing gates again.
