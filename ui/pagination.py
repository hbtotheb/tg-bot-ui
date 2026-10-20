from __future__ import annotations

from telegram import InlineKeyboardButton

BOLD_TRANS = str.maketrans("0123456789", "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵")


def _to_bold_digits(num: int) -> str:
    return str(num).translate(BOLD_TRANS)


def _make_pagination_row(
    prefix: str, page: int, total_pages: int, total_count: int | None = None
) -> list[InlineKeyboardButton]:
    if total_pages <= 1:
        return []

    buttons: list[InlineKeyboardButton] = []

    # 1. Previous page button
    if page > 0:
        buttons.append(InlineKeyboardButton("◀ 上一页", callback_data=f"{prefix}:{page - 1}"))
    else:
        buttons.append(InlineKeyboardButton("◀", callback_data=f"{prefix}:noop"))

    # 2. Middle page indicator button with total match count
    page_num = page + 1
    if total_count is not None and total_count > 0:
        center_label = f"📄 {page_num}/{total_pages} ({total_count:,}条)"
    else:
        center_label = f"📄 {page_num}/{total_pages}"
    buttons.append(InlineKeyboardButton(center_label, callback_data=f"{prefix}:noop"))

    # 3. Next page button
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("下一页 ▶", callback_data=f"{prefix}:{page + 1}"))
    else:
        buttons.append(InlineKeyboardButton("▶", callback_data=f"{prefix}:noop"))

    return buttons


def _make_control_row(
    prefix: str,
    view_mode: str = "card",
    sort_mode: str = "score",
    sub_query: str | None = None,
) -> list[InlineKeyboardButton]:
    vm_label = "🔄 视图 (展开)" if view_mode == "card" else "🔄 视图 (精简)"
    sort_labels = {
        "recent": "🆕 最新",
        "score": "💎 热门",
        "price_asc": "💰 价格↑",
        "price_desc": "💰 价格↓",
    }
    sort_label = sort_labels.get(sort_mode, "🆕 最新")

    if sub_query:
        display_sub = sub_query[:6] + "…" if len(sub_query) > 6 else sub_query
        sub_label = f"🔎 筛选: {display_sub} ✕"
        sub_cb = f"{prefix}:clearsubkw"
    else:
        sub_label = "🔎 结果内二次筛选"
        sub_cb = f"{prefix}:subkw"

    return [
        InlineKeyboardButton(vm_label, callback_data=f"{prefix}:tvm"),
        InlineKeyboardButton(f"排序: {sort_label}", callback_data=f"{prefix}:tsort"),
        InlineKeyboardButton(sub_label, callback_data=sub_cb),
    ]


