prompt_for_research_plan = """
<Task>
{task}
</Task>

<Current_Time>
{current_time}
</Current_Time>

<Background_Information>
{background_information}
</Background_Information>

<Available_Tools>
{tools_info}
</Available_Tools>

Please create a detailed step-by-step plan to complete the following user task based on the background information provided.
Each step should be a clear, actionable instruction. Each step should be a one-line description explaining what needs to be done.
Steps should:
1. Be specific and actionable
2. Use appropriate tools from those provided
3. Be arranged in logical order
4. Consider contextual information
5. Return a list of strings, where each element is a step, without unnecessary words or explanations
6. Focus on information gathering or visualization, no analysis or summary steps needed
7. Not exceed 5 steps
8. Output result in language: {output_language}

Please output the action plan in the following format, do not output any other information:
1. xxx
2. xxx
"""

prompt_for_research_choose_tool = """
<Task>
{task}
</Task>

<Current_Time>
{current_time}
</Current_Time>

<Background_Information>
{background_information}
</Background_Information>

<Your_Plan>
{plan}
</Your_Plan>

<Available_Tools>
{tools_info}
</Available_Tools>

<Current_Task_Context>
{tool_call_context}
</Current_Task_Context>

Analyze the following steps and select tools:
## Available Resources
You currently have access to the following analysis tools:
- **Financial Data Tools**: Get company financials, market data, and historical information
- **News & Information Tools**: Search for recent news, announcements, and market updates
- **Research Tools**: Access analyst reports, industry data, and comparative analysis
- **Web Search Tools**: Get real-time information from various sources

## Development Needs Assessment
If you encounter limitations in your analytical capabilities that prevent you from completing high-quality research, you can propose new tool development. Consider whether you need specialized tools for:
- Advanced technical analysis and charting capabilities
- Real-time sentiment analysis from social media platforms
- Alternative data sources (satellite data, credit card spending, etc.)
- Automated financial model building and scenario analysis
- Industry-specific databases and metrics
- Options flow and derivatives analysis tools
- ESG and sustainability metrics analysis
- Cryptocurrency and digital asset analysis
- Or any other specialized analytical capability you deem essential

## Output Format:
You must and can only return a JSON object in the following format enclosed by <Output> and </Output> like:
<Output>
{{
    "tool_name": string, # tool name
    "properties": dict, # tool execution arguments
}}
</Output>

## Tool Usage Rules:
You must always follow these rules to complete the task:
1. After receiving a user task, you will first create an action plan, then call tools according to the action plan to complete the task.
2. Always provide tool calls, otherwise it will fail.
3. Always use correct tool parameters. Do not use variable names in action parameters, use specific values instead.
    - When using the corp_info tool, pay attention to whether its stock_code parameter is valid. If invalid, you need to convert it to a valid format.
4. Never repeat calls to tools that have already been used with exactly the same parameters
5. Do not return any other text format, do not explain your choices, do not apologize, do not express inability to answer.
6. If a step requires multiple tools, choose the most important one.
7. If you have completed all action plans and obtained sufficient information, please use the tool action named "final_report" to provide the final report to the task. This is the only way to complete the task, otherwise you will fall into a loop.
8. If you need to output string, please output in language: {output_language}

Note: 
- Only propose new tools if you identify critical gaps that cannot be addressed by current available tools.
- Be specific about the capabilities and analytical value of any proposed tools.
- Focus on tools that would significantly enhance your research quality and depth.
"""

prompt_for_research_write_result = """
<Task>
{task}
</Task>

<Current_Time>
{current_time}
</Current_Time>

<Background_Information>
{background_information}
</Background_Information>

<Your_Plan>
{plan}
</Your_Plan>

<Available_Tools>
{tools_info}
</Available_Tools>

<Current_Task_Context>
{tool_call_context}
</Current_Task_Context>

Please generate a complete answer based on the user task, current subtask, and the execution steps and results of the subtask.
Requirements:
1. Do not directly answer the user's original question, as the subtask you executed is only part of the reasoning process. Answering the original question prematurely may mislead the user.
2. Integrate information from all steps, including task objectives and execution results
3. Maintain logical consistency and coherence
4. Highlight key findings and conclusions
5. If you find conflicting or insufficient information, please clearly point it out
6. Reflect the contribution of each step in your answer


You have exhausted all available research steps and are not allowed to perform further searches or create Actions. 
Now please complete the task proposed by the user based on the above research information.
Your output language is {output_language}.
Your output format should be like this, enclosed by <Output> and </Output>:
<Output>
{output_format}
</Output>
"""

