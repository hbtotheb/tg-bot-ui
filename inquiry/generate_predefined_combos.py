"""Precompute matching strategies for all 144 predefined inquiry option combinations.

4 Preferred Looks x 6 Body Types x 6 Value Priorities = 144 Combos.
This eliminates LLM network latency and token costs for users selecting predefined options.
"""

from __future__ import annotations

import itertools
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent
OUTPUT_FILE = Path(__file__).parent / "predefined_combos.json"

LOOK_OPTIONS: dict[str, tuple[str | None, str]] = {
    "青春嫩妹": ("嫩妹", "青春嫩妹"),
    "成熟御姐": ("御姐", "成熟御姐"),
    "清纯邻家": ("清纯", "清纯邻家"),
    "不限风格": (None, ""),
}

BODY_OPTIONS: dict[str, tuple[str | None, str]] = {
    "苗条纤细": ("苗条", "苗条身材"),
    "丰满有料": ("大胸", "丰满身材"),
    "高挑长腿": ("长腿", "高挑长腿"),
    "微胖肉感": ("微胖", "微胖肉感"),
    "娇小可爱": ("娇小", "娇小体型"),
    "不限身材": (None, ""),
}

VAL_OPTIONS: dict[str, dict[str, Any]] = {
    "服务配合": {
        "focus": "service",
        "weights": {"visual": 0.20, "body": 0.20, "service": 0.50, "price": 0.10},
        "extra_kw": None,
        "action": "重点加权服务态度与配合细节评分。",
    },
    "女友感": {
        "focus": "service",
        "weights": {"visual": 0.20, "body": 0.15, "service": 0.55, "price": 0.10},
        "extra_kw": "女友感",
        "action": "大幅强化女友感与情绪陪伴服务权重。",
    },
    "颜值容貌": {
        "focus": "visual",
        "weights": {"visual": 0.50, "body": 0.20, "service": 0.20, "price": 0.10},
        "extra_kw": None,
        "action": "核心加权面容颜值与外在视觉评分。",
    },
    "身材体态": {
        "focus": "body",
        "weights": {"visual": 0.20, "body": 0.50, "service": 0.20, "price": 0.10},
        "extra_kw": None,
        "action": "核心加权身材体态与比例评分。",
    },
    "高性价比": {
        "focus": "price",
        "weights": {"visual": 0.20, "body": 0.20, "service": 0.25, "price": 0.35},
        "extra_kw": None,
        "action": "重点提高消费价格与综合性价比权重。",
    },
    "综合均衡": {
        "focus": "balanced",
        "weights": {"visual": 0.25, "body": 0.25, "service": 0.35, "price": 0.15},
        "extra_kw": None,
        "action": "均衡分配各维度体验与综合实力评分。",
    },
}


def build_predefined_combos() -> dict[str, dict[str, Any]]:
    """Build all 144 combinations of predefined user choices."""
    combos: dict[str, dict[str, Any]] = {}

    for (l_name, (l_kw, l_desc)), (b_name, (b_kw, b_desc)), (v_name, v_info) in itertools.product(
        LOOK_OPTIONS.items(), BODY_OPTIONS.items(), VAL_OPTIONS.items()
    ):
        kws: list[str] = []
        if l_kw:
            kws.append(l_kw)
        if b_kw:
            kws.append(b_kw)
        if v_info["extra_kw"]:
            kws.append(v_info["extra_kw"])

        feat_parts = [p for p in [l_desc, b_desc] if p]
        action_text = v_info["action"]
        if feat_parts:
            feat_str = "与".join(feat_parts) + "特征"
            expl = f"已锁定{feat_str}，{action_text}"
        else:
            expl = f"全维度综合考量，{action_text}"

        key = f"{l_name}|{b_name}|{v_name}"
        combos[key] = {
            "keywords": " ".join(kws),
            "keywords_list": kws,
            "weight_focus": v_info["focus"],
            "weights": v_info["weights"],
            "explanation": expl,
        }

    return combos


def save_predefined_combos(target_file: Path | None = None) -> Path:
    """Generate and write predefined_combos.json."""
    file_path = target_file or OUTPUT_FILE
    combos = build_predefined_combos()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(combos, f, ensure_ascii=False, indent=2)
    return file_path


if __name__ == "__main__":
    saved_path = save_predefined_combos()
    print(f"Successfully generated 144 predefined combos -> {saved_path}")
