from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "extractor" / "review_llm_extractor" / ".env.review_extractor")
load_dotenv(ROOT / "extractor" / ".env.extractor")
load_dotenv(ROOT / "bot" / ".env.bot")

from .state import InquirySession

logger = logging.getLogger(__name__)


try:
    from tg_rec_engine import generate_heuristic_search_query, parse_price_range
except ImportError:
    def parse_price_range(text: str | None) -> tuple[float | None, float | None]:
        if not text:
            return None, None
        nums = [float(x) for x in re.findall(r"\d{3,5}", str(text))]
        if len(nums) >= 2:
            return min(nums[0], nums[1]), max(nums[0], nums[1])
        if len(nums) == 1:
            return None, nums[0]
        return None, None

    def generate_heuristic_search_query(session: Any) -> dict[str, Any]:
        p_min, p_max = parse_price_range(getattr(session, "price_range", None))
        kws = [x for x in (getattr(session, "preferred_look", None), getattr(session, "preferred_body", None)) if x and "不限" not in str(x)]
        return {
            "keywords": " ".join(kws),
            "keywords_list": kws,
            "weight_focus": "service",
            "weights": {"visual": 0.25, "body": 0.25, "service": 0.35, "price": 0.15},
            "price_min": p_min,
            "price_max": p_max,
            "location_text": getattr(session, "location_text", None),
            "explanation": "已根据您的偏好完成匹配筛选。",
        }

PREDEFINED_COMBOS_FILE = Path(__file__).parent / "predefined_combos.json"
_PREDEFINED_COMBOS: dict[str, dict[str, Any]] | None = None

LOOK_NORM: dict[str | None, str] = {
    "青春嫩妹": "青春嫩妹",
    "嫩妹": "青春嫩妹",
    "成熟御姐": "成熟御姐",
    "御姐": "成熟御姐",
    "清纯邻家": "清纯邻家",
    "清纯": "清纯邻家",
    "不限风格": "不限风格",
    "不限": "不限风格",
    "": "不限风格",
    None: "不限风格",
}

BODY_NORM: dict[str | None, str] = {
    "苗条纤细": "苗条纤细",
    "苗条": "苗条纤细",
    "丰满有料": "丰满有料",
    "丰满": "丰满有料",
    "大胸": "丰满有料",
    "高挑长腿": "高挑长腿",
    "高挑": "高挑长腿",
    "长腿": "高挑长腿",
    "微胖肉感": "微胖肉感",
    "微胖": "微胖肉感",
    "娇小可爱": "娇小可爱",
    "娇小": "娇小可爱",
    "不限身材": "不限身材",
    "不限": "不限身材",
    "": "不限身材",
    None: "不限身材",
}

VAL_NORM: dict[str | None, str] = {
    "服务配合": "服务配合",
    "服务": "服务配合",
    "女友感": "女友感",
    "颜值容貌": "颜值容貌",
    "颜值": "颜值容貌",
    "身材体态": "身材体态",
    "身材": "身材体态",
    "高性价比": "高性价比",
    "性价比": "高性价比",
    "综合均衡": "综合均衡",
    "综合体验": "综合均衡",
    "综合": "综合均衡",
    "均衡": "综合均衡",
    "": "综合均衡",
    None: "综合均衡",
}


def normalize_combo_key(look: str | None, body: str | None, val: str | None) -> str | None:
    """
    Check if the user choices map cleanly to one of the 144 predefined combos.
    Returns the canonical key (e.g. '青春嫩妹|苗条纤细|女友感') if all 3 are predefined options,
    or None if any answer contains custom typed text.
    """
    canon_look = LOOK_NORM.get(look.strip() if isinstance(look, str) else look)
    canon_body = BODY_NORM.get(body.strip() if isinstance(body, str) else body)
    canon_val = VAL_NORM.get(val.strip() if isinstance(val, str) else val)

    if not canon_look or not canon_body or not canon_val:
        return None

    return f"{canon_look}|{canon_body}|{canon_val}"


