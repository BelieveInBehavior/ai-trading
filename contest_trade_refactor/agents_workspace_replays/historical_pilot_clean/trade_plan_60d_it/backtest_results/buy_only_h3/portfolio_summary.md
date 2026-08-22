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
Avg return/trade: -0.09%
Avg winner: 6.5%
Avg loser: -4.48%
Total P&L: -1,622.44
Strategy return: -0.16%
Max drawdown: -0.71%
Profit factor: 0.77

## Trades

| trigger_time        |   symbol | signal_group   | signal_tier   |   entry_date |   entry_price |   shares |   buy_cost |   position_weight_pct |   exit_date |   exit_price |   days_held |   gross_return_pct |      pnl |   fees |   return_after_cost_pct |   max_gain_pct |   max_loss_pct | trade_plan_pass   | trade_plan_reject_reasons                  |
|:--------------------|---------:|:---------------|:--------------|-------------:|--------------:|---------:|-----------:|----------------------:|------------:|-------------:|------------:|-------------------:|---------:|-------:|------------------------:|---------------:|---------------:|:------------------|:-------------------------------------------|
| 2026-06-23 18:00:00 |   000831 | buy_passed     | B             |     20260624 |         59.13 |      900 |    53243.6 |                 5.324 |    20260626 |        54.85 |           3 |            -7.2383 | -3927.97 |  75.97 |                 -7.3774 |         1.2177 |        -7.5427 | False             | ['rr_below_1.0']                           |
| 2026-06-24 18:00:00 |   000831 | buy_passed     | B             |     20260625 |         57.68 |      900 |    51938   |                 5.194 |    20260629 |        54.29 |           3 |            -5.8773 | -3125.82 |  74.82 |                 -6.0184 |         2.2538 |        -8.3564 | False             | ['rr_below_1.0']                           |
| 2026-06-29 18:00:00 |   688008 | buy_passed     | B             |     20260630 |        296.27 |      100 |    29641.8 |                 2.964 |    20260701 |       322.77 |           3 |             8.9445 |  2602.91 |  47.09 |                  8.7812 |        12.2321 |        -2.2446 | False             | ['rr_below_1.0', 'rsi_above_70.0']         |
| 2026-07-22 18:00:00 |   688072 | buy_passed     | B             |     20260723 |        791.08 |      100 |    79147.6 |                 7.915 |    20260727 |       791.9  |           3 |             0.1037 |   -36.74 | 118.74 |                 -0.0464 |         3.5142 |        -8.9852 | False             | ['rr_below_1.0', 'volume_ratio_below_1.0'] |
| 2026-08-10 18:00:00 |   600183 | buy_passed     | B             |     20260811 |        135.8  |      500 |    67933.9 |                 6.793 |    20260813 |       141.74 |           3 |             4.3741 |  2865.18 | 104.82 |                  4.2176 |        11.8557 |        -1.5758 | True              | nan                                        |

## Equity curve (at exit dates)

| date     |     equity |      pnl |   drawdown_pct |
|:---------|-----------:|---------:|---------------:|
| START    |      1e+06 |     0    |       0        |
| 20260626 | 996072     | -3927.97 |      -0.392797 |
| 20260629 | 992946     | -3125.82 |      -0.705379 |
| 20260701 | 995549     |  2602.91 |      -0.445088 |
| 20260727 | 995512     |   -36.74 |      -0.448762 |
| 20260813 | 998378     |  2865.18 |      -0.162244 |