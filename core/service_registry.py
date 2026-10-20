from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

BOT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BOT_DIR.parent

class ServiceRegistry:
    _instance = None
    _config: dict[str, dict[str, Any]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServiceRegistry, cls).__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        path = os.getenv("SERVICES_CONFIG_PATH", str(PROJECT_ROOT / "constants" / "bot" / "services.json"))
        if not os.path.exists(path):
            self._config = {"OTHER": {"label": {"zh": "其他", "en": "Other"}, "keywords": []}}
            return
        
        with open(path, "r", encoding="utf-8") as f:
            self._config = json.load(f)

    @property
    def categories(self) -> list[str]:
        return list(self._config.keys())

    def get_label(self, category: str, lang: str) -> str:
        cat = self._config.get(category, self._config.get("OTHER", {}))
        return cat.get("label", {}).get(lang, category)

    def get_keywords(self, category: str) -> list[str]:
        return self._config.get(category, {}).get("keywords", [])

    def get_prompt_block(self) -> str:
        all_kws = set()
        for data in self._config.values():
            for kw in data.get("keywords", []):
                all_kws.add(kw)
        return ", ".join(sorted(list(all_kws)))

    def map_category(self, original_text: str | None) -> str:
        if not original_text:
            return "OTHER"
        
        terms = [t.strip().lower() for t in original_text.split(",") if t.strip()]
        if not terms:
            return "OTHER"

        found_categories = set()

        for term in terms:
            term_found = False
            for code, data in self._config.items():
                if code == "OTHER":
                    continue
                for kw in data.get("keywords", []):
                    kw_lower = kw.lower()
                    idx = term.find(kw_lower)
                    if idx != -1:
                        is_valid = True
                        is_ascii_alpha = len(kw_lower) > 0 and all('a' <= c <= 'z' for c in kw_lower)
                        if is_ascii_alpha:
                            if idx > 0 and 'a' <= term[idx - 1] <= 'z':
                                is_valid = False
                            end_idx = idx + len(kw_lower)
                            if end_idx < len(term) and 'a' <= term[end_idx] <= 'z':
                                is_valid = False
                        
                        if is_valid:
                            found_categories.add(code)
                            term_found = True
                            break
                if term_found:
                    break
            
            if term_found:
                continue

            import difflib
            best_code = "OTHER"
            best_score = 0.0
            
            for code, data in self._config.items():
                if code == "OTHER":
                    continue
                for kw in data.get("keywords", []):
                    score = difflib.SequenceMatcher(None, kw.lower(), term).ratio()
                    if score > 0.6 and score > best_score:
                        best_score = score
                        best_code = code
            
            if best_code != "OTHER":
                found_categories.add(best_code)

        if not found_categories:
            return "OTHER"
        
        return ",".join(sorted(list(found_categories)))


class CategoryGroupRegistry:
    _instance = None
    _config: dict[str, dict[str, Any]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CategoryGroupRegistry, cls).__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        groups_path = os.getenv("GROUPS_CONFIG_PATH", str(PROJECT_ROOT / "constants" / "bot" / "category_groups.json"))
        path = Path(groups_path)
        if not path.exists():
            self._config = {}
            return
        with open(path, "r", encoding="utf-8") as f:
            self._config = json.load(f)

    @property
    def groups(self) -> dict[str, dict[str, Any]]:
        return self._config

    def get_label(self, group_code: str, lang: str = "zh") -> str:
        group = self._config.get(group_code, {})
        return group.get("label", {}).get(lang, group_code)

    def resolve_sub_categories(self, group_codes: list[str] | str) -> list[str]:
        if isinstance(group_codes, str):
            group_codes = [group_codes]
        sub_cats = []
        for code in group_codes:
            if code in self._config:
                sub_cats.extend(self._config[code].get("sub_categories", []))
            else:
                sub_cats.append(code)
        return list(dict.fromkeys(sub_cats))

    def aggregate_counts(self, raw_cat_map: dict[str, int]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for group_code, group_data in self._config.items():
            sub_cats = group_data.get("sub_categories", [])
            group_total = 0
            for sub in sub_cats:
                for cat_str, cnt in raw_cat_map.items():
                    if sub in cat_str:
                        group_total += cnt
            counts[group_code] = group_total
        return counts


registry = ServiceRegistry()
category_groups = CategoryGroupRegistry()
