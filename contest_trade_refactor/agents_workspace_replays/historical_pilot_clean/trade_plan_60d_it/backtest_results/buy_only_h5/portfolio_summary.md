# Portfolio Simulation Report

Generated: 2026-08-17 15:44:52

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
Avg return/trade: -2.24%
Avg winner: 7.04%
Avg loser: -8.42%
Total P&L: -10,143.91
Strategy return: -1.01%
Max drawdown: -1.37%
Profit factor: 0.38

## Trades

| trigger_time        |   symbol | signal_group   | signal_tier   |   entry_date |   entry_price |   shares |   buy_cost |   position_weight_pct |   exit_date |   exit_price |   days_held |   gross_return_pct |      pnl |   fees |   return_after_cost_pct |   max_gain_pct |   max_loss_pct | trade_plan_pass   | trade_plan_reject_reasons                  |
|:--------------------|---------:|:---------------|:--------------|-------------:|--------------:|---------:|-----------:|----------------------:|------------:|-------------:|------------:|-------------------:|---------:|-------:|------------------------:|---------------:|---------------:|:------------------|:-------------------------------------------|
| 2026-06-23 18:00:00 |   000831 | buy_passed     | B             |     20260624 |         59.13 |      900 |    53243.6 |                 5.324 |    20260630 |        55.46 |           5 |            -6.2067 | -3379.52 |  76.52 |                 -6.3473 |         1.2177 |       -10.6038 | False             | ['rr_below_1.0']                           |
| 2026-06-24 18:00:00 |   000831 | buy_passed     | B             |     20260625 |         57.68 |      900 |    51938   |                 5.194 |    20260701 |        53.5  |           5 |            -7.2469 | -3836.11 |  74.11 |                 -7.3859 |         2.2538 |        -8.3564 | False             | ['rr_below_1.0']                           |
| 2026-06-29 18:00:00 |   688008 | buy_passed     | B             |     20260630 |        296.27 |      100 |    29641.8 |                 2.964 |    20260701 |       322.77 |           5 |             8.9445 |  2602.91 |  47.09 |                  8.7812 |        12.2321 |        -2.2446 | False             | ['rr_below_1.0', 'rsi_above_70.0']         |
| 2026-07-22 18:00:00 |   688072 | buy_passed     | B             |     20260723 |        791.08 |      100 |    79147.6 |                 7.915 |    20260729 |       700.87 |           5 |           -11.4034 | -9130.64 | 109.64 |                -11.5362 |         3.5142 |       -17.6341 | False             | ['rr_below_1.0', 'volume_ratio_below_1.0'] |
| 2026-08-10 18:00:00 |   600183 | buy_passed     | B             |     20260811 |        135.8  |      500 |    67933.9 |                 6.793 |    20260814 |       143.21 |           4 |             5.4566 |  3599.45 | 105.55 |                  5.2984 |        11.8557 |        -1.5758 | True              | nan                                        |

## Equity curve (at exit dates)

| date     |     equity |      pnl |   drawdown_pct |
|:---------|-----------:|---------:|---------------:|
| START    |      1e+06 |     0    |       0        |
| 20260630 | 996620     | -3379.52 |      -0.337952 |
| 20260701 | 995387     | -1233.2  |      -0.461272 |
| 20260729 | 986257     | -9130.64 |      -1.37434  |
| 20260814 | 989856     |  3599.45 |      -1.01439  |