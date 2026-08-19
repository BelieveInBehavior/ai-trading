"""动���出场管���器
���据技���指标、资金流���、���亏情���动���决定止损/止盈
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime


class ExitManager:
    """���理持���的出场逻���"""

    def __init__(self):
        # 止损/止盈配置���可后续从config���取���
        self.default_stop_loss_pct = -6.0  # 默���止损-8%
        self.default_take_profit_pct = 6.0  # 默认止盈+6%（T+1~T+3止盈优先）
        self.trailing_stop_trigger_pct = 4.0  # 盈���超过8%时启动移���止损
        self.trailing_stop_distance_pct = 5.0  # 移动���损距离最高点5%

    def evaluate_position(
        self,
        position: Dict[str, Any],
        current_price: float,
        technical_factor: Dict[str, Any],
        market_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        评估持仓是否���该出场

        Args:
            position: {
                "symbol_code": str,
                "symbol_name": str,
                "entry_price": float,
                "entry_date": str,
                "quantity": int,
                "signal_tier": str,  # A/B/C
                "highest_price": float,  # 持有期间最高价
            }
            current_price: 当前价���
            technical_factor: 当前技术因子
            market_context: 市场环境

        Returns:
            {
                "action": "hold" | "sell",
                "reason": str,
                "urgency": "normal" | "urgent",  # 是否需要紧急卖出
                "exit_score": float,  # ���场得分0-100，越高越应该卖
                "stop_loss_triggered": bool,
                "take_profit_triggered": bool,
                "reasons": List[str]
            }
        """
        entry_price = position.get("entry_price", current_price)
        highest_price = position.get("highest_price", current_price)
        signal_tier = position.get("signal_tier", "B")

        # ���新最高价
        if current_price > highest_price:
            highest_price = current_price
            position["highest_price"] = highest_price

        # 计算���益率
        current_return_pct = (current_price - entry_price) / entry_price * 100
        drawdown_from_peak_pct = (current_price - highest_price) / highest_price * 100

        reasons = []
        exit_score = 0.0
        stop_loss_triggered = False
        take_profit_triggered = False
        urgency = "normal"

        # 1. 固定止���检查
        stop_loss_threshold = self._get_tier_stop_loss(signal_tier)
        if current_return_pct <= stop_loss_threshold:
            stop_loss_triggered = True
            exit_score += 50
            urgency = "urgent"
            reasons.append(f"���发止���{stop_loss_threshold:.1f}%���当前{current_return_pct:.1f}%")

        # 2. ���定���盈检查
        take_profit_threshold = self._get_tier_take_profit(signal_tier)
        if current_return_pct >= take_profit_threshold:
            take_profit_triggered = True
            exit_score += 30
            reasons.append(f"达到止盈目标{take_profit_threshold:.1f}%，当���{current_return_pct:.1f}%")

        # 3. 移动止损���查���盈利后回撤）
        if current_return_pct > self.trailing_stop_trigger_pct:
            # ���经盈利超���8%，启动移���止损
            if drawdown_from_peak_pct <= -self.trailing_stop_distance_pct:
                exit_score += 40
                urgency = "urgent"
                reasons.append(
                    f"移动止损触发���从最���点{highest_price:.2f}回撤{abs(drawdown_from_peak_pct):.1f}%"
                )

        # 4. 技术面恶化检查
        tech_exit_score = self._check_technical_deterioration(technical_factor)
        if tech_exit_score > 0:
            exit_score += tech_exit_score
            reasons.append(f"技术���恶化评���+{tech_exit_score:.1f}")

        # 5. 市场环境恶化检查
        market_exit_score = self._check_market_deterioration(market_context)
        if market_exit_score > 0:
            exit_score += market_exit_score
            reasons.append(f"市场环境恶化+{market_exit_score:.1f}")

        # 6. 持有时间检查：T+1~T+2 优先，超过推荐持有天数就考虑换股
        holding_rule = position.get("holding_rule") or "T+1_2_fast_exit"
        entry_date = position.get("entry_date", "")
        if entry_date:
            holding_days = self._calculate_holding_days(entry_date)
            max_hold = position.get("recommended_holding_days", 2)
            if holding_rule == "T+3_ok":
                max_hold = max(int(max_hold), 3)
            if holding_days > max_hold:
                exit_score += min(6, holding_days - max_hold)
                reasons.append(f"持有{holding_days}天，超过推荐{max_hold}天")

        # 决策
        action = "sell" if exit_score >= 50 else "hold"

        return {
            "action": action,
            "reason": " | ".join(reasons) if reasons else "���续持���",
            "urgency": urgency,
            "exit_score": round(exit_score, 2),
            "current_return_pct": round(current_return_pct, 2),
            "drawdown_from_peak_pct": round(drawdown_from_peak_pct, 2),
            "stop_loss_triggered": stop_loss_triggered,
            "take_profit_triggered": take_profit_triggered,
            "reasons": reasons,
        }

    def _get_tier_stop_loss(self, tier: str) -> float:
        """根���信号���别返回���损阈���"""
        tier_config = {
            "A": -7.0,  # A级信号短期止损
            "B": -6.0,
            "C": -5.0,   # C级信���快速止损
        }
        return tier_config.get(tier, self.default_stop_loss_pct)

    def _get_tier_take_profit(self, tier: str) -> float:
        """根据信号���别返回止盈阈值"""
        tier_config = {
            "A": 8.0,  # A级信号短线止盈
            "B": 6.0,
            "C": 5.0,  # C���信号快���落袋为安
        }
        return tier_config.get(tier, self.default_take_profit_pct)

    def _check_technical_deterioration(
        self,
        factor: Dict[str, Any]
    ) -> float:
        """
        检查技术面���否恶化

        Returns:
            恶化得分���0-40），���高越应该卖���
        """
        score = 0.0

        # 1. ���线空头排列
        ma20_dev = factor.get("ma20_deviation_pct")
        if ma20_dev is not None and ma20_dev < -5:
            score += 15
            if ma20_dev < -10:
                score += 10

        # 2. 相对强度���弱
        rs_score = factor.get("relative_strength_score", 50)
        if rs_score < 45:
            score += 10
        if rs_score < 40:
            score += 10

        # 3. 周线趋���转弱
        weekly_score = factor.get("weekly_trend_score", 50)
        if weekly_score < 50:
            score += 10

        # 4. 温斯坦阶段恶化
        weinstein_stage = factor.get("weinstein_stage", "")
        if weinstein_stage in ["stage_3_topping", "stage_4_downtrend"]:
            score += 15

        return min(40, score)

    def _check_market_deterioration(
        self,
        market_context: Dict[str, Any]
    ) -> float:
        """
        检���市场环境是否恶化

        Returns:
            恶化���分（0-20）
        """
        score = 0.0

        trend = market_context.get("market_trend", "neutral")
        risk_sentiment = market_context.get("risk_sentiment", "neutral")

        if trend == "down":
            score += 10

        if risk_sentiment == "risk_off":
            score += 10

        return min(20, score)

    def _calculate_holding_days(self, entry_date: str) -> int:
        """计算���有天���"""
        try:
            entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
            today = datetime.now()
            return (today - entry_dt).days
        except Exception:
            return 0

    def batch_evaluate_positions(
        self,
        positions: List[Dict[str, Any]],
        prices: Dict[str, float],
        technical_factors: Dict[str, Dict[str, Any]],
        market_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        批���评估多个持���

        Args:
            positions: ���仓列���
            prices: {symbol_code: current_price}
            technical_factors: {symbol_code: factor}
            market_context: 市场���境

        Returns:
            评估结果列表
        """
        results = []

        for position in positions:
            code = position.get("symbol_code", "")
            current_price = prices.get(code)
            factor = technical_factors.get(code, {})

            if current_price is None:
                results.append({
                    "symbol_code": code,
                    "action": "hold",
                    "reason": "价���数据缺���",
                    "exit_score": 0,
                })
                continue

            evaluation = self.evaluate_position(
                position=position,
                current_price=current_price,
                technical_factor=factor,
                market_context=market_context,
            )

            evaluation["symbol_code"] = code
            evaluation["symbol_name"] = position.get("symbol_name", "")
            results.append(evaluation)

        # 按出���得分排序���最应���卖的在���）
        results.sort(key=lambda x: x.get("exit_score", 0), reverse=True)

        return results

    def format_exit_report(self, evaluations: List[Dict[str, Any]]) -> str:
        """生成可读的���场报���"""
        lines = [
            "=" * 60,
            "持仓出场评估���告",
            "=" * 60,
        ]

        sell_list = [e for e in evaluations if e.get("action") == "sell"]
        hold_list = [e for e in evaluations if e.get("action") == "hold"]

        if sell_list:
            lines.append(f"\n建议卖出 ({len(sell_list)}���):")
            for i, eval_result in enumerate(sell_list, 1):
                name = eval_result.get("symbol_name", "")
                code = eval_result.get("symbol_code", "")
                score = eval_result.get("exit_score", 0)
                return_pct = eval_result.get("current_return_pct", 0)
                urgency = eval_result.get("urgency", "normal")
                urgency_mark = "����" if urgency == "urgent" else "����"

                lines.append(
                    f"  {urgency_mark} {i}. {name}({code}) | "
                    f"���场分{score:.1f} | 收益{return_pct:+.1f}%"
                )
                lines.append(f"     原因: {eval_result.get('reason', '')}")

        if hold_list:
            lines.append(f"\n继续持��� ({len(hold_list)}个):")
            for i, eval_result in enumerate(hold_list, 1):
                name = eval_result.get("symbol_name", "")
                code = eval_result.get("symbol_code", "")
                return_pct = eval_result.get("current_return_pct", 0)

                lines.append(
                    f"  {i}. {name}({code}) | 收益{return_pct:+.1f}%"
                )

        lines.append("=" * 60)
        return "\n".join(lines)
