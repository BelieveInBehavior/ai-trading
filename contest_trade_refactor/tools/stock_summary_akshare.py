"""
Data Summary Based On Akshare
"""
import asyncio
import hashlib
from pathlib import Path
from pydantic import BaseModel, Field
from utils.akshare_utils import akshare_cached
from models.llm_model import GLOBAL_VISION_LLM
from tools.tool_utils import smart_tool
from tools.search_web import search_web
import pandas as pd
import numpy as np
from utils.date_utils import get_latest_completed_trading_date, get_trading_date_range

TOOL_HOME = Path(__file__).parent.resolve()
TOOL_CACHE = TOOL_HOME / "stock_summary_akshare_cache"
LLM_SUMMARY_TIMEOUT_SECONDS = 35.0
LLM_SUMMARY_MAX_TOKENS = 1600


def _fmt_value(value, fmt: str = ".2f") -> str:
    try:
        if value is None:
            return "NA"
        if isinstance(value, float) and np.isnan(value):
            return "NA"
        return format(value, fmt)
    except Exception:
        return "NA"


def get_stock_name_by_code(symbol, market):
    """Gets the stock name from its symbol and market using Akshare for CN-Stock."""
    try:
        if market == "CN-Stock":
            # Normalize symbol like 600519.SH -> 600519
            base_symbol = symbol.split(".")[0]
            df = akshare_cached.run("stock_info_a_code_name", func_kwargs={}, verbose=False)
            if df is not None and not df.empty:
                # Expect columns: code, name
                match = df[df.get('code') == base_symbol] if 'code' in df.columns else df[df.iloc[:, 0] == base_symbol]
                if match is not None and not match.empty:
                    # Prefer 'name' column if exists
                    if 'name' in match.columns:
                        return match.iloc[0]['name']
                    # Fallback to second column as name if schema differs
                    return match.iloc[0][1]
            return symbol
        elif market == "US-Stock":
            # Keep simple fallback for US; extend via Akshare if needed
            return symbol
        else:
            return symbol
    except Exception:
        return symbol