def _get_predefined_combos() -> dict[str, dict[str, Any]]:
    """Retrieve precomputed combinations from JSON file, with runtime generation fallback."""
    global _PREDEFINED_COMBOS
    if _PREDEFINED_COMBOS is not None:
        return _PREDEFINED_COMBOS
    if PREDEFINED_COMBOS_FILE.exists():
        try:
            with open(PREDEFINED_COMBOS_FILE, "r", encoding="utf-8") as f:
                _PREDEFINED_COMBOS = json.load(f)
                return _PREDEFINED_COMBOS
        except Exception as e:
            logger.warning("Failed to load predefined_combos.json: %s", e)
    from .generate_predefined_combos import build_predefined_combos
    _PREDEFINED_COMBOS = build_predefined_combos()
    return _PREDEFINED_COMBOS



def _clean_json_text(text: str) -> str:
    """Strip markdown code fence if present."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


async def _call_deepseek_or_openai(
    system_prompt: str,
    user_payload: str,
    api_key: str,
    base_url: str | None = None,
    model: str = "deepseek-chat",
) -> dict[str, Any] | None:
    """Call DeepSeek or any OpenAI-compatible API endpoint."""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
        )
        logger.info(
            "Sending inquiry matching LLM request via OpenAI-compatible endpoint (%s, model=%s)...",
            base_url or "https://api.openai.com/v1",
            model,
        )
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                response_format={"type": "json_object"},
                max_tokens=400,
            ),
            timeout=10.0,
        )
        content = resp.choices[0].message.content or "{}"
        cleaned = _clean_json_text(content)
        parsed = json.loads(cleaned)
        logger.info("Successfully received LLM search query response: %s", parsed)
        return parsed
    except Exception as e:
        logger.warning("DeepSeek/OpenAI LLM search query generation failed (%s, model=%s): %s", base_url, model, e)
    return None


async def _call_gemini(system_prompt: str, user_payload: str) -> dict[str, Any] | None:
    """Call Google Gemini API."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        model_name = os.getenv("EXTRACTOR_MODEL") or "gemini-2.0-flash"
        logger.info("Sending inquiry matching LLM request via Gemini (model=%s)...", model_name)
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model_name,
                contents=user_payload,
                config={
                    "system_instruction": system_prompt,
                    "response_mime_type": "application/json",
                },
            ),
            timeout=10.0,
        )
        if response and response.text:
            cleaned = _clean_json_text(response.text)
            parsed = json.loads(cleaned)
            logger.info("Successfully received Gemini LLM search query response: %s", parsed)
            return parsed
    except Exception as e:
        logger.warning("Gemini search query generation failed: %s", e)
    return None


