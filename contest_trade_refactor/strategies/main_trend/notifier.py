"""主升浪通知模块（Webhook / Server酱 / 钉钉）。

配置读取策略：
  1. 环境变量（以 MTF_NOTIFY* 开头）
  2. strategies/main_trend/strategy.yaml 里 notify: {...}

不会因为通知失败影响主流程：所有错误只记录，不抛给上层。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _cfg_candidates(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    notify = config.get("notify") or {}
    if not isinstance(notify, dict):
        return []
    webhook_url = notify.get("webhook_url") or os.getenv("MTF_NOTIFY_WEBHOOK_URL", "")
    if not webhook_url:
        return []
    type_ = str(notify.get("type") or os.getenv("MTF_NOTIFY_TYPE", "generic")).lower()
    enabled = bool(notify.get("enabled", True))
    env_enabled = os.getenv("MTF_NOTIFY_ENABLED", "")
    if env_enabled != "":
        enabled = env_enabled == "1"
    if not enabled:
        return []
    return [{"type": type_, "webhook_url": webhook_url, "title": notify.get("title", "主升浪系统")}]


def _send_webhook(url: str, payload: Dict[str, Any]) -> Optional[str]:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")[:500]
    except Exception as exc:
        logger.warning("notification send failed: %s", exc)
        return str(exc)


def build_payload(
    subject: str,
    lines: List[str],
    *,
    level: str = "info",
    tag: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    text = f"[{level.upper()}] {subject}\n\n" + "\n".join(lines)
    if tag:
        text = f"#{tag}\n" + text
    return {"text": text, "subject": subject, "level": level, "extra": extra or {}}


def notify(
    subject: str,
    lines: List[str],
    *,
    level: str = "info",
    config: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> None:
    """发送一次通知。失败不抛异常（日志警告）。"""
    targets = _cfg_candidates(config or {})
    payload = build_payload(subject, lines, level=level, tag="main_trend", extra=extra)
    if not targets:
        if dry_run:
            print(f"[dry-run-notify] {json.dumps(payload, ensure_ascii=False, indent=2)}")
        else:
            logger.info("notify skipped: no webhook configured")
        return
    for t in targets:
        url = t.get("webhook_url")
        if not url:
            continue
        if dry_run:
            print(f"[dry-run-notify] {json.dumps(payload, ensure_ascii=False, indent=2)}")
            continue
        resp = _send_webhook(url, payload)
        if resp:
            logger.info("notification response: %s", resp)
