# 当前系统 T+1/T+3 回测总结

生成时间：2026-08-18 15:49:10

样本来源：
- `agents_workspace_replays/current_no_future_june17_30`（6/17~6/30 no-future replay）
- `agents_workspace_replays/current_system_0810_0813`（8/10~8/13 replay）
- 新入场质量/拥挤度使用 `StockOpportunityRanker._score_entry_quality` 离线重打分

## 样本量

- agents_workspace_replays/current_no_future_june17_30: 33 signals
- agents_workspace_replays/current_system_0810_0813: 24 signals

- 合并去重后: **57** signals

## 按信号组

                t1                  t3             
             count   mean median count  mean median
signal_group                                       
buy_passed      40  1.047  0.747    38  0.46  0.252
consensus       13 -0.401 -0.540    13  0.81 -0.360
watch            4 -1.519 -0.928     4 -3.09 -3.244

## 按持有规则

                   t1                  t3              
                count   mean median count   mean median
holding_rule                                           
T+1_2_fast_exit    14  1.190  0.867    14  1.581 -0.195
T+3_ok             43  0.324 -0.311    41 -0.158 -0.118

## entry_quality 分桶

         t1           t3       
      count   mean count   mean
eq_b                           
35~50     8  0.215     8  4.754
<35       6  2.491     6 -2.650
>=50     43  0.324    41 -0.158

## crowding 分桶

           t1           t3       
        count   mean count   mean
crowd_b                          
55~70      13  1.531    12  5.866
<55        40  0.035    39 -0.593
>=70        4  2.314     4 -7.911

## high-risk: entry_quality<35 & crowding>=70

trigger_date symbol_code symbol_name  entry_quality  crowding      t1       t3
    20260630      688721        龙图光罩           27.5      80.0 17.3559  -4.8983
    20260630      688372        伟测科技           27.5      80.0 -6.5263 -14.5789
