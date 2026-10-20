from __future__ import annotations

import re
from typing import Any

# Regex patterns for stripping volatile content
URL_PATTERN = re.compile(r"https?://\S+|t\.me/\S+|tg://\S+", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"@[a-zA-Z0-9_]+", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"\+?\d[\d\s\-]{7,}\d")
DATETIME_PATTERN = re.compile(
    r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?|\d{1,2}:\d{2}(:\d{2})?|\d{1,2}月\d{1,2}日"
)
NON_ALPHANUM_PATTERN = re.compile(r"[^\w\u4e00-\u9fa5]+", re.UNICODE)


def normalize_text(text: str | None) -> str:
    """Clean text by removing links, mentions, phones, timestamps, and punctuation."""
    if not text:
        return ""
    cleaned = URL_PATTERN.sub("", text)
    cleaned = MENTION_PATTERN.sub("", cleaned)
    cleaned = PHONE_PATTERN.sub("", cleaned)
    cleaned = DATETIME_PATTERN.sub("", cleaned)
    cleaned = NON_ALPHANUM_PATTERN.sub("", cleaned)
    return cleaned.strip().lower()


def get_ngrams(text: str, n: int = 2) -> set[str]:
    """Generate n-grams for text (character-level for Chinese/mixed text)."""
    if len(text) < n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity between two texts using 2-character n-grams."""
    norm1 = normalize_text(text1)
    norm2 = normalize_text(text2)

    if not norm1 and not norm2:
        return 1.0
    if not norm1 or not norm2:
        return 0.0
    if norm1 == norm2:
        return 1.0

    set1 = get_ngrams(norm1, 2)
    set2 = get_ngrams(norm2, 2)

    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))

    if union == 0:
        return 0.0
    return intersection / union


def deduplicate_results(
    results: list[dict[str, Any]], threshold: float = 0.80
) -> list[dict[str, Any]]:
    """Group near-duplicate items in a list of search/browse results.
    
    Returns a deduplicated list where primary items contain:
    - 'dup_count': number of hidden duplicate messages
    - 'duplicates': list of hidden duplicate items
    """
    if not results:
        return []

    # Pre-compute normalized text and 2-grams once per item
    prepared: list[dict[str, Any]] = []
    for item in results:
        text = item.get("text") or ""
        norm = normalize_text(text)
        ngrams = get_ngrams(norm, 2) if norm else set()
        prepared.append({
            "item": item,
            "norm": norm,
            "ngrams": ngrams,
            "len": len(norm),
        })

    deduped: list[dict[str, Any]] = []
    deduped_prepared: list[dict[str, Any]] = []
    seen_hashes: dict[str, int] = {}  # norm_hash -> index in deduped

    for p in prepared:
        item = p["item"]
        norm = p["norm"]

        # Fast path: exact normalized hash match
        if norm and norm in seen_hashes:
            target_idx = seen_hashes[norm]
            primary = deduped[target_idx]
            primary.setdefault("dup_count", 0)
            primary["dup_count"] += 1
            primary.setdefault("duplicates", []).append(item)
            continue

        # Fuzzy similarity check against already selected items
        found_duplicate = False
        ngrams1 = p["ngrams"]
        len1 = p["len"]

        if ngrams1:
            for d_prep in deduped_prepared:
                len2 = d_prep["len"]
                if max(len1, len2) > 0 and min(len1, len2) / max(len1, len2) < 0.5:
                    continue

                ngrams2 = d_prep["ngrams"]
                if not ngrams2:
                    continue

                inter = len(ngrams1.intersection(ngrams2))
                union = len(ngrams1.union(ngrams2))
                sim = inter / union if union > 0 else 0.0

                if sim >= threshold:
                    primary = d_prep["item"]
                    primary.setdefault("dup_count", 0)
                    primary["dup_count"] += 1
                    primary.setdefault("duplicates", []).append(item)
                    found_duplicate = True
                    break

        if not found_duplicate:
            # Create shallow copy of item to avoid mutating original dictionary unexpectedly
            item_copy = dict(item)
            item_copy["dup_count"] = 0
            item_copy["duplicates"] = []
            deduped.append(item_copy)
            d_entry = {"item": item_copy, "norm": norm, "ngrams": ngrams1, "len": len1}
            deduped_prepared.append(d_entry)
            if norm:
                seen_hashes[norm] = len(deduped) - 1

    return deduped


def interleave_by_channel(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Interleave search/browse results by chat_id so no single channel dominates consecutive slots.

    Picks 1st item from Channel A, 1st from Channel B, 1st from Channel C...
    then 2nd item from Channel A, 2nd from Channel B... and so on.
    """
    if not results:
        return []

    groups: dict[Any, list[dict[str, Any]]] = {}
    for item in results:
        key = item.get("chat_id") or item.get("chat_title") or "unknown"
        groups.setdefault(key, []).append(item)

    interleaved: list[dict[str, Any]] = []
    group_lists = list(groups.values())
    max_len = max(len(g) for g in group_lists)

    for i in range(max_len):
        for group in group_lists:
            if i < len(group):
                interleaved.append(group[i])

    return interleaved
