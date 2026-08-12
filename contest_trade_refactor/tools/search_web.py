"""
Search Web Tools
use bocha and serpapi to search web
"""
import sys
import os
import asyncio
import requests
import textwrap
from pathlib import Path
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from loguru import logger
import json
from config.config import cfg
from tools.tool_utils import smart_tool


sys.path.append(str(Path(__file__).parent.parent.resolve()))

CWEI_SERVER_ENV_PATH = Path(
    os.getenv("CWEI_SERVER_ENV_PATH", "/Users/wangxinyu/Desktop/web/cwei-server/.env")
)


def _load_cwei_env_file() -> dict:
    """Load key-values from cwei-server .env file."""
    values = {}
    if not CWEI_SERVER_ENV_PATH.exists():
        return values

    try:
        for line in CWEI_SERVER_ENV_PATH.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, val = text.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                values[key] = val
    except Exception as e:
        logger.warning(f"Failed to read cwei-server env file: {e}")
    return values


def _get_volc_search_config() -> tuple[str, str]:
    """Resolve Volcengine web search config with cwei-server priority."""
    env_file = _load_cwei_env_file()
    api_key = (
        env_file.get("VOLC_WEB_SEARCH_API_KEY")
        or os.getenv("VOLC_WEB_SEARCH_API_KEY")
        or ""
    ).strip()
    base_url = (
        env_file.get("VOLC_WEB_SEARCH_BASE_URL")
        or os.getenv("VOLC_WEB_SEARCH_BASE_URL")
        or "https://open.feedcoopapi.com/search_api/web_search"
    ).strip()
    return api_key, base_url