def _fetch_cn_kline(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    base_symbol = symbol.split(".")[0]
    df = akshare_cached.run(
        func_name="stock_zh_a_hist",
        func_kwargs={
            "symbol": base_symbol,
            "period": "daily",
            "start_date": start_date,
            "end_date": end_date,
            "adjust": "qfq"
        },
        verbose=False
    )
    if df is None or len(df) == 0:
        return pd.DataFrame()
    rename_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "turnover",
        "振幅": "amplitude",
        "涨跌幅": "change_percent",
        "涨跌额": "change_amount",
        "换手率": "turnover_rate"
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _compute_indicators(df: pd.DataFrame) -> dict:
    out = {}
    if df.empty:
        return out
    closes = df["close"].astype(float)
    out["ma5"] = closes.rolling(5).mean().iloc[-1]
    out["ma10"] = closes.rolling(10).mean().iloc[-1]
    out["ma20"] = closes.rolling(20).mean().iloc[-1]
    # RSI(14)
    delta = closes.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(gain).rolling(14).mean()
    roll_down = pd.Series(loss).rolling(14).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    out["rsi14"] = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else None
    # MACD (12,26,9)
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = (dif - dea) * 2
    out["macd_dif"] = float(dif.iloc[-1])
    out["macd_dea"] = float(dea.iloc[-1])
    out["macd_hist"] = float(macd.iloc[-1])
    # Bollinger (20, 2 std)
    ma20 = closes.rolling(20).mean()
    std20 = closes.rolling(20).std()
    out["boll_mid"] = float(ma20.iloc[-1]) if not np.isnan(ma20.iloc[-1]) else None
    out["boll_up"] = float((ma20 + 2*std20).iloc[-1]) if not np.isnan(std20.iloc[-1]) else None
    out["boll_dn"] = float((ma20 - 2*std20).iloc[-1]) if not np.isnan(std20.iloc[-1]) else None
    return out


def _describe_kline(df: pd.DataFrame, indicators: dict) -> str:
    if df.empty:
        return "无可用K线数据"
    last = df.iloc[-1]
    parts = [
        f"最新交易日: {last['date'].strftime('%Y-%m-%d') if 'date' in df.columns else ''}",
        f"收盘: {last['close']} 开盘: {last['open']} 最高: {last['high']} 最低: {last['low']}",
        f"5/10/20日均线: {_fmt_value(indicators.get('ma5'))} / {_fmt_value(indicators.get('ma10'))} / {_fmt_value(indicators.get('ma20'))}",
        f"RSI14: {_fmt_value(indicators.get('rsi14'))}",
        f"MACD: DIF {_fmt_value(indicators.get('macd_dif'), '.3f')}, DEA {_fmt_value(indicators.get('macd_dea'), '.3f')}, Hist {_fmt_value(indicators.get('macd_hist'), '.3f')}",
        f"布林带: 上 {_fmt_value(indicators.get('boll_up'))}, 中 {_fmt_value(indicators.get('boll_mid'))}, 下 {_fmt_value(indicators.get('boll_dn'))}",
    ]
    return "\n".join([p for p in parts if p])


def get_all_stock_data(market: str, symbol: str, stock_name: str, trigger_time: str) -> dict:
    if market != "CN-Stock":
        return {
            "kline_description": "暂不支持该市场",
            "technical_analysis": "",
            "financial_summary": "",
            "sector_analysis": "",
            "stock_moneyflow_analysis": "",
            "intraday_chart_base64": None,
            "kline_chart_base64": None,
        }
    end_date = get_latest_completed_trading_date(trigger_time)
    start_date, end_date = get_trading_date_range(
        end_date=end_date,
        count=90,
        include_end=True,
    )
    df = _fetch_cn_kline(symbol, start_date, end_date)
    indicators = _compute_indicators(df) if not df.empty else {}
    kline_desc = _describe_kline(df, indicators)
    tech_desc = (
        "技术指标摘要: MA5/10/20="
        f"{_fmt_value(indicators.get('ma5'))}/"
        f"{_fmt_value(indicators.get('ma10'))}/"
        f"{_fmt_value(indicators.get('ma20'))}; "
        f"RSI14={_fmt_value(indicators.get('rsi14'))}; "
        f"MACD(DIF/DEA/Hist)={_fmt_value(indicators.get('macd_dif'), '.3f')}/"
        f"{_fmt_value(indicators.get('macd_dea'), '.3f')}/"
        f"{_fmt_value(indicators.get('macd_hist'), '.3f')}; "
        f"布林(上/中/下)={_fmt_value(indicators.get('boll_up'))}/"
        f"{_fmt_value(indicators.get('boll_mid'))}/"
        f"{_fmt_value(indicators.get('boll_dn'))}"
    ) if indicators else "技术指标不足，无法计算"
    return {
        "kline_description": kline_desc,
        "technical_analysis": tech_desc,
        # 以下维度暂不从akshare直接获取，保留占位符
        "financial_summary": "暂不可用（Akshare基础财务接口未接入）",
        "sector_analysis": "暂不可用（板块资金流未接入）",
        "stock_moneyflow_analysis": "暂不可用（个股资金流未接入）",
        # 图像生成可后续接入，本次返回None
        "intraday_chart_base64": None,
        "kline_chart_base64": None,
    }


async def call_llm_for_comprehensive_analysis(prompt, intraday_chart_base64=None, kline_chart_base64=None):
    """Calls the LLM for a comprehensive analysis with text and images."""
    
    content = [{"type": "text", "text": prompt}]
    if intraday_chart_base64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{intraday_chart_base64}"}})
    if kline_chart_base64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{kline_chart_base64}"}})
    
    messages = [{"role": "user", "content": content}]
    response = await GLOBAL_VISION_LLM.a_run(
        messages,
        temperature=0.3,
        max_tokens=LLM_SUMMARY_MAX_TOKENS,
        verbose=False,
        thinking=False,
        max_retries=0,
        timeout=LLM_SUMMARY_TIMEOUT_SECONDS,
    )
    return response.content


def _build_fallback_analysis(symbol: str, stock_name: str, trigger_time: str, all_data: dict, news_analysis: str) -> str:
    news_text = str(news_analysis or "").strip()
    if len(news_text) > 1200:
        news_text = news_text[:1200] + "\n...（新闻内容已截断）"
    return f"""## 技术面摘要（规则兜底）

{stock_name}({symbol})  
分析时间: {trigger_time}

### K线与均线
{all_data.get('kline_description') or 'K线数据暂不可用'}

### 技术指标
{all_data.get('technical_analysis') or '技术指标暂不可用'}

### 新闻事件
{news_text if news_text else '相关新闻暂不可用'}

### 数据局限
LLM综合分析未在限定时间内完成；本结果使用已成功获取的K线、均线和新闻数据直接兜底生成。后续最终排序仍会单独补齐候选股MA20、涨跌幅、RSI、MACD等技术因子。"""


class StockSummaryInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. For CN-Stock use format like '600519.SH', for US-Stock use format like 'AAPL'.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


# --- Main Analysis Function (Refactored) ---
async def analyze_stock_basic_info(market, symbol, stock_name, trigger_time):
    """Main analysis function, redesigned for Akshare-available dimensions."""
    print("📊  Fetching K-line & indicators via Akshare...")
    all_data = get_all_stock_data(market, symbol, stock_name, trigger_time)
    print("✅  Data fetching complete.")

    # News data (optional)
    try:
        news_result = await search_web.ainvoke({"query": f"{stock_name}", "topk": 10, "trigger_time": trigger_time})
        news_analysis = '\n'.join(map(str, news_result)) if isinstance(news_result, list) else str(news_result)
        print("✅  News fetching complete.")
    except Exception as e:
        news_analysis = f"相关新闻获取失败: {e}"
        print(f"❌  News fetching failed: {e}")

    prompt_template = f"""请为{stock_name}({symbol})生成一份基于可用数据的股票技术分析报告。
分析时间: {trigger_time}

=== 数据输入（基于Akshare可用性精简）===
【K线数据与关键指标】
{all_data['kline_description']}
{all_data['technical_analysis']}

【新闻事件数据】
{news_analysis}

=== 分析要求 ===
1. 概述近期价格走势与波动特征
2. 结合均线、RSI、MACD、布林带等指标给出技术判断
3. 标注关键支撑/阻力位与潜在风险
4. 说明数据局限性（仅技术面、财务/资金面未接入）
"""
    if market == "US-Stock":
        prompt_template += "\n\n请用英文输出美股分析报告"

    print("🤖  Starting LLM technical analysis...")
    try:
        analysis_result = await call_llm_for_comprehensive_analysis(
            prompt_template, 
            all_data['intraday_chart_base64'], 
            all_data['kline_chart_base64']
        )
        return analysis_result
    except Exception as e:
        print(f"⚠️  LLM analysis skipped, returning K-line fallback: {type(e).__name__}: {e}")
        return _build_fallback_analysis(symbol, stock_name, trigger_time, all_data, news_analysis)


@smart_tool(
    description="""Get stock summarized technical info (Akshare-based). 仅支持A股，返回基于K线与技术指标的分析报告。""",
    args_schema=StockSummaryInput,
    max_output_len=4000,
    timeout_seconds=120.0
)
async def stock_summary(market: str, symbol: str, trigger_time: str) -> str:
    """Akshare-based stock summary tool, focusing on K-line and technical indicators."""
    if market not in ["CN-Stock"]:
        return f"错误：当前Akshare模式仅支持A股(CN-Stock)，传入: '{market}'。"

    if not TOOL_CACHE.exists():
        TOOL_CACHE.mkdir(parents=True, exist_ok=True)
    
    cache_key = f"{market}_{symbol}_{trigger_time.split(' ')[0]}"
    cache_file = TOOL_CACHE / f"{hashlib.md5(cache_key.encode()).hexdigest()}.txt"

    if cache_file.exists():
        return cache_file.read_text()
    else:
        stock_name = get_stock_name_by_code(symbol, market)
        result = await analyze_stock_basic_info(market, symbol, stock_name, trigger_time)
        cache_file.write_text(result)
        return result


if __name__ == "__main__":
    
    result = asyncio.run(stock_summary.ainvoke(
        { "market": "CN-Stock", 
         "symbol": "600519.SH", 
         "trigger_time": "2025-07-09 15:00:00"}))
         
    print(result)
