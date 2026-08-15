"""
config module for trade agent
"""
from pathlib import Path
import yaml
import os
import re

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

WORKSPACE_ROOT = Path(os.environ.get("CONTEST_TRADE_WORKSPACE", str(PROJECT_ROOT / "agents_workspace"))).resolve()


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file without overriding existing env vars."""
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, val = text.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = val.strip().strip('"').strip("'")
    except Exception as exc:
        print(f"Warning: failed to load env file {path}: {exc}")


_load_dotenv(PROJECT_ROOT / ".env")


def _expand_env_placeholders(value):
    if isinstance(value, dict):
        return {k: _expand_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_placeholders(item) for item in value]
    if isinstance(value, str):
        match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value.strip())
        if match:
            return os.environ.get(match.group(1))
        return os.path.expandvars(value)
    return value


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _apply_llm_env(block: dict, prefix: str, fallback_prefix: str | None = None) -> None:
    field_env = {
        "provider": "PROVIDER",
        "base_url": "BASE_URL",
        "api_key": "API_KEY",
        "model_name": "MODEL_NAME",
    }
    for field, suffix in field_env.items():
        env_name = f"{prefix}_{suffix}"
        value = _env(env_name)
        if not value and fallback_prefix:
            value = _env(f"{fallback_prefix}_{suffix}")
        if value:
            block[field] = value


def _build_llm_block(prefix: str, fallback_prefix: str | None = None) -> dict:
    block = {"provider": "openai", "base_url": "", "api_key": "", "model_name": ""}
    _apply_llm_env(block, prefix, fallback_prefix=fallback_prefix)
    return block


def _apply_env_overrides(config: dict) -> dict:
    """Inject secrets and model settings from environment / .env."""
    secret_keys = {
        "tushare_key": "TUSHARE_KEY",
        "jqdata_username": "JQDATA_USERNAME",
        "jqdata_password": "JQDATA_PASSWORD",
        "bocha_key": "BOCHA_KEY",
        "serp_key": "SERP_KEY",
        "fmp_key": "FMP_KEY",
        "finnhub_key": "FINNHUB_KEY",
        "alpha_vantage_key": "ALPHA_VANTAGE_KEY",
        "polygon_key": "POLYGON_KEY",
    }
    for attr, env_name in secret_keys.items():
        config[attr] = _env(env_name)

    account_type = _env("JQDATA_ACCOUNT_TYPE", "formal").lower()
    if account_type not in {"formal", "trial"}:
        account_type = "formal"
    config["jqdata_account_type"] = account_type

    provider = _env("CN_MARKET_DATA_PROVIDER", "auto").lower()
    if provider not in {"auto", "jqdata", "akshare"}:
        provider = "auto"
    config["cn_market_data_provider"] = provider

    config["llm"] = _build_llm_block("LLM")
    config["llm_thinking"] = _build_llm_block("LLM_THINKING", fallback_prefix="LLM")
    config["vlm"] = _build_llm_block("VLM", fallback_prefix="LLM")

    return config


class ProjectConfig:

    def __init__(self) -> None:
        # Get market type from environment variable, default to CN-Stock
        market_type = os.environ.get('CONTEST_TRADE_MARKET', 'CN-Stock')
        
        # Choose config file based on market type
        if market_type == 'US-Stock':
            config_filename = "config_us.yaml"
        else:
            config_filename = "config.yaml"
        
        yaml_path = PROJECT_ROOT / config_filename
        print(f"Loading config from: {yaml_path} (Market: {market_type})")

        with open(yaml_path, "r", encoding="utf-8") as fr:
            config = yaml.load(fr, Loader=yaml.FullLoader)
        config = _expand_env_placeholders(config)
        config = _apply_env_overrides(config)
        for k in config:
            setattr(self, k, config[k])
        
        # Store the market type for reference
        self.market_type = market_type

cfg = ProjectConfig()

if __name__ == "__main__":
    print(f"Market Type: {cfg.market_type}")
    print(f"Data Agents Config: {cfg.data_agents_config}")
    print(f"Research Agent Config: {cfg.research_agent_config}")
    print(f"Market Config File: {cfg.market_config_file}")
    print(f"System Language: {cfg.system_language}")
    print(f"LLM Config: {cfg.llm}")
    print(f"Available attributes: {[attr for attr in dir(cfg) if not attr.startswith('_')]}")