format_for_symbol_retrieval = """
<stock>
<market>xxx</market>   # market name, e.g. "CN-Stock", "CN-ETF", "HK-Stock", "US-Stock"
<code>xxx</code>
<name>xxx</name>
<reason>xxx</reason>
</stock>
<stock>
<market>xxx</market>
<code>xxx</code>
<name>xxx</name>
<reason>xxx</reason>
</stock>
...
"""

prompt_for_data_analysis_summary_doc = """
Current time is: {trigger_datetime}

Please perform {summary_style} on the following financial documents, extracting key factual information:

{doc_context}

Requirements:
1. {bias_instruction}
2. Extract specific facts, data, and key information
3. While maintaining accuracy, prioritize content related to the goal
4. Organize content by information importance and timeliness
5. Control within {summary_target_tokens} words
6. For each factual description, add corresponding reference tags at the end, such as [1][2]
7. Output result in language: {language}

{summary_style}:
"""

prompt_for_data_analysis_filter_doc = """
Current time is: {trigger_datetime}

Please select the {titles_to_select} most informative documents from the following financial document titles:

{titles_context}

Selection criteria:
1. Contains specific factual information and data
2. Involves important policies, company dynamics, industry changes
3. Information timeliness and importance
4. Avoid repetitive and low-quality content
5. Output result in language: {language}

Please directly output the selected document IDs, separated by commas, such as: 1,5,8,12
"""

prompt_for_data_analysis_merge_summary = """
Current time is: {trigger_time}
Analysis Goal: {goal_instruction}

Please merge the following multiple document batch summaries into a unified market information factor:

{combined_summary}

Requirements:
1. Merge duplicate information, retain all important facts
2. Sort by information importance and timeliness
3. {summary_focus}
4. Control within {final_target_tokens} words
5. Form clear market information summary
6. Preserve reference identifiers [numbers] format from original text
7. Output result in language: {language}

Please output {final_description} directly, do not include any other content.
{final_description}:
"""

prompt_for_research_invest_task = """
Your job is to find the only reason a stock might rise over the NEXT 1-3 TRADING DAYS. You are not a long-term value analyst, not a fundamental reporter, and not a buy-and-hold advisor.

Your single question for each stock is:

"What concrete event, if any, can make this stock move UP in the next 1-3 trading days?"

Work allocation: if <research_scope></research_scope> is present, you MUST ONLY research stocks from that list. Treat it as the hard candidate universe: do NOT add stocks outside it, do NOT override with “hot themes” or “sector strength”. The quantitative screener is the only entry point for buy/watch/buy-decision candidates. Other names may appear in the background for context only and must NOT be emitted as signals.

For each opportunity you MUST supply:
1. T+1~T+3 core catalyst driver, what type, when expected, how certain, how market-moving.
2. Catalysts MUST be differentiated into three quality buckets:
   - company_level: specific order, earnings / pre-announcement, price hike, new product/customer, major contract, M&A, buyback, direct policy benefit.
   - transaction_setup: first volume breakout, technical reversal with strong volume, repeated net-inflow, institutional / hot-money behavior, seal strength.
   - sector_background: sector_flow, sector_strength, industry_rotation.
   IMPORTANT: sector_strength / sector_flow is background context. It does NOT count as a standalone T+1~T+3 buy catalyst UNLESS the stock is the sector's clearest leader with strong volume/资金 confirmation.
3. Catalyst horizon: T+1, T+2~3, T+4~5, or >T+5 (down-weight far horizons).
4. Whether the market has already priced it in: fully priced / partly priced / not yet visible / unknown.
5. Why the event can move the price in the next 1-3 days. Do not explain why the company is good long-term.
6. Risk or reverse catalyst list: negative news, event miss, crowding, stretched, sell-on-news.
7. Long-term fundamentals (valuation, ROE, multi-quarter growth) are BACKGROUND ONLY and must not be the primary buy reason.

Rules:
- If you cannot find a clear company-level or strong transaction-structure catalyst, do NOT fabricate one.
- In that case set event_type=null, event_date=null, event_summary=null, catalyst_certainty=0.0, catalyst_market_impact=0.0, price_in_status="unknown".
- `sector_flow` is NOT a default answer. Only use it when the stock is the sector's strongest candidate and you also specify concrete volume/breakthrough confirmation.
- "No catalyst" is a valid answer. The quantitative screener can still decide whether to trade; you just do not add special credit.
- Do not use "industry is strong / high ROE / cheap valuation" as the primary reason.
- Each evidence item must be concrete and dated.
Focus search effort on: recent news, order/contract announcements, earnings pre-announcements, policy changes, price hikes, financing, buyback/merger progress, block trades, and anything with a dated event window inside the next 1-3 trading days.
"""