async def _call_anthropic(system_prompt: str, user_payload: str) -> dict[str, Any] | None:
    """Call Anthropic API."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=api_key)
        model_name = os.getenv("EXTRACTOR_MODEL") or "claude-3-5-haiku-20241022"
        logger.info("Sending inquiry matching LLM request via Anthropic (model=%s)...", model_name)
        resp = await asyncio.wait_for(
            client.messages.create(
                model=model_name,
                max_tokens=400,
                system=system_prompt,
                messages=[{"role": "user", "content": user_payload}],
            ),
            timeout=10.0,
        )
        text = resp.content[0].text if resp.content else "{}"
        cleaned = _clean_json_text(text)
        parsed = json.loads(cleaned)
        logger.info("Successfully received Anthropic LLM search query response: %s", parsed)
        return parsed
    except Exception as e:
        logger.warning("Anthropic search query generation failed: %s", e)
    return None


async def generate_search_query(
    session: InquirySession,
    teacher_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Synthesize the user's 4 answered questions into a structured search query payload,
    keyword tokens, and dynamic rubric weights for ranking candidate teachers using LLM.
    """
    # 0. Check predefined combinations first (instant local resolution, 0 LLM calls)
    price_min, price_max = parse_price_range(session.preferred_price)

    combo_key = normalize_combo_key(session.preferred_look, session.preferred_body, session.value_most)
    if combo_key:
        combos = _get_predefined_combos()
        if combo_key in combos:
            entry = combos[combo_key]
            logger.info("Matched predefined combo [%s], bypassing LLM call.", combo_key)
            return {
                "keywords": entry["keywords"],
                "keywords_list": list(entry.get("keywords_list") or [k for k in entry["keywords"].split() if k]),
                "weight_focus": entry["weight_focus"],
                "weights": dict(entry["weights"]),
                "city": (teacher_context or {}).get("city") or (teacher_context or {}).get("canonical_city"),
                "location_text": session.location_text,
                "preferred_price": session.preferred_price,
                "price_min": price_min,
                "price_max": price_max,
                "explanation": entry["explanation"],
                "source": "predefined",
            }

    system_prompt = (
        "You are an expert search engine optimizer for a Telegram service directory.\n"
        "Convert the user's 4 preferences into search keywords and ranking weights.\n\n"
        "Domain Vocabulary & Concept Mapping Rules (CRITICAL for database index alignment):\n"
        "1. Question #1 (Look & Style):\n"
        "   - Young / Youthful / Student -> ALWAYS emit '嫩妹' (the primary database term with 350+ entries; avoid generic '年轻').\n"
        "   - Mature / Sensual / MILF -> ALWAYS emit '御姐' (avoid generic '成熟').\n"
        "   - Pure / Natural / Girl-Next-Door / Clean face -> ALWAYS emit '清纯' (distinguished from young; highlights sweet, minimal-makeup beauty).\n\n"
        "2. Question #2 (Body Type - Understand Critical Physical Distinctions):\n"
        "   - Slim vs. Petite:\n"
        "     * Slim / Slender (苗条) refers to low body fat, flat belly, and thin waistline across any height. Emit '苗条'.\n"
        "     * Petite (娇小) refers strictly to short height (under 158cm / 5'2\") and small compact frame. Emit '娇小'.\n"
        "   - Busty vs. Chubby:\n"
        "     * Busty (大胸) refers specifically to large chest/breast size (C/D/E+ cup). A busty girl can still be slim. Emit '大胸'.\n"
        "     * Chubby / Curvy (微胖) refers to overall body fullness, soft curves on hips and thighs, and meaty tactile feel. Emit '微胖'.\n"
        "   - Tall / Long Legs (长腿) refers to height 168cm+ and long leg proportions. Emit '长腿'.\n\n"
        "3. Question #3 (Value Most / Core Priority):\n"
        "   - Girlfriend Experience / Emotional Value / Intimacy (女友感) -> ALWAYS emit '女友感' in keywords, focus 'service' (weight 0.55, visual 0.20, body 0.15, price 0.10).\n"
        "   - Service & Compliance / Attitude (服务配合) -> focus 'service' (weight 0.50).\n"
        "   - Top Face & Looks (颜值容貌) -> focus 'visual' (weight 0.50).\n"
        "   - Body & Figure (身材体态) -> focus 'body' (weight 0.50).\n"
        "   - High Cost-Performance (高性价比) -> focus 'price' (weight 0.35).\n"
        "   - Balanced / All-Rounder (综合均衡) -> balanced weights (visual 0.25, body 0.25, service 0.35, price 0.15).\n\n"
        "Input preferences:\n"
        "- #1 Preferred Look (young/nenmei, mature/yujie, pure/natural, or custom)\n"
        "- #2 Preferred Body Type (slim/miaotiao, busty/daxiong, tall/changtui, chubby/weipang, petite/jiaoxiao, or custom)\n"
        "- #3 Value Most (gfe/nvyougan, service, face, body, price, balanced, or custom)\n"
        "- #4 Location\n\n"
        "Return JSON schema:\n"
        "{\n"
        '  "keywords": "1-3 concise Chinese keywords for matching tags/summary (e.g. 嫩妹 苗条 or 女友感 御姐 or 清纯 微胖 or 大胸 娇小)",\n'
        '  "weight_focus": "visual" | "body" | "service" | "price" | "balanced",\n'
        '  "weights": {\n'
        '    "visual": float (0.1 to 0.5),\n'
        '    "body": float (0.1 to 0.5),\n'
        '    "service": float (0.1 to 0.5),\n'
        '    "price": float (0.05 to 0.35)\n'
        "  },\n"
        '  "explanation": "A concise 1-sentence explanation in Chinese explaining the query strategy and boosted weight."\n'
        "}"
    )

    if session.latitude and session.longitude:
        coords_str = f"GPS Coordinates (Lat: {session.latitude:.4f}, Lon: {session.longitude:.4f})"
    elif session.location_text:
        coords_str = f"Typed Area/District: {session.location_text}"
    elif session.location_skipped:
        coords_str = "Skipped (Any location)"
    else:
        coords_str = "None"

    user_payload = (
        f"User Answers:\n"
        f"- Look: {session.preferred_look or 'Flexible'}\n"
        f"- Body: {session.preferred_body or 'Flexible'}\n"
        f"- Budget/Price Range: {session.preferred_price or 'Flexible'}\n"
        f"- Value Most: {session.value_most or 'Balanced'}\n"
        f"- Location: {coords_str}\n"
        f"Current City Context: {(teacher_context or {}).get('city') or 'Any'}\n"
    )

    llm_out = None
    provider_pref = (
        os.getenv("REVIEW_EXTRACTOR_PROVIDER")
        or os.getenv("EXTRACTOR_PROVIDER")
        or ("gemini" if os.getenv("GOOGLE_API_KEY") and not os.getenv("DEEPSEEK_API_KEY") else "deepseek")
    ).lower()

    # 1. Preferred provider dispatch
    if provider_pref == "gemini" and os.getenv("GOOGLE_API_KEY"):
        llm_out = await _call_gemini(system_prompt, user_payload)
    elif provider_pref == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        llm_out = await _call_anthropic(system_prompt, user_payload)
    elif provider_pref == "openai" and os.getenv("OPENAI_API_KEY"):
        base_url = os.getenv("OPENAI_BASE_URL")
        model = os.getenv("EXTRACTOR_MODEL") or "gpt-4o-mini"
        llm_out = await _call_deepseek_or_openai(system_prompt, user_payload, api_key=os.getenv("OPENAI_API_KEY"), base_url=base_url, model=model)
    elif os.getenv("DEEPSEEK_API_KEY"):
        base_url = os.getenv("REVIEW_OPENAI_BASE_URL") or "https://api.deepseek.com"
        model = os.getenv("REVIEW_LLM_MODEL") or "deepseek-chat"
        llm_out = await _call_deepseek_or_openai(system_prompt, user_payload, api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=base_url, model=model)

    # 2. Fallbacks if preferred provider failed or wasn't configured
    if not llm_out and os.getenv("DEEPSEEK_API_KEY"):
        base_url = os.getenv("REVIEW_OPENAI_BASE_URL") or "https://api.deepseek.com"
        model = os.getenv("REVIEW_LLM_MODEL") or "deepseek-chat"
        llm_out = await _call_deepseek_or_openai(system_prompt, user_payload, api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=base_url, model=model)

    if not llm_out and os.getenv("OPENAI_API_KEY"):
        base_url = os.getenv("OPENAI_BASE_URL")
        model = os.getenv("EXTRACTOR_MODEL") or "gpt-4o-mini"
        llm_out = await _call_deepseek_or_openai(system_prompt, user_payload, api_key=os.getenv("OPENAI_API_KEY"), base_url=base_url, model=model)

    if not llm_out and os.getenv("GOOGLE_API_KEY"):
        llm_out = await _call_gemini(system_prompt, user_payload)

    if not llm_out and os.getenv("ANTHROPIC_API_KEY"):
        llm_out = await _call_anthropic(system_prompt, user_payload)

    if llm_out and isinstance(llm_out, dict) and llm_out.get("weights"):
        kw_str = str(llm_out.get("keywords") or "").strip()
        kw_list = [k.strip() for k in kw_str.split() if k.strip()]
        return {
            "keywords": kw_str,
            "keywords_list": kw_list,
            "weight_focus": llm_out.get("weight_focus") or "service",
            "weights": llm_out.get("weights") or {"visual": 0.25, "body": 0.25, "service": 0.35, "price": 0.15},
            "city": (teacher_context or {}).get("city") or (teacher_context or {}).get("canonical_city"),
            "location_text": session.location_text,
            "preferred_price": session.preferred_price,
            "price_min": price_min,
            "price_max": price_max,
            "explanation": str(llm_out.get("explanation") or "已完成偏好检索与权重加权排序。"),
            "source": "llm",
        }

    logger.info("No LLM response available; falling back to deterministic heuristic rule generator.")
    return generate_heuristic_search_query(session, teacher_context)
