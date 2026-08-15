"""
Data Analysis Pipeline - Simple Sequential Implementation

No need for LangGraph or Loop pattern for linear pipelines.
Just straightforward async function composition.
"""

import json
import asyncio
import importlib
import re
import pandas as pd
from typing import List, Dict, Any, Awaitable, Callable, Optional
from pathlib import Path

from agents.prompts import (
    prompt_for_data_analysis_filter_doc,
    prompt_for_data_analysis_summary_doc,
    prompt_for_data_analysis_merge_summary,
)
from models.llm_model import GLOBAL_LLM
from utils.llm_utils import count_tokens
from config.config import cfg, WORKSPACE_ROOT
from utils.report_utils import generate_data_agent_report, refresh_combined_data_report


class DataAnalysisPipeline:
    """
    Simple pipeline for data analysis - no framework needed.

    Flow: Load Cache → Fetch Data → Filter & Summarize Batches → Merge → Save
    """

    def __init__(
        self,
        agent_name: str,
        source_list: List[str],
        bias_goal: str = "",
        final_target_tokens: int = 4000,
        max_concurrent_batches: int = 6,
        **kwargs
    ):
        self.agent_name = agent_name
        self.source_list = source_list
        self.bias_goal = bias_goal
        self.final_target_tokens = final_target_tokens
        self.max_concurrent_batches = max_concurrent_batches

        # Config parameters
        self.content_cutoff_length = kwargs.get("content_cutoff_length", 2000)
        self.batch_count = kwargs.get("credits_per_batch", 10) // 2 + 1
        self.title_selection_per_batch = 28000 // self.content_cutoff_length
        self.summary_target_tokens = 28000 // self.batch_count
        self.high_value_keep_ratio = kwargs.get("high_value_keep_ratio", 0.35)
        self.high_value_min_docs = kwargs.get("high_value_min_docs", 40)
        self.high_value_max_docs = kwargs.get("high_value_max_docs", 220)
        self.passthrough_summary = bool(kwargs.get("passthrough_summary", False))

        # Setup workspace
        self.factor_dir = WORKSPACE_ROOT / "factors" / agent_name
        self.factor_dir.mkdir(parents=True, exist_ok=True)

        # Initialize data sources
        self.data_sources = self._load_data_sources()

    def _load_data_sources(self):
        """Load data source instances"""
        sources = []
        for source_path in self.source_list:
            try:
                parts = source_path.split(".")
                class_name = parts[-1]
                module_name = ".".join(parts[:-1])

                module = importlib.import_module(module_name)
                source_class = getattr(module, class_name)
                sources.append(source_class())

                print(f"[{self.agent_name}] Loaded: {source_path}")
            except Exception as e:
                print(f"[{self.agent_name}] Error loading {source_path}: {e}")

        return sources

    async def run(
        self,
        trigger_time: str,
        on_result: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        Main pipeline execution - simple and straightforward.

        Returns a dict with: agent_name, trigger_time, context_string, references, etc.
        """
        print(f"[{self.agent_name}] Starting analysis for {trigger_time}")

        # Step 1: Try to load cached result
        cached = self._load_cache(trigger_time)
        if cached:
            print(f"[{self.agent_name}] Using cached result")
            return cached

        # Step 2: Fetch data from all sources
        data_df = await self._fetch_data(trigger_time, on_result=on_result)
        if data_df.empty:
            print(f"[{self.agent_name}] No data fetched")
            return self._empty_result(trigger_time)

        # Step 2.5: High-value news extraction layer
        data_df = self._select_high_value_news(data_df)
        print(f"[{self.agent_name}] High-value selection: {len(data_df)} docs kept")

        if self.passthrough_summary:
            final_summary = self._build_passthrough_summary(data_df)
            batch_results = [{
                "batch_id": 1,
                "summary": final_summary,
                "references": [],
                "success": True,
            }]
        else:
            # Step 3: Create batches
            batches = self._create_batches(data_df)
            print(f"[{self.agent_name}] Processing {len(batches)} batches...")

            # Step 4: Process batches in parallel
            batch_results = await self._process_batches(batches, trigger_time)

            # Step 5: Merge batch summaries
            final_summary = await self._merge_summaries(batch_results, trigger_time)

        # Step 6: Collect references
        references = self._collect_references(data_df, batch_results, final_summary)

        # Step 7: Build result
        result = {
            "agent_name": self.agent_name,
            "trigger_time": trigger_time,
            "source_list": self.source_list,
            "bias_goal": self.bias_goal,
            "context_string": final_summary,
            "references": references,
            "batch_summaries": [
                {
                    "batch_id": br["batch_id"],
                    "summary": br["summary"],
                    "references": br.get("references", [])
                }
                for br in batch_results if br.get("success")
            ],
        }

        # Step 8: Save cache and generate reports
        self._save_cache(trigger_time, result)
        self._generate_reports(trigger_time, result)

        print(f"[{self.agent_name}] Completed: {len(final_summary)} chars")
        return result

    async def _fetch_data(
        self,
        trigger_time: str,
        on_result: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> pd.DataFrame:
        """Fetch data from all sources"""
        data_dfs = []

        for source in self.data_sources:
            try:
                df = await source.get_data(trigger_time)

                df = self._normalize_source_dataframe(df)

                if not df.empty:
                    data_dfs.append(df)
                    print(f"[{self.agent_name}] Fetched {len(df)} from {source.__class__.__name__}")
                    if on_result:
                        rows = df.head(20).to_dict(orient="records")
                        preview = "\n\n".join(
                            f"{row.get('title', '')}\n"
                            f"{row.get('content', '')}\n"
                            f"relevance={row.get('market_relevance_score', 0)} "
                            f"signal={row.get('signal_event_type', '')}/{row.get('signal_direction', '')}"
                            for row in rows
                        )[:12000]
                        await on_result({
                            "agent_name": self.agent_name,
                            "source_name": source.__class__.__name__,
                            "trigger_time": trigger_time,
                            "context_string": preview,
                            "partial": True,
                        })
            except Exception as e:
                print(f"[{self.agent_name}] Error fetching from {source.__class__.__name__}: {e}")

        if not data_dfs:
            return pd.DataFrame()

        # Combine and add IDs
        combined_df = pd.concat(data_dfs, ignore_index=True)
        combined_df["id"] = range(1, len(combined_df) + 1)

        return combined_df

    def _normalize_source_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize source output and keep optional market-value metadata."""
        if df is None or df.empty:
            return pd.DataFrame()

        for col in ["title", "content", "pub_time"]:
            if col not in df.columns:
                df[col] = ""

        df["title"] = df["title"].fillna("").astype(str)
        df["content"] = df["content"].fillna("").astype(str)

        df = df[df["title"].str.strip() != ""]
        df = df[df["content"].str.strip() != ""]
        if df.empty:
            return df

        optional_cols = [
            "url",
            "market_relevance_score",
            "market_relevance_label",
            "market_relevance_reason",
            "signal_event_type",
            "signal_direction",
            "signal_confidence",
            "signal_rationale",
        ]
        for col in optional_cols:
            if col not in df.columns:
                df[col] = ""

        keep_cols = ["title", "content", "pub_time", *optional_cols]
        return df[keep_cols].copy()

    def _select_high_value_news(self, df: pd.DataFrame) -> pd.DataFrame:
        """Select high-value news for downstream LLM reasoning."""
        if df.empty:
            return df

        working_df = df.copy()
        working_df["doc_value_score"] = working_df.apply(self._compute_doc_value_score, axis=1)
        working_df = working_df.sort_values(
            by=["doc_value_score", "pub_time"],
            ascending=[False, False],
        )

        desired = int(len(working_df) * self.high_value_keep_ratio)
        keep_n = max(self.high_value_min_docs, desired)
        keep_n = min(keep_n, self.high_value_max_docs, len(working_df))

        # If data set is small, keep all to avoid over-pruning.
        if len(working_df) <= self.high_value_min_docs:
            keep_n = len(working_df)

        selected = working_df.head(keep_n).copy()
        selected = selected.sort_values(by=["pub_time"], ascending=[False]).reset_index(drop=True)
        return selected

    def _compute_doc_value_score(self, row: pd.Series) -> float:
        """
        Compute document value score prioritizing direct A-share trading relevance.

        Scoring tiers (highest to lowest):
        - Direct A-share company news (earnings, M&A, insider trading)
        - A-share sector/industry catalyst (policy, regulatory)
        - Macro data with direct China market impact (PBoC, CSRC, economic data)
        - Global macro with indirect China impact (Fed, trade data)
        - International news with no direct China market link
        - Weather, cultural, sports, social events (penalized)
        """
        title = str(row.get("title", ""))
        content = str(row.get("content", ""))
        text = f"{title} {content}"
        relevance = self._safe_float(row.get("market_relevance_score", 0.0))
        signal_confidence = self._safe_float(row.get("signal_confidence", 0.0))
        signal_direction = str(row.get("signal_direction", "")).lower()
        event_type = str(row.get("signal_event_type", "")).lower()

        score = 0.0

        # --- Tier 1: Direct A-share company identifiers (strongest signal) ---
        # Stock codes like 600519.SH, 000001.SZ, or 6-digit codes in Chinese context
        entity_hits = len(re.findall(r"\d{6}\.(?:SH|SZ|BJ)\b", text))
        entity_hits += len(re.findall(r"(?:股票代码|代码)[：:]?\s*\d{6}", text))
        if entity_hits > 0:
            score += min(25.0, 12.0 + entity_hits * 4.0)

        # --- Tier 2: A-share specific keywords (high value) ---
        # Direct company action keywords
        ashare_company_keywords = [
            "净利润", "营收", "业绩预告", "业绩快报", "年报", "季报", "中报",
            "回购", "增持", "减持", "定增", "配股", "并购", "重组", "借壳",
            "股权转让", "要约收购", "战略投资", "大宗交易", "龙虎榜",
            "涨停", "跌停", "ST", "摘帽", "戴帽", "退市",
            "分红", "送股", "转增", "除权", "复牌", "停牌",
        ]
        ashare_company_hits = sum(1 for kw in ashare_company_keywords if kw in text)
        score += min(20.0, ashare_company_hits * 4.0)

        # --- Tier 3: China policy/regulatory (high value) ---
        china_policy_keywords = [
            "证监会", "银保监", "央行", "国务院", "发改委", "财政部",
            "上交所", "深交所", "北交所", "中国人民银行",
            "降息", "降准", "加息", "逆回购", "MLF", "LPR", "SLF",
            "货币政策", "财政政策", "产业政策", "监管", "注册制",
            "IPO", "再融资", "减持新规", "转融通",
            "A股", "沪指", "深成指", "创业板", "科创板", "北证",
            "两融", "融资融券", "北向资金", "外资", "QFII",
        ]
        china_policy_hits = sum(1 for kw in china_policy_keywords if kw in text)
        score += min(20.0, china_policy_hits * 3.5)

        # --- Tier 4: China macro/sector catalysts (medium-high) ---
        china_macro_keywords = [
            "GDP", "CPI", "PPI", "PMI", "社融", "M2", "信贷",
            "进出口", "贸易顺差", "贸易逆差", "外汇储备",
            "房地产", "地产", "新能源", "半导体", "芯片", "人工智能",
            "光伏", "锂电", "军工", "医药", "消费", "白酒",
            "猪肉", "原油", "煤炭", "钢铁", "有色",
            "同比", "环比", "超预期", "不及预期",
            "目标价", "研报", "评级", "指引",
        ]
        china_macro_hits = sum(1 for kw in china_macro_keywords if kw in text)
        score += min(15.0, china_macro_hits * 2.5)

        # --- Tier 5: Global macro with China spillover (medium) ---
        global_china_keywords = [
            "美联储", "非农", "美债", "美元指数", "人民币汇率",
            "中美", "关税", "贸易战", "制裁", "出口管制",
            "港股", "恒生", "中概股", "黄金", "原油",
        ]
        global_china_hits = sum(1 for kw in global_china_keywords if kw in text)
        score += min(10.0, global_china_hits * 2.5)

        # --- Penalty: Irrelevant international / non-financial content ---
        irrelevant_keywords = [
            "世界杯", "奥运", "欧洲杯", "NBA", "英超", "西甲",
            "难民", "移民危机", "边境检查", "签证",
            "地震", "台风", "飓风", "洪水",
            "娱乐", "明星", "综艺", "选秀", "电影票房",
            "天气预报", "气温", "降雨",
            "食品安全", "自给率", "粮食安全",
        ]
        # Only penalize if there are NO China/A-share signals present
        irrelevant_hits = sum(1 for kw in irrelevant_keywords if kw in text)
        if irrelevant_hits > 0 and (ashare_company_hits + china_policy_hits + china_macro_hits) == 0:
            score -= min(15.0, irrelevant_hits * 5.0)

        # Detect purely international news with no China link
        intl_no_china_keywords = [
            "欧盟", "英国脱欧", "日本央行", "欧央行", "意大利",
            "法国", "德国", "巴西", "印度", "俄罗斯", "乌克兰",
        ]
        intl_hits = sum(1 for kw in intl_no_china_keywords if kw in text)
        china_link = any(kw in text for kw in ["中国", "A股", "人民币", "中美", "港股", "沪", "深"])
        if intl_hits > 0 and not china_link and (ashare_company_hits + china_policy_hits) == 0:
            score -= min(10.0, intl_hits * 3.0)

        # --- Upstream metadata bonuses (reduced weight, supplementary only) ---
        # market_relevance_score from data source keyword rules (typically 0-10+)
        score += min(10.0, relevance * 1.5)

        # signal_confidence only adds small bonus
        score += min(5.0, signal_confidence * 5.0)

        # signal_direction: small bonus, only meaningful with other context
        if signal_direction in {"bullish", "bearish"}:
            score += 3.0
        elif signal_direction == "neutral":
            score += 1.0

        # event_type bonus (reduced from before, now supplementary)
        event_bonus = {
            "monetary_policy": 5,
            "risk_event": 5,
            "earnings": 6,
            "regulation": 5,
            "corporate_action": 6,
            "other": 1,
        }
        score += event_bonus.get(event_type, 1)

        # Content length: mild bonus only if content has some A-share relevance
        if (ashare_company_hits + china_policy_hits + china_macro_hits) > 0:
            if len(content) > 220:
                score += 3.0
            if len(content) > 450:
                score += 2.0

        return round(max(0.0, score), 2)

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            text = str(value).strip()
            if not text:
                return default
            if text.endswith("%"):
                return float(text[:-1]) / 100.0
            return float(text)
        except Exception:
            return default

    def _create_batches(self, data_df: pd.DataFrame) -> List[tuple]:
        """Split data into batches"""
        total_docs = len(data_df)
        batch_size = total_docs // self.batch_count
        if total_docs % self.batch_count:
            batch_size += 1

        batches = []
        for i in range(self.batch_count):
            start_idx = i * batch_size
            end_idx = min((i + 1) * batch_size, total_docs)

            if start_idx >= total_docs:
                break

            batch_df = data_df.iloc[start_idx:end_idx]
            if not batch_df.empty:
                batches.append((i + 1, batch_df))

        return batches

    async def _process_batches(
        self, batches: List[tuple], trigger_time: str
    ) -> List[Dict[str, Any]]:
        """Process all batches in parallel"""
        semaphore = asyncio.Semaphore(self.max_concurrent_batches)

        async def process_one(batch_id, batch_df):
            async with semaphore:
                return await self._process_single_batch(
                    batch_id, batch_df, trigger_time
                )

        tasks = [process_one(bid, bdf) for bid, bdf in batches]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        batch_results = []
        for result in results:
            if isinstance(result, Exception):
                batch_results.append({
                    "batch_id": "unknown",
                    "success": False,
                    "error": str(result)
                })
            else:
                batch_results.append(result)

        return batch_results

    async def _process_single_batch(
        self, batch_id: int, batch_df: pd.DataFrame, trigger_time: str
    ) -> Dict[str, Any]:
        """Process one batch: filter titles → summarize content"""
        try:
            # Filter by title
            filtered_df = await self._filter_by_title(batch_df, trigger_time)

            # Summarize content
            summary = await self._summarize_content(filtered_df, trigger_time)

            # Extract references from summary
            ref_ids = [int(i) for i in re.findall(r'\[(\d+)\]', summary)]
            references = filtered_df[filtered_df["id"].isin(ref_ids)].to_dict(orient="records")

            return {
                "batch_id": batch_id,
                "success": True,
                "summary": summary,
                "references": references,
            }

        except Exception as e:
            return {
                "batch_id": batch_id,
                "success": False,
                "error": str(e)
            }

    async def _filter_by_title(
        self, batch_df: pd.DataFrame, trigger_time: str
    ) -> pd.DataFrame:
        """Use LLM to filter most valuable documents by title"""
        titles_to_select = min(self.title_selection_per_batch, len(batch_df))

        if len(batch_df) <= titles_to_select:
            return batch_df

        # Build context
        titles_context = ""
        for _, row in batch_df.iterrows():
            titles_context += f"ID: {row['id']}\nTitle: {row['title']}\nPublish Time: {row['pub_time']}\n\n"

        # Call LLM
        prompt = prompt_for_data_analysis_filter_doc.format(
            trigger_datetime=trigger_time,
            titles_to_select=titles_to_select,
            titles_context=titles_context,
            language=cfg.system_language,
        )

        response = await GLOBAL_LLM.a_run(
            [{"role": "user", "content": prompt}],
            verbose=False,
            thinking=False
        )

        # Parse selected IDs
        try:
            selected_ids = [
                int(x.strip())
                for x in response.content.strip().split(",")
                if x.strip().isdigit()
            ]
            filtered = batch_df[batch_df["id"].isin(selected_ids)]
            return filtered if not filtered.empty else batch_df.head(titles_to_select)
        except:
            return batch_df.head(titles_to_select)

    async def _summarize_content(
        self, batch_df: pd.DataFrame, trigger_time: str
    ) -> str:
        """Summarize document content"""
        if batch_df.empty:
            return "No valid content"

        # Build document context
        doc_context = ""
        for _, row in batch_df.iterrows():
            content = row["content"]
            if len(content) > self.content_cutoff_length:
                content = content[:self.content_cutoff_length] + "..."

            pub_time = row["pub_time"]
            if pub_time.endswith("23:59:59"):
                pub_time = pub_time.split(" ")[0]

            doc_context += (
                f"<doc id={row['id']}> "
                f"Title: {row['title']}\n"
                f"Publish Time: {pub_time}\n"
                f"Relevance Score: {row.get('market_relevance_score', '')}\n"
                f"Relevance Label: {row.get('market_relevance_label', '')}\n"
                f"Event Type: {row.get('signal_event_type', '')}\n"
                f"Direction: {row.get('signal_direction', '')}\n"
                f"Signal Confidence: {row.get('signal_confidence', '')}\n"
                f"Content: {content}</doc>\n"
            )

        # If short enough, return as-is
        if len(doc_context) <= self.summary_target_tokens and not self.bias_goal:
            return doc_context

        # Use LLM to summarize
        bias_instruction = (
            f"Focus on target '{self.bias_goal}' for targeted summary"
            if self.bias_goal
            else "Objectively summarize market dynamics and important events"
        )
        summary_style = "Goal-oriented Summary" if self.bias_goal else "Objective Summary"

        prompt = prompt_for_data_analysis_summary_doc.format(
            trigger_datetime=trigger_time,
            bias_instruction=bias_instruction,
            summary_style=summary_style,
            doc_context=doc_context,
            summary_target_tokens=self.summary_target_tokens,
            language=cfg.system_language,
        )

        response = await GLOBAL_LLM.a_run(
            [{"role": "user", "content": prompt}],
            verbose=False,
            max_tokens=self.summary_target_tokens
        )

        return response.content.strip()

    async def _merge_summaries(
        self, batch_results: List[Dict], trigger_time: str
    ) -> str:
        """Merge batch summaries into final summary"""
        successful = [br for br in batch_results if br.get("success")]

        if not successful:
            return "No valid summaries"

        # Combine summaries
        combined = "\n\n".join([
            f"Batch {br['batch_id']} Documents:\n{br['summary']}"
            for br in successful
        ])

        # If short enough, return as-is
        if len(combined) <= self.final_target_tokens and not self.bias_goal:
            return combined

        # Use LLM to merge
        goal_instruction = (
            f"Integrate information around goal '{self.bias_goal}'"
            if self.bias_goal
            else "Objectively integrate market information"
        )
        summary_focus = (
            "Highlight important facts related to the goal"
            if self.bias_goal
            else "Maintain objectivity and accuracy"
        )

        prompt = prompt_for_data_analysis_merge_summary.format(
            trigger_time=trigger_time,
            goal_instruction=goal_instruction,
            combined_summary=combined,
            summary_focus=summary_focus,
            final_description="Final Summary",
            final_target_tokens=self.final_target_tokens,
            language=cfg.system_language,
        )

        response = await GLOBAL_LLM.a_run(
            [{"role": "user", "content": prompt}],
            thinking=False,
            verbose=False,
            max_tokens=self.final_target_tokens
        )

        return response.content.strip()

    def _collect_references(
        self, data_df: pd.DataFrame, batch_results: List[Dict], final_summary: str
    ) -> List[Dict]:
        """Collect all referenced documents"""
        import re

        all_ref_ids = set()

        # From batch results
        for br in batch_results:
            if br.get("success"):
                for ref in br.get("references", []):
                    if isinstance(ref, dict) and "id" in ref:
                        all_ref_ids.add(ref["id"])

        # From final summary
        final_refs = re.findall(r'\[(\d+)\]', final_summary)
        all_ref_ids.update([int(r) for r in final_refs if r.isdigit()])

        # Get unique references
        if all_ref_ids:
            refs_df = data_df[data_df["id"].isin(all_ref_ids)]
            return refs_df.to_dict(orient="records")

        return []

    def _load_cache(self, trigger_time: str) -> Dict:
        """Load cached result"""
        filename = f'{trigger_time.replace(" ", "_").replace(":", "-")}.json'
        filepath = self.factor_dir / filename

        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass

        return None

    def _build_passthrough_summary(self, data_df: pd.DataFrame) -> str:
        """Use pre-formatted source content directly without LLM summarization."""
        docs = []
        for idx, row in enumerate(data_df.to_dict(orient="records"), start=1):
            title = str(row.get("title") or "Untitled").strip()
            pub_time = str(row.get("pub_time") or "").strip()
            content = str(row.get("content") or "").strip()
            relevance = row.get("market_relevance_score", "")
            label = row.get("market_relevance_label", "")
            event_type = row.get("signal_event_type", "")
            direction = row.get("signal_direction", "")
            confidence = row.get("signal_confidence", "")
            docs.append(
                f"<doc id={idx}> Title: {title}\n"
                f"Publish Time: {pub_time}\n"
                f"Relevance Score: {relevance}\n"
                f"Relevance Label: {label}\n"
                f"Event Type: {event_type}\n"
                f"Direction: {direction}\n"
                f"Signal Confidence: {confidence}\n"
                f"Content: {content}</doc>\n"
            )
        return f"Batch 1 Documents:\n{''.join(docs)}"

    def _save_cache(self, trigger_time: str, result: Dict):
        """Save result to cache"""
        filename = f'{trigger_time.replace(" ", "_").replace(":", "-")}.json'
        filepath = self.factor_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    def _generate_reports(self, trigger_time: str, result: Dict):
        """Generate markdown reports"""
        try:
            generate_data_agent_report(result)
            refresh_combined_data_report(trigger_time)
        except Exception as e:
            print(f"[{self.agent_name}] Error generating reports: {e}")

    def _empty_result(self, trigger_time: str) -> Dict:
        """Return empty result"""
        return {
            "agent_name": self.agent_name,
            "trigger_time": trigger_time,
            "source_list": self.source_list,
            "bias_goal": self.bias_goal,
            "context_string": "",
            "references": [],
            "batch_summaries": [],
        }


if __name__ == "__main__":
    async def test():
        pipeline = DataAnalysisPipeline(
            agent_name="test_pipeline",
            source_list=["data_source.sina_news.SinaNews"],
            final_target_tokens=2000,
        )

        result = await pipeline.run("2024-01-23 09:00:00")
        print(f"Result: {result['context_string'][:200]}...")

    asyncio.run(test())