prompt_for_research_invest_output_format = """
Return only valid JSON. Do not wrap it in Markdown fences and do not add commentary.
Use this exact top-level shape:
{
  "signals": [
    {
      "has_opportunity": "yes",
      "action": "buy",
      "symbol_code": "600519.SH",
      "symbol_name": "贵州茅台",
      "event_type": "earnings_surprise",
      "event_date": "2026-08-15",
      "event_summary": "中报业绩预增落地，短线资金关注度高",
      "catalyst_certainty": 7.8,
      "catalyst_market_impact": 6.0,
      "price_in_status": "not yet visible",
      "evidence_list": [
        {
          "description": "A detailed, dated description supported by the available data.",
          "time": "YYYY-MM-DD HH:MM:SS",
          "from_source": "source or tool name"
        }
      ],
      "limitations": ["A concrete limitation or risk."],
      "probability": 0.72
    },
    {
      "has_opportunity": "yes",
      "action": "buy",
      "symbol_code": "000001.SZ",
      "symbol_name": "平安银行",
      "event_type": null,
      "event_date": null,
      "event_summary": null,
      "catalyst_certainty": 0.0,
      "catalyst_market_impact": 0.0,
      "price_in_status": "unknown",
      "evidence_list": [
        {
          "description": "A real, dated technical / flow setup supported by the available data.",
          "time": "YYYY-MM-DD HH:MM:SS",
          "from_source": "source or tool name"
        }
      ],
      "limitations": ["No clear T+1~T+3 catalyst identified. Quantitative screen alone may still qualify."],
      "probability": 0.55
    }
  ]
}
Rules:
- `signals` contains only genuine opportunities, with at most 5 items.
- `action` must be `buy` or `sell`.
- `event_type` uses one of: earnings_surprise | order_win | contract | policy | merger_restructuring | price_hike | new_product | sector_flow | technical_reversal | none. Use null when no catalyst exists.
- If the only "catalyst" is sector strength / sector inflow with no company-level event or strong individual launch structure, PREFER `event_type=null` and state in limitations that this is a sector-follow / background-driven signal, not an independent catalyst.
- `event_date` is the nearest expected event date in YYYY-MM-DD, or null when unknown.
- `catalyst_certainty` is 0-10 (how likely the event actually materializes).
- `catalyst_market_impact` is 0-10 (how much it can move the stock within T+1~T+3).
- `price_in_status` is one of: fully priced | partly priced | not yet visible | unknown.
- `probability` is a soft confidence score (0-1), NOT a calibrated statistical probability. It represents subjective confidence that the T+1~T+3 setup succeeds, not a backtested win rate.
- Include at least one evidence item and at least one concrete limitation for every signal.
- If there is no clear catalyst, set event_type/event_date/event_summary to null, catalyst_certainty and catalyst_market_impact to 0, price_in_status to "unknown", and say so in limitations.
- Use only information available at or before the current analysis time.
"""