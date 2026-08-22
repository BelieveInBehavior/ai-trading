# Portfolio Simulation Report

Generated: 2026-08-16 15:56:56

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

Trades: 5
Won: 2
Lost: 3
Win rate: 40.0%
Avg return/trade: -1.04%
Avg winner: 8.45%
Avg loser: -7.37%
Total P&L: -2,081.03
Strategy return: -0.21%
Max drawdown: -1.52%
Profit factor: 0.91

## Trades

| trigger_time        |   symbol | signal_group   | signal_tier   |   entry_date |   entry_price |   shares |   buy_cost |   position_weight_pct |   exit_date |   exit_price |   days_held |   gross_return_pct |       pnl |   fees |   return_after_cost_pct |   max_gain_pct |   max_loss_pct | trade_plan_pass   |   trade_plan_reject_reasons |
|:--------------------|---------:|:---------------|:--------------|-------------:|--------------:|---------:|-----------:|----------------------:|------------:|-------------:|------------:|-------------------:|----------:|-------:|------------------------:|---------------:|---------------:|:------------------|----------------------------:|
| 2026-07-30 18:00:00 |   688825 | buy_passed     | B             |     20260731 |         58.2  |     2000 |     116458 |                11.646 |    20260803 |      52.51   |           3 |            -9.7766 | -11543.2  | 163.22 |                 -9.9119 |         4.1237 |       -12.8351 | True              |                         nan |
| 2026-08-04 18:00:00 |   000831 | buy_passed     | B             |     20260805 |         50.18 |     2300 |     115472 |                11.547 |    20260807 |      54.1944 |           3 |             8      |   9050.77 | 182.35 |                  7.8381 |        13.9697 |        -0.1196 | True              |                         nan |
| 2026-08-06 18:00:00 |   300502 | buy_passed     | B             |     20260807 |        430.34 |      200 |      86111 |                 8.611 |    20260810 |     408.823  |           3 |            -5      |  -4428.2  | 124.8  |                 -5.1424 |         4.2478 |        -9.7737 | True              |                         nan |
| 2026-08-10 18:00:00 |   601899 | buy_passed     | B             |     20260811 |         35.66 |     3300 |     117737 |                11.774 |    20260812 |      33.19   |           3 |            -6.9265 |  -8319.37 | 168.37 |                 -7.0661 |         0.3085 |        -7.1509 | True              |                         nan |
| 2026-08-13 18:00:00 |   000831 | buy_passed     | A             |     20260814 |         55.8  |     2600 |     145153 |                14.515 |    20260814 |      60.95   |           1 |             9.2294 |  13159    | 231.01 |                  9.0656 |         9.2294 |        -0.1254 | True              |                         nan |

## Equity curve (at exit dates)

| date     |     equity |       pnl |   drawdown_pct |
|:---------|-----------:|----------:|---------------:|
| START    |      1e+06 |      0    |       0        |
| 20260803 | 988457     | -11543.2  |      -1.15432  |
| 20260807 | 997508     |   9050.77 |      -0.249245 |
| 20260810 | 993079     |  -4428.2  |      -0.692065 |
| 20260812 | 984760     |  -8319.37 |      -1.524    |
| 20260814 | 997919     |  13159    |      -0.208103 |