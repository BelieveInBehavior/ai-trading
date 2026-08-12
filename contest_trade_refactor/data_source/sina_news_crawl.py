"""
sina news data crawler
"""
import asyncio
import aiohttp
import re
import json
import os
import time
from datetime import datetime
import random
import html
import pandas as pd
import sys
current_dir = os.path.dirname(__file__)
package_root = os.path.dirname(current_dir)
if package_root not in sys.path:
    sys.path.insert(0, package_root)
from data_source.data_source_base import DataSourceBase
from loguru import logger


class SinaNewsCrawl(DataSourceBase):
    def __init__(self, start_page=1, end_page=50):
        super().__init__("sina_news_crawl")
        self.start_page = start_page
        self.end_page = end_page
        # 使用你提供的完整URL格式，page/r/callback 将在请求时动态生成
        self.base_url = "http://feed.mix.sina.com.cn/api/roll/get"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            "Referer": "https://finance.sina.com.cn/",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self.all_items = []
        self.fetch_full_intro = False  # 默认关闭：仅标题筛选后再按需补充
        self.article_concurrency = 2  # 控制抓取文章页的全局并发

        # 漏斗层1：市场相关性筛选
        self.enable_relevance_filter = True
        self.relevance_min_score = 2
        self.max_enrich_ratio = 0.2
        self.max_enrich_items_per_page = 10

        # 可选：接入外部模型（同步函数或 async 函数）
        # model_relevance_fn(item) -> bool/int/float/dict
        # dict 约定支持: {"score": 0-10, "is_relevant": bool, "reason": str}
        self.use_model_for_relevance = False
        self.model_relevance_fn = None

        # 漏斗层3：结构化信号（可选模型）
        # model_signal_fn(item) -> dict
        self.use_model_for_signal = False
        self.model_signal_fn = None

        self.article_semaphore = None
        self.stats = {}
        
    async def fetch_page(self, session, page):
        """异步获取单个页面的数据"""
        params = {
            "pageid": 384,
            "lid": 2519,
            "k": "",
            "num": 50,
            "page": page
        }
        
        try:
            async with session.get(self.base_url, params=params, headers=self.headers, timeout=15) as response:
                text = await response.text()
                
                # 兼容 JSONP 与 纯 JSON
                m = re.search(r'^\s*[\w$]+\((.*)\)\s*;?\s*$', text.strip(), re.S)
                json_text = m.group(1) if m else text.strip()
                data = json.loads(json_text)
                
                # 提取items（仅保留指定字段）
                items = self.extract_items(data, page)

                if items:
                    await self.annotate_market_relevance(items)

                # 漏斗层2：仅对候选新闻补充描述
                if self.fetch_full_intro and items:
                    candidates = self.select_enrichment_candidates(items)
                    if candidates:
                        await self.enrich_items_with_full_intro(session, candidates)

                if items:
                    await self.annotate_market_signal(items)

                return items
                
        except Exception as e:
            logger.warning(f"Fetch page failed (page={page}): {e}")
            return []
    
    def extract_items(self, data, page):
        """提取新闻items，并裁剪为目标字段集"""
        try:
            if isinstance(data, dict):
                result = data.get("result", {})
                if isinstance(result, dict):
                    data_field = result.get("data", [])
                    if isinstance(data_field, list):
                        processed_items = []
                        for raw in data_field:
                            if not isinstance(raw, dict):
                                continue
                            # 选取第一个可用的时间字段
                            candidate_keys = [
                                "ctime", "intime", "mtime", "create_time", "createtime",
                                "pub_time", "pubTime", "pubdate", "pubDate", "time", "update_time"
                            ]
                            raw_time_value = None
                            for key in candidate_keys:
                                if key in raw and raw.get(key) not in (None, ""):
                                    raw_time_value = raw.get(key)
                                    break
                            publish_time = self.normalize_publish_time(raw_time_value)

                            # 本地可用的简介
                            intro_local = self.choose_best_intro_local(raw)
                            # 目标URL（优先PC，其次WAP，其次urls数组）
                            url = self.choose_best_url(raw)

                            # 仅保留指定字段
                            processed_items.append({
                                "title": raw.get("title") or raw.get("stitle") or "",
                                "intro": intro_local or "",
                                "enriched_intro": "",
                                "publish_time": publish_time,
                                "media_name": raw.get("media_name") or "",
                                "url": url or "",
                                "market_relevance_score": 0,
                                "market_relevance_label": "unknown",
                                "market_relevance_reason": "",
                                "signal_event_type": "",
                                "signal_direction": "",
                                "signal_confidence": "",
                                "signal_rationale": "",
                            })
                        return processed_items
            return []
        except Exception as e:
            print(f"第 {page} 页数据解析失败: {e}")
            return []
    
    def normalize_publish_time(self, raw_value):
        """将多种时间格式标准化为 'YYYY-MM-DD HH:MM:SS' 字符串"""
        try:
            if raw_value is None:
                return None
            # 数字时间戳（秒或毫秒）
            if isinstance(raw_value, (int, float)):
                timestamp = int(raw_value)
            elif isinstance(raw_value, str) and re.fullmatch(r"\d{10,13}", raw_value):
                timestamp = int(raw_value)
            else:
                # 尝试解析常见的时间字符串
                if isinstance(raw_value, str):
                    for fmt in [
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d %H:%M",
                        "%Y-%m-%d",
                        "%Y/%m/%d %H:%M:%S",
                        "%Y/%m/%d %H:%M",
                        "%Y/%m/%d",
                        "%Y年%m月%d日 %H:%M",
                        "%Y年%m月%d日",
                    ]:
                        try:
                            dt = datetime.strptime(raw_value.strip(), fmt)
                            return dt.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass
                # 无法识别则原样返回字符串
                return str(raw_value)

            # 毫秒与秒的区分
            if timestamp > 1_000_000_000_000:
                timestamp //= 1000
            elif 0 < timestamp < 10_000_000_000:
                pass
            else:
                # 非常规范围，保险起见取前10位
                timestamp = int(str(timestamp)[:10])

            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(raw_value)

    def choose_best_url(self, raw_item):
        """选择最合适的文章URL"""
        url = raw_item.get("url")
        if url:
            return url
        # 有些返回的 urls 是 JSON 字符串
        urls_field = raw_item.get("urls")
        if isinstance(urls_field, list) and urls_field:
            return urls_field[0]
        if isinstance(urls_field, str) and urls_field.strip().startswith("["):
            try:
                parsed = json.loads(urls_field)
                if isinstance(parsed, list) and parsed:
                    return parsed[0]
            except Exception:
                pass
        wapurl = raw_item.get("wapurl")
        if wapurl:
            return wapurl
        return None

    def choose_best_intro_local(self, raw_item):
        """在不请求文章页的情况下，选取最合适的简介字段"""
        candidates = [raw_item.get("intro"), raw_item.get("summary"), raw_item.get("wapsummary")]
        candidates = [c for c in candidates if isinstance(c, str) and c.strip()]
        if not candidates:
            return None
        # 选择最长的一条
        best = max(candidates, key=lambda x: len(x))
        return best

    def should_fetch_full_intro(self, intro_text):
        """判断是否需要抓取文章页补全简介"""
        if not intro_text:
            return True
        text = intro_text.strip()
        if len(text) < 60:
            return True
        if text.endswith("…") or text.endswith("..."):
            return True
        return False

    def keyword_relevance_score(self, title, intro):
        """基于关键词计算市场相关性分数（规则版）"""
        text = f"{title or ''} {intro or ''}".lower()
        keyword_weights = {
            "央行": 3,
            "降息": 3,
            "加息": 3,
            "降准": 3,
            "货币政策": 3,
            "财政政策": 2,
            "证监会": 3,
            "上交所": 2,
            "深交所": 2,
            "北交所": 2,
            "停牌": 2,
            "复牌": 2,
            "回购": 2,
            "分红": 2,
            "增持": 2,
            "减持": 2,
            "并购": 2,
            "重组": 2,
            "业绩": 2,
            "财报": 2,
            "预增": 2,
            "预亏": 2,
            "暴雷": 3,
            "违约": 3,
            "地产": 1,
            "新能源": 1,
            "半导体": 1,
            "ai": 1,
            "人工智能": 1,
            "指数": 1,
            "涨停": 1,
            "跌停": 1,
        }
        score = 0
        hits = []
        for keyword, weight in keyword_weights.items():
            if keyword in text:
                score += weight
                hits.append(keyword)
        return score, hits

    async def _call_model_relevance(self, item):
        if not (self.use_model_for_relevance and callable(self.model_relevance_fn)):
            return None, ""
        try:
            result = self.model_relevance_fn(item)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, dict):
                score = result.get("score")
                if score is None and isinstance(result.get("is_relevant"), bool):
                    score = self.relevance_min_score if result["is_relevant"] else 0
                return score, (result.get("reason") or "")
            if isinstance(result, bool):
                return (self.relevance_min_score if result else 0), "model-bool"
            if isinstance(result, (int, float)):
                return float(result), "model-score"
            return None, ""
        except Exception as e:
            logger.warning(f"Model relevance call failed: {e}")
            return None, ""

    async def annotate_market_relevance(self, items):
        """给每条新闻打市场相关性标签（规则 + 可选模型）"""
        for item in items:
            score_rule, hits = self.keyword_relevance_score(item.get("title"), item.get("intro"))
            score_model, model_reason = await self._call_model_relevance(item)
            if isinstance(score_model, (int, float)):
                score = max(score_rule, float(score_model))
                source = "rule+model"
            else:
                score = float(score_rule)
                source = "rule"

            is_relevant = score >= self.relevance_min_score
            reasons = []
            if hits:
                reasons.append(f"rule_hits={','.join(hits[:6])}")
            if model_reason:
                reasons.append(f"model={model_reason}")

            item["market_relevance_score"] = score
            item["market_relevance_label"] = "relevant" if is_relevant else "noise"
            item["market_relevance_reason"] = "; ".join(reasons)
            item["market_relevance_source"] = source

    def select_enrichment_candidates(self, items):
        """根据相关性与摘要质量选择需要补充描述的候选新闻"""
        if not items:
            return []

        candidates = []
        for item in items:
            if self.enable_relevance_filter and item.get("market_relevance_label") != "relevant":
                continue
            if not self.should_fetch_full_intro(item.get("intro")):
                continue
            if not item.get("url"):
                continue
            candidates.append(item)

        if not candidates:
            return []

        candidates.sort(key=lambda x: x.get("market_relevance_score", 0), reverse=True)
        ratio_limit = int(len(items) * self.max_enrich_ratio)
        total_limit = max(1, min(self.max_enrich_items_per_page, ratio_limit if ratio_limit > 0 else 1))
        return candidates[:total_limit]

    async def enrich_items_with_full_intro(self, session, items):
        """并发抓取文章页，补全 intro"""
        semaphore = self.article_semaphore or asyncio.Semaphore(self.article_concurrency)

        async def process_one(item):
            url = item.get("url")
            if not url:
                return
            try:
                async with semaphore:
                    intro_full = await self.fetch_article_intro(session, url)
                if intro_full and len(intro_full) > len(item.get("intro") or ""):
                    item["enriched_intro"] = intro_full
                    self.stats["enrich_success"] = self.stats.get("enrich_success", 0) + 1
                else:
                    self.stats["enrich_skipped"] = self.stats.get("enrich_skipped", 0) + 1
            except Exception as e:
                self.stats["enrich_failed"] = self.stats.get("enrich_failed", 0) + 1
                logger.debug(f"Enrich intro failed: {e}")

        await asyncio.gather(*[process_one(it) for it in items])

    def build_rule_signal(self, item):
        """规则版结构化信号（可被模型结果覆盖）"""
        text = f"{item.get('title', '')} {item.get('enriched_intro', '') or item.get('intro', '')}".lower()

        event_rules = [
            ("monetary_policy", ["降息", "加息", "降准", "货币政策", "央行"]),
            ("earnings", ["财报", "业绩", "预增", "预亏"]),
            ("regulation", ["证监会", "监管", "处罚", "问询"]),
            ("corporate_action", ["回购", "分红", "增持", "减持", "并购", "重组"]),
            ("risk_event", ["违约", "暴雷", "爆雷", "停牌"]),
        ]

        event_type = "other"
        for candidate, keywords in event_rules:
            if any(keyword in text for keyword in keywords):
                event_type = candidate
                break

        positive_keywords = ["上涨", "上调", "增长", "超预期", "回购", "增持", "分红", "利好"]
        negative_keywords = ["下跌", "下调", "亏损", "违约", "暴雷", "减持", "处罚", "利空"]
        pos_hits = sum(1 for keyword in positive_keywords if keyword in text)
        neg_hits = sum(1 for keyword in negative_keywords if keyword in text)

        if pos_hits > neg_hits:
            direction = "bullish"
        elif neg_hits > pos_hits:
            direction = "bearish"
        else:
            direction = "neutral"

        confidence = min(0.95, 0.5 + 0.05 * (pos_hits + neg_hits))
        rationale = f"rule_based pos_hits={pos_hits}, neg_hits={neg_hits}, event_type={event_type}"
        return {
            "event_type": event_type,
            "direction": direction,
            "confidence": round(confidence, 2),
            "rationale": rationale,
        }

    async def annotate_market_signal(self, items):
        """输出结构化交易信号：优先模型，失败则降级到规则"""
        for item in items:
            signal = None
            if self.use_model_for_signal and callable(self.model_signal_fn):
                try:
                    maybe_signal = self.model_signal_fn(item)
                    signal = await maybe_signal if asyncio.iscoroutine(maybe_signal) else maybe_signal
                except Exception as e:
                    logger.warning(f"Model signal extraction failed: {e}")

            if not isinstance(signal, dict):
                signal = self.build_rule_signal(item)

            item["signal_event_type"] = signal.get("event_type", "")
            item["signal_direction"] = signal.get("direction", "")
            item["signal_confidence"] = signal.get("confidence", "")
            item["signal_rationale"] = signal.get("rationale", "")

    async def fetch_article_intro(self, session, url):
        """抓取文章页简介：优先 meta description / og:description，其次正文首段"""
        try:
            async with session.get(url, headers=self.headers, timeout=15) as resp:
                html_text = await resp.text(errors="ignore")
            if not html_text:
                return None
            # 先尝试 meta description / og:description
            meta_desc = self._extract_meta_description(html_text)
            if meta_desc:
                return meta_desc
            # 退化到正文首段
            first_paragraph = self._extract_first_paragraph(html_text)
            if first_paragraph:
                return first_paragraph
            return None
        except Exception:
            return None

    def _extract_meta_description(self, html_text):
        """从HTML中提取<meta name="description">或<meta property="og:description">"""
        try:
            # name=description
            m1 = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html_text, re.I | re.S)
            if m1:
                return html.unescape(self._clean_whitespace(m1.group(1)))
            # property=og:description
            m2 = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', html_text, re.I | re.S)
            if m2:
                return html.unescape(self._clean_whitespace(m2.group(1)))
            return None
        except Exception:
            return None

    def _extract_first_paragraph(self, html_text):
        """从常见容器中提取首段文本（简易正则版）"""
        try:
            # 常见正文容器 id/class: artibody, article, content
            container_patterns = [
                r'<div[^>]+id=["\']artibody["\'][^>]*>(.*?)</div>',
                r'<article[^>]*>(.*?)</article>',
                r'<div[^>]+class=["\'][^"\']*(?:article|content)[^"\']*["\'][^>]*>(.*?)</div>',
            ]
            for pat in container_patterns:
                m = re.search(pat, html_text, re.I | re.S)
                if m:
                    inner = m.group(1)
                    # 找第一个<p>
                    p = re.search(r'<p[^>]*>(.*?)</p>', inner, re.I | re.S)
                    if p:
                        text = self._strip_html_tags(p.group(1))
                        return self._clean_whitespace(text)
            # 兜底：全局第一个<p>
            p = re.search(r'<p[^>]*>(.*?)</p>', html_text, re.I | re.S)
            if p:
                text = self._strip_html_tags(p.group(1))
                return self._clean_whitespace(text)
            return None
        except Exception:
            return None

    def _strip_html_tags(self, text):
        text = re.sub(r'<script[\s\S]*?</script>', ' ', text, flags=re.I)
        text = re.sub(r'<style[\s\S]*?</style>', ' ', text, flags=re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        return html.unescape(text)

    def _clean_whitespace(self, text):
        return re.sub(r'\s+', ' ', (text or '')).strip()
    
    async def crawl_all_pages(self):
        start_time = time.time()
        self.stats = {
            "enrich_success": 0,
            "enrich_failed": 0,
            "enrich_skipped": 0,
        }
        self.article_semaphore = asyncio.Semaphore(self.article_concurrency)
        
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = []
            for page in range(self.start_page, self.end_page + 1):
                task = self.fetch_page(session, page)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for page, result in enumerate(results, start=self.start_page):
                if isinstance(result, Exception):
                    print(f"第 {page} 页发生异常: {result}")
                elif isinstance(result, list):
                    self.all_items.extend(result)
        elapsed = time.time() - start_time
        logger.info(
            "Sina crawl completed: pages={}-{}, total_items={}, enrich_success={}, enrich_failed={}, elapsed={:.2f}s",
            self.start_page,
            self.end_page,
            len(self.all_items),
            self.stats.get("enrich_success", 0),
            self.stats.get("enrich_failed", 0),
            elapsed,
        )
        return self.all_items
    

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        self.all_items = []  # 清空累积的数据
        
        try:
            items = await self.crawl_all_pages()
        except Exception as e:
            logger.error(f"❌ Failed to crawl pages: {e}")
            # 即使爬取失败，也尝试返回空DataFrame而不是报错
            logger.info("⚠️ Returning empty DataFrame due to crawl failure")
            return pd.DataFrame(columns=['title', 'content', 'pub_time', 'url'])
        
        # 检查是否有数据
        if not items:
            logger.warning("⚠️ No items collected from crawling")
            return pd.DataFrame(columns=['title', 'content', 'pub_time', 'url'])
        
        logger.info(f"📊 Processing {len(items)} collected items...")
        
        df = pd.DataFrame(items)
        
        # 处理时间字段
        if not df.empty and 'publish_time' in df.columns:
            df['publish_time'] = pd.to_datetime(df['publish_time'], errors='coerce')
            end_dt = pd.to_datetime(trigger_time, errors='coerce')
            mask = pd.Series(True, index=df.index)
            if not pd.isna(end_dt):
                start_dt = end_dt - pd.Timedelta(days=1)
                mask &= (df['publish_time'] >= start_dt) & (df['publish_time'] < end_dt)
            df = df.loc[mask].reset_index(drop=True)
            df['pub_time'] = df['publish_time'].dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            df['pub_time'] = ''

        if 'intro' in df.columns:
            df['content'] = df.apply(
                lambda row: self._clean_whitespace(
                    self._strip_html_tags(str(row.get('enriched_intro') or row.get('intro') or ''))
                ),
                axis=1,
            )
        else:
            df['content'] = ""

        df['pub_time'] = df['pub_time'].fillna('')

        # 确保所有必需的列都存在
        keep_cols = [
            'title', 'content', 'pub_time', 'url',
            'market_relevance_score', 'market_relevance_label', 'market_relevance_reason',
            'signal_event_type', 'signal_direction', 'signal_confidence', 'signal_rationale'
        ]
        for col in keep_cols:
            if col not in df.columns:
                df[col] = ""

        df = df[keep_cols].copy()
        logger.info(f"get sina news until {trigger_time} success. Total {len(df)} rows")
        return df

if __name__ == "__main__":
    crawler = SinaNewsCrawl(start_page=1, end_page=50)
    df = asyncio.run(crawler.get_data("2025-08-21 15:00:00"))
    print(len(df))
    # try:
    #     output_path = os.path.join(os.path.dirname(__file__), "sina_news_crawl.json")
    #     df.to_json(output_path, orient="records", force_ascii=False, date_format="iso")
    #     print(f"Saved JSON to: {output_path}")
    # except Exception as e:
    #     print(f"Failed to save JSON: {e}")
 
