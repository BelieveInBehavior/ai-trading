# 2026-06-17 parse-fix smoke + historical T3/T5 reality check

## 1. What we checked on 2026-06-17

- Reran full-market replay with:
  - `research_scope` split (forced each research agent to cover a slice of quantitative candidates)
  - `parse_json_signals` fixed to extract **all** `"signals"` arrays (duplicate-key bug)
  - malformed JSON fallback: partial signal objects + skip invalid fragments
- Result: 0 buys in old pipeline → 3 buys, 2 watch, 7 consensus.
- The new single-day portfolio (with plan stops/TP):
  - buy-only T3: 3/3 win, avg +7.89%, +1.49% portfolio
  - buy-only T5: 3/3 win, avg +11.71%

This day shows that the parsing/scope fix can surface good candidates (中国稀土 +9.99%, 有研新材 +12.33% T3).

## 2. Full existing history (52 mature signals, 2026-06-17..2026-08-13)

The fix does **not** change the historical conclusion.

Buy-only, close at horizon, no stop:
- T3: 7 trades, win 28.6%, avg -2.94%, total -0.53%
- T5: 7 trades, win 28.6%, avg -5.27%, total -1.62%

Buy-only with plan stop -5% / TP +8%:
- T3: 7 trades, win 42.9%, avg -1.76%
- T5: 7 trades, win 42.9%, avg -4.23%

All groups (buy+watch+consensus), close at horizon:
- T3: 41 trades, win 39.0%, avg -1.47%
- T5: 37 trades, win 27.0%, avg -4.92%

Raw signal-level T3/T5 across the 29-day sample:
- T3: n=49, win 36.7%, avg -2.46%
- T5: n=48, win 25.0%, avg -5.35%

## 3. What this tells us

1. The research parser + forced scope fixes a real pipeline bug (missed names from multiple `signals` keys / ignored quant pool).
2. But **fixing what gets into the research round does not make the current 3–5 day system profitable**.
3. The current "buy" gate still has too few trades and no persistent edge on either T3 or T5.

## 4. Next best steps (not yet run)

- A: Make the candidate gate stricter on `trade_plan_pass` / `rr_ok`, quit allowing `rr_below_1.0` or `rsi_above_70` through.
- B: Treat research-signal coverage as funnel fix only, then replace the entry rule with a proper momentum + liquidity 3-day model.
- C: Re-run parse-fix replay for remaining days to see whether coverage gain alone makes T3/T5 positive (likely no, given the above)).