def ask_volcengine(payload: dict) -> list:
    """Search using Volcengine web search API configured from cwei-server."""
    api_key, base_url = _get_volc_search_config()
    if not api_key:
        return []

    request_body = {
        "Query": payload.get("query", "").strip()[:100],
        "SearchType": "web_summary",
        "Count": max(1, min(10, int(payload.get("topk", 3) or 3))),
        "NeedSummary": True,
        "Filter": {
            "NeedUrl": True,
            "NeedContent": False,
        },
        "QueryControl": {
            "QueryRewrite": False,
        },
        "TimeRange": "OneYear",
        "ContentFormats": "text",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(base_url, headers=headers, json=request_body, timeout=12)
        response.raise_for_status()
        raw_text = response.content.decode("utf-8", errors="ignore").strip()
        data = {}
        if raw_text:
            # Some Volc endpoints return SSE: `data:{...}` lines.
            if raw_text.startswith("data:"):
                candidates = []
                for line in raw_text.splitlines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        parsed = json.loads(chunk)
                        if isinstance(parsed, dict):
                            candidates.append(parsed)
                    except Exception:
                        continue
                if candidates:
                    # Merge streaming frames: keep last frame, but preserve WebResults from seed frame.
                    seed = None
                    for c in candidates:
                        result_obj = c.get("Result") if isinstance(c, dict) else None
                        web_results = result_obj.get("WebResults") if isinstance(result_obj, dict) else None
                        if isinstance(web_results, list) and web_results:
                            seed = c
                            break
                    last = candidates[-1]
                    if seed is not None and isinstance(last, dict):
                        merged = dict(last)
                        merged_result = dict(last.get("Result") or {})
                        seed_result = seed.get("Result") or {}
                        if not merged_result.get("WebResults") and seed_result.get("WebResults"):
                            merged_result["WebResults"] = seed_result.get("WebResults")
                        if not merged_result.get("ResultCount") and seed_result.get("ResultCount"):
                            merged_result["ResultCount"] = seed_result.get("ResultCount")
                        merged["Result"] = merged_result
                        data = merged
                    else:
                        data = last
            else:
                try:
                    data = json.loads(raw_text)
                except Exception:
                    data = {}

        result = data.get("Result") if isinstance(data, dict) else None
        if not isinstance(result, dict):
            result = data.get("result", {}) if isinstance(data, dict) else {}

        candidates = result.get("WebResults") or result.get("webResults") or result.get("results") or []

        standardized_results = []
        for item in candidates[:request_body["Count"]]:
            title = item.get("Title") or item.get("title") or item.get("name") or ""
            snippet = (
                item.get("Summary")
                or item.get("Snippet")
                or item.get("Content")
                or item.get("snippet")
                or ""
            )
            url = item.get("Url") or item.get("url") or item.get("link") or ""
            publish_time = item.get("PublishTime") or item.get("time") or ""
            if title or snippet:
                standardized_results.append({
                    "title": str(title).strip(),
                    "snippet": str(snippet).strip(),
                    "url": str(url).strip(),
                    "time": str(publish_time).strip(),
                })
        return standardized_results
    except Exception as e:
        logger.warning(f"Volcengine search failed: {e}")
        return []

def ask_bocha(payload: dict, BOCHA_API_KEY: str) -> list:
    """
    Performs a search using the Bocha AI API.
    API Key must be provided as an argument.
    """
    BOCHA_URL = "https://api.bochaai.com/v1/web-search"
    headers = {
        'Authorization': 'Bearer ' + BOCHA_API_KEY,
        'Content-Type': 'application/json'
    }

    start_date = payload.get("start_date")
    end_date = payload.get("end_date")

    try:
        start_formatted = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        end_formatted = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
        freshness = f"{start_formatted}..{end_formatted}"
    except (TypeError, IndexError):
        logger.error("Bocha search failed: start_date or end_date are missing or malformed in payload.")
        return []

    bocha_payload = {
        "query": payload.get("query", ""),
        "count": payload.get("topk", 3),
        "freshness": freshness
    }

    try:
        response = requests.post(BOCHA_URL, headers=headers, json=bocha_payload, timeout=5)
        response.raise_for_status()  # For non-200 responses

        response_data = response.json()
        web_pages = response_data.get("data", {}).get("webPages", {})
        values = web_pages.get("value", [])

        standardized_results = []
        for item in values[:bocha_payload["count"]]:
            standardized_results.append({
                "title": item.get("name", ""),
                "snippet": item.get("snippet", ""),
                "url": item.get("url", ""),
                "time": item.get("dateLastCrawled", "")[:10]
            })
        return standardized_results

    except requests.exceptions.RequestException as e:
        logger.error(f"Bocha API request failed: {e}")
        return []


def ask_google(payload: dict, SERP_API_KEY: str) -> list:
    """
    Performs a search using the SerpAPI (Google Search).
    API Key must be provided as an argument.
    """
    SERP_URL = "https://google.serper.dev/search"

    try:
        start_date = payload.get("start_date")
        end_date = payload.get("end_date")
        headers = {
            "X-API-KEY": SERP_API_KEY,
            'Content-Type': 'application/json'
        }
        params = {
            "q": payload.get("query", ""),
            "num": min(payload.get("topk", 3), 10), "gl": "cn", "hl": "zh-cn"
        }

        if start_date and end_date:
            start_formatted = f"{int(start_date[4:6])}/{int(start_date[6:8])}/{start_date[:4]}"
            end_formatted = f"{int(end_date[4:6])}/{int(end_date[6:8])}/{end_date[:4]}"
            params["tbs"] = f"cdr:1,cd_min:{start_formatted},cd_max:{end_formatted}"

        payload = json.dumps(params)
        response = requests.request("POST", SERP_URL, headers=headers, data=payload)
        response.raise_for_status()
        data = response.json()

        standardized_results = []
        organic_results = data.get("organic", [])
        for item in organic_results[:params["num"]]:
            standardized_results.append({
                "title": item.get("title", ""), 
                "snippet": item.get("snippet", ""),
                "url": item.get("link", ""), 
                "time": item.get("date", "")
            })
        
        print(standardized_results)
        return standardized_results
    except requests.exceptions.RequestException as e:
        logger.error(f"SerpAPI request failed: {e}")
        return []



def build_search_result_context(results: list) -> str:
    """Formats a list of search results into a single string context."""
    if not results: return ""
    def _trim(text: str, limit: int = 220) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    SearchResultFormat = textwrap.dedent("""
    <search_result id={id}>
    <title>{title}</title>
    <time>{time}</time>
    <url>{url}</url>
    <summary>{summary}</summary>
    </search_result>
    """)
    result_context = [
        SearchResultFormat.format(
            id=idx + 1,
            title=_trim(res.get('title', 'N/A'), 140),
            summary=_trim(res.get('snippet', 'N/A'), 220),
            url=_trim(res.get('url', 'N/A'), 220),
            time=_trim(res.get('time', 'N/A'), 60),
        ) for idx, res in enumerate(results)
    ]
    return "\n".join(result_context)


class SearchWebInput(BaseModel):
    query: str = Field(description="The search keywords, separate with empty space. Simple specific keywords. No more than 3 keywords.")
    topk: int = Field(default=5, description="The number of top results to return, default is 5")
    trigger_time: str = Field(description="The trigger time of the search. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Searches information from the web based on a query and returns a list of results up to the specified limit.",
    args_schema=SearchWebInput,
    max_output_len=3000,
    timeout_seconds=60.0
)
async def search_web(query: str, topk: int = 5, trigger_time: str = None):
    """
    Main tool function that orchestrates the search process with a fallback mechanism.
    This tool's signature is compatible with the Pydantic model for LangChain.
    """
    if not trigger_time:
        logger.error("Search failed: 'trigger_time' is a mandatory parameter for this tool.")
        return ""

    trigger_date = trigger_time.split(" ")[0].replace("-", "")
    start_time = (datetime.strptime(trigger_date, "%Y%m%d") - timedelta(days=30)).strftime("%Y%m%d")
    end_time = (datetime.strptime(trigger_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")

    payload = {
        "query": query, "topk": min(topk, 20),
        "start_date": start_time, "end_date": end_time
    }
    
    response = []
    serp_api_key = cfg.serp_key
    bocha_api_key = cfg.bocha_key
    volc_api_key, volc_base_url = _get_volc_search_config()

    if not volc_api_key and not serp_api_key and not bocha_api_key:
        logger.warning(
            "No search API keys are configured. Checked Volcengine (cwei-server/.env), SERP, BOCHA."
        )
        return ""

    # Priority 1: Volcengine Web Search via cwei-server .env
    if volc_api_key:
        logger.info(
            f"Attempting search with Volcengine (cwei-server) for query: '{query}', base_url='{volc_base_url}'"
        )
        response = ask_volcengine(payload)

    # Priority 2: Try Google Search
    if not response and serp_api_key:
        logger.info(f"Attempting search with Google (SerpAPI) for query: '{query}'")
        response = ask_google(payload, serp_api_key)
    
    # Priority 3: Fallback to Bocha if the first attempts fail
    if not response and bocha_api_key:
        logger.warning("Volcengine/Google search failed or was not configured. Falling back to Bocha AI.")
        logger.info(f"Attempting search with Bocha AI for query: '{query}'")
        response = ask_bocha(payload, bocha_api_key)
    
    if not response:
        logger.warning("All configured search providers failed to return results.")
        return ""
        
    logger.info(f"Search successful. Returning {len(response)} results.")
    return build_search_result_context(response)

if __name__ == "__main__":
    result = asyncio.run(search_web.ainvoke({"query": "最近电影", "topk": 3, "trigger_time": "2025-01-09 15:00:00"}))
    print(result)
