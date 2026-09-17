import hashlib
import json
from typing import Any


def _canonical_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": item.get("kind"),
        "category": item.get("category"),
        "severity": item.get("severity"),
        "attention_rank": item.get("attention_rank"),
        "title": item.get("title"),
        "detail": item.get("detail"),
        "meta": item.get("meta"),
        "resource_type": item.get("resource_type"),
        "resource_id": item.get("resource_id"),
        "action": item.get("action") or {},
    }


def owner_attention_fingerprint(attention: dict[str, Any]) -> str:
    canonical = {
        "summary": attention.get("summary") or {},
        "items": [_canonical_item(item) for item in attention.get("items") or []],
        "read_only": bool(attention.get("read_only", True)),
        "governance": attention.get("governance") or {},
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _headline(summary: dict[str, Any]) -> str:
    total = int(summary.get("total") or 0)
    if total == 0:
        return "No owner attention is currently required."
    parts = []
    for key, label in (
        ("critical", "critical"),
        ("reviews", "review"),
        ("approvals", "approval"),
        ("warnings", "warning"),
    ):
        count = int(summary.get(key) or 0)
        if count:
            suffix = "" if count == 1 else "s"
            parts.append(f"{count} {label}{suffix}")
    return "Owner attention: " + ", ".join(parts) + "."


def build_owner_attention_snapshot(
    attention: dict[str, Any],
    *,
    limit: int = 5,
    previous_fingerprint: str | None = None,
) -> dict[str, Any]:
    fingerprint = owner_attention_fingerprint(attention)
    summary = attention.get("summary") or {}
    items = attention.get("items") or []
    changed = None if previous_fingerprint is None else previous_fingerprint.lower() != fingerprint
    return {
        "snapshot_version": 1,
        "fingerprint": fingerprint,
        "fingerprint_algorithm": "sha256",
        "previous_fingerprint_supplied": previous_fingerprint is not None,
        "changed": changed,
        "has_attention": bool(int(summary.get("total") or 0)),
        "headline": _headline(summary),
        "summary": summary,
        "top_items": items[:limit],
        "top_items_limit": limit,
        "total_items": len(items),
        "read_only": True,
        "governance": attention.get("governance") or {},
        "fingerprint_semantics": {
            "meaningful_fields": [
                "kind",
                "category",
                "severity",
                "attention_rank",
                "title",
                "detail",
                "meta",
                "resource_type",
                "resource_id",
                "action",
            ],
            "excluded_fields": ["occurred_at"],
            "purpose": "Detect meaningful owner-attention changes without timestamp-only noise.",
        },
    }
