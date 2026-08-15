# Walk-Forward Validation

Generated: 2026-08-15 10:53:47
Folds: 1

## Factors sorted by avg test IC

| factor | folds | avg_test_ic | min_test_ic | max_test_ic | sign_consistent | avg_test_topQ_ret |
|---|---|---|---|---|---|---|
| capital_flow_score | 1 | 0.2551 | 0.2551 | 0.2551 | yes | nan |
| prev_day_gain_pct | 1 | 0.2293 | 0.2293 | 0.2293 | yes | -0.8166 |
| risk_reward_score | 1 | 0.2134 | 0.2134 | 0.2134 | yes | nan |
| tradeability_score | 1 | 0.1718 | 0.1718 | 0.1718 | yes | nan |
| weekly_trend_score | 1 | 0.1175 | 0.1175 | 0.1175 | yes | -0.5964 |
| data_quality_score | 1 | -0.2825 | -0.2825 | -0.2825 | yes | nan |
| market_regime_score | 1 | -0.2825 | -0.2825 | -0.2825 | yes | nan |
| relative_strength_score | 1 | -0.3595 | -0.3595 | -0.3595 | yes | -1.0132 |
| probability_value | 1 | -0.4387 | -0.4387 | -0.4387 | yes | nan |
| catalyst_score | 1 | -0.4762 | -0.4762 | -0.4762 | yes | nan |
| ma20_deviation_pct | 1 | -0.5737 | -0.5737 | -0.5737 | yes | -0.8166 |
| buy_score | 1 | -0.6291 | -0.6291 | -0.6291 | yes | nan |
| daily_entry_score | 1 | -0.8709 | -0.8709 | -0.8709 | yes | -2.1298 |

## Fold details

|   fold |   train_start |   train_end |   test_start |   test_end | factor                  |   train_n |   test_n | train_ic   |   test_ic | train_top_quartile_avg   |   test_top_quartile_avg |
|-------:|--------------:|------------:|-------------:|-----------:|:------------------------|----------:|---------:|:-----------|----------:|:-------------------------|------------------------:|
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | buy_score               |         5 |       22 |            |   -0.6291 |                          |                nan      |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | probability_value       |         5 |       22 |            |   -0.4387 |                          |                nan      |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | weekly_trend_score      |         5 |       22 |            |    0.1175 |                          |                 -0.5964 |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | relative_strength_score |         5 |       22 |            |   -0.3595 |                          |                 -1.0132 |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | daily_entry_score       |         5 |       22 |            |   -0.8709 |                          |                 -2.1298 |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | catalyst_score          |         5 |       22 |            |   -0.4762 |                          |                nan      |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | capital_flow_score      |         5 |       22 |            |    0.2551 |                          |                nan      |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | market_regime_score     |         5 |       22 |            |   -0.2825 |                          |                nan      |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | risk_reward_score       |         5 |       22 |            |    0.2134 |                          |                nan      |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | tradeability_score      |         5 |       22 |            |    0.1718 |                          |                nan      |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | data_quality_score      |         5 |       22 |            |   -0.2825 |                          |                nan      |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | ma20_deviation_pct      |         5 |       22 |            |   -0.5737 |                          |                 -0.8166 |
|      1 |      20260808 |    20260808 |     20260811 |   20260812 | prev_day_gain_pct       |         5 |       22 |            |    0.2293 |                          |                 -0.8166 |