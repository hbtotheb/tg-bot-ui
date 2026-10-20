from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
LOCATIONS_PATH = ROOT / "constants" / "extractor" / "locations.json"
_LOCATIONS_CACHE: dict | None = None


def get_configured_locations() -> dict:
    global _LOCATIONS_CACHE
    if _LOCATIONS_CACHE is None:
        if LOCATIONS_PATH.exists():
            try:
                with open(LOCATIONS_PATH, "r", encoding="utf-8") as f:
                    _LOCATIONS_CACHE = json.load(f)
            except Exception:
                _LOCATIONS_CACHE = {}
        else:
            _LOCATIONS_CACHE = {}
    return _LOCATIONS_CACHE


def get_all_configured_cities() -> list[str]:
    locs = get_configured_locations()
    if locs:
        return list(locs.keys())
    return [
        "北京", "上海", "广州", "深圳", "重庆", "成都", "西安", "长沙",
        "天津", "南京", "太仓", "苏州", "无锡", "保定", "廊坊", "石家庄",
        "杭州", "武汉", "东莞", "佛山", "郑州", "合肥", "宁波", "常州",
    ]


def get_configured_districts(city: str | None) -> list[str]:
    if not city:
        return []
    locs = get_configured_locations()
    if city in locs:
        city_info = locs[city]
        districts = list(city_info.get("districts", []))
        unique_lms = list(city_info.get("unique_landmarks", {}).keys())
        common_lms = list(city_info.get("common_landmarks", {}).keys())
        return list(dict.fromkeys(districts + unique_lms + common_lms))
    fallback_districts = {
        "上海": ["静安", "徐汇", "浦东", "黄浦", "长宁", "普陀", "闵行", "虹口", "杨浦"],
        "北京": ["朝阳", "海淀", "东城", "西城", "丰台", "通州", "三里屯", "望京", "国贸"],
        "深圳": ["南山", "福田", "罗湖", "宝安", "龙华"],
        "广州": ["天河", "越秀", "海珠", "番禺", "白云"],
        "杭州": ["西湖", "拱墅", "上城", "滨江", "萧山"],
    }
    return fallback_districts.get(city, [])
