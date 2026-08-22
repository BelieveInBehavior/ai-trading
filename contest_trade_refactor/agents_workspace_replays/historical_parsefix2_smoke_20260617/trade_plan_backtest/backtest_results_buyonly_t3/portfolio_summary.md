# Portfolio Simulation Report

Generated: 2026-08-17 16:57:37

Initial cash: 1,000,000.00
Commission rate per side: 0.0300%
Minimum commission per order: 5.00
Sell stamp duty: 0.0500%
Slippage: 2.00 bps per side
Minimum fill ratio: 0.50
Stop loss: -5.0%
Take profit: 8.0%
Enable stop/take: True

## Summary

Trades: 3
Won: 3
Lost: 0
Win rate: 100.0%
Avg return/trade: 7.89%
Avg winner: 7.89%
Avg loser: 0.0%
Total P&L: 14,900.34
Strategy return: 1.49%
Max drawdown: 0.0%
Profit factor: 14900.34

## Trades

| trigger_time        |   symbol | signal_group   | signal_tier   |   entry_date |   entry_price |   shares |   buy_cost |   position_weight_pct |   exit_date |   exit_price |   days_held |   gross_return_pct |     pnl |   fees |   return_after_cost_pct |   max_gain_pct |   max_loss_pct | trade_plan_pass   | trade_plan_reject_reasons          |
|:--------------------|---------:|:---------------|:--------------|-------------:|--------------:|---------:|-----------:|----------------------:|------------:|-------------:|------------:|-------------------:|--------:|-------:|------------------------:|---------------:|---------------:|:------------------|:-----------------------------------|
| 2026-06-17 18:00:00 |   000831 | buy_passed     | B             |     20260618 |         58.57 |     1200 |    70319.1 |                 7.032 |    20260622 |        64.52 |           3 |            10.1588 | 7027.43 | 112.57 |                  9.9936 |        14.1369 |        -0.1366 | False             | ['rr_below_1.0']                   |
| 2026-06-17 18:00:00 |   300398 | buy_passed     | B             |     20260618 |         46.53 |     1100 |    51208.6 |                 5.121 |    20260623 |        47.23 |           3 |             1.5044 |  692.46 |  77.54 |                  1.3522 |         8.7256 |        -2.2781 | False             | ['rr_below_1.0']                   |
| 2026-06-17 18:00:00 |   600206 | buy_passed     | B             |     20260618 |         38.79 |     1500 |    58214.1 |                 5.821 |    20260622 |        43.64 |           3 |            12.5032 | 7180.45 |  94.55 |                 12.3346 |        20.5465 |         0      | False             | ['rr_below_1.0', 'rsi_above_70.0'] |

## Equity curve (at exit dates)

| date     |      equity |      pnl |   drawdown_pct |
|:---------|------------:|---------:|---------------:|
| START    | 1e+06       |     0    |              0 |
| 20260622 | 1.01421e+06 | 14207.9  |              0 |
| 20260623 | 1.0149e+06  |   692.46 |              0 |