# First Board Continue 首板延续策略

独立策略包，与 strong_diverge 分离。

- 首板识别：前一交易日未涨停 + 今日涨停（`first_board_event`）。
- 首板质量：`first_board_quality_score`（封板、炸板、成交换手、价格位置、首板前动量、板块）。
- T+1 继续性确认：`first_board_continuation_confirmed`，只要求正常延续，不要求 weak-to-strong。
- 买入：`first_board_continuation_score` + `entry_quality_score` 双重门槛。
- 止损/持仓：T+1~T+3 结构 + 时间退出。

调整入口：`strategies/first_board_continue/strategy.yaml`
