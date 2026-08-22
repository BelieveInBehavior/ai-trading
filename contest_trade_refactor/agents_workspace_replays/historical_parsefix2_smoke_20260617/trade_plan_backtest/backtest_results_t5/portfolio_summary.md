# Portfolio Simulation Report

Generated: 2026-08-17 16:57:33

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

Trades: 7
Won: 7
Lost: 0
Win rate: 100.0%
Avg return/trade: 9.46%
Avg winner: 9.46%
Avg loser: 0.0%
Total P&L: 45,418.04
Strategy return: 4.54%
Max drawdown: 0.0%
Profit factor: 45418.04

## Trades

| trigger_time        |   symbol | signal_group   | signal_tier   |   entry_date |   entry_price |   shares |   buy_cost |   position_weight_pct |   exit_date |   exit_price |   days_held |   gross_return_pct |     pnl |   fees |   return_after_cost_pct |   max_gain_pct |   max_loss_pct | trade_plan_pass   | trade_plan_reject_reasons                              |
|:--------------------|---------:|:---------------|:--------------|-------------:|--------------:|---------:|-----------:|----------------------:|------------:|-------------:|------------:|-------------------:|--------:|-------:|------------------------:|---------------:|---------------:|:------------------|:-------------------------------------------------------|
| 2026-06-17 18:00:00 |   000831 | buy_passed     | B             |     20260618 |         58.57 |     1200 |    70319.1 |                 7.032 |    20260622 |        64.52 |           5 |            10.1588 | 7027.43 | 112.57 |                  9.9936 |        14.1369 |        -0.1366 | False             | ['rr_below_1.0']                                       |
| 2026-06-17 18:00:00 |   300398 | buy_passed     | B             |     20260618 |         46.53 |     1100 |    51208.6 |                 5.121 |    20260624 |        52.57 |           5 |            12.9809 | 6560.58 |  83.42 |                 12.8115 |        18.8695 |        -2.6864 | False             | ['rr_below_1.0']                                       |
| 2026-06-17 18:00:00 |   600206 | buy_passed     | B             |     20260618 |         38.79 |     1500 |    58214.1 |                 5.821 |    20260622 |        43.64 |           5 |            12.5032 | 7180.45 |  94.55 |                 12.3346 |        20.5465 |         0      | False             | ['rr_below_1.0', 'rsi_above_70.0']                     |
| 2026-06-17 18:00:00 |   600459 | consensus      | NAN           |     20260618 |         26.03 |     3000 |    78129   |                 7.813 |    20260625 |        26.61 |           5 |             2.2282 | 1621.13 | 118.87 |                  2.0749 |         9.2585 |        -4.1875 | False             | ['rr_below_1.0']                                       |
| 2026-06-17 18:00:00 |   300709 | consensus      | NAN           |     20260618 |         60.95 |     1300 |    79274.6 |                 7.927 |    20260623 |        68.54 |           5 |            12.4528 | 9738.28 | 128.72 |                 12.2842 |        13.5357 |        -0.8203 | False             | ['rr_below_1.0']                                       |
| 2026-06-17 18:00:00 |   600301 | watch          | NAN           |     20260618 |         65.99 |     1200 |    79227.6 |                 7.923 |    20260622 |        69.37 |           5 |             5.122  | 3933.16 | 122.84 |                  4.9644 |         8.9104 |        -3.0156 | False             | ['low_signal_group', 'rr_below_1.0']                   |
| 2026-06-17 18:00:00 |   000657 | watch          | NAN           |     20260618 |         88.52 |      900 |    79707.8 |                 7.971 |    20260622 |        99.06 |           5 |            11.9069 | 9357.01 | 128.99 |                 11.7391 |        22.1193 |         0      | False             | ['low_signal_group', 'rr_below_1.0', 'rsi_above_70.0'] |

## Equity curve (at exit dates)

| date     |      equity |      pnl |   drawdown_pct |
|:---------|------------:|---------:|---------------:|
| START    | 1e+06       |     0    |              0 |
| 20260622 | 1.0275e+06  | 27498    |              0 |
| 20260623 | 1.03724e+06 |  9738.28 |              0 |
| 20260624 | 1.0438e+06  |  6560.58 |              0 |
| 20260625 | 1.04542e+06 |  1621.13 |              0 |