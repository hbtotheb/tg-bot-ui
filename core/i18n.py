from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "help": (
            "✨ <b>全国修车小龙虾</b>\n\n"
            "<blockquote>🦞 <b>欢迎使用全国修车小龙虾！</b>\n"
            "全网严选优质老师、真实体验评测，助您智能选人、安心出行不踩坑。</blockquote>\n\n"
            "🔥 <b>今日高分精选 · 最受喜爱老师 (Top 5)：</b>\n"
            "<blockquote>暂无已收录的高分老师数据</blockquote>\n\n"
            "🆕 <b>新晋入驻 · 最新收录老师 (Top 5)：</b>\n"
            "<blockquote>暂无最新收录的老师数据</blockquote>\n\n"
            "🔍 <b>推荐搜索（点击直接跳转搜索结果）：</b>\n"
            "<blockquote>🏙️ <b>热门商圈：</b> #静安 · #徐汇 · #浦东 · #普陀 · #闵行 · #长宁\n"
            "🏷️ <b>风格特色：</b> #服务好 · #嫩妹 · #女友感 · #身材好 · #御姐</blockquote>\n\n"
            "────────────────────────\n"
            "💡 <i>点击标签直达搜索结果，点击【查看 ➔】直达老师详情资料 👇</i>"
        ),
        "no_results":     "未找到 <b>{query}</b> 的相关结果。",
        "no_channels":    "暂无已索引的频道。",
        "filter_active":  "当前筛选：<b>{name}</b>",
        "filter_none":    "未设置筛选 — 显示全部频道。",
        "filter_prompt":  "\n\n选择频道：",
        "filter_cleared": "已清除筛选，显示全部频道。",
        "filter_set":     "筛选已设置，下次搜索或 /recent 将只显示此频道。\n使用 /filter 可更改。",
        "search_expired": "搜索已过期，请重新搜索。",
        "search_usage":   "用法：/search &lt;关键词&gt;",
        "stats":          "<blockquote>📊 数据库已累计索引 <b>{total:,}</b> 条消息。</blockquote>",
        "footer":         "<i>第 {start}–{end} 条，共 {total} 条 · 第 {page}/{total_pages} 页{filter_hint}</i>",
        "filter_hint":    " · 已筛选",
        "dup_notice":     "ℹ️ <i>已自动合并 {count} 条重复/重发内容</i>",
        "just_now":       "刚刚",
        "minutes_ago":    "{n}分钟前",
        "hours_ago":      "{n}小时前",
        "days_ago":       "{n}天前",
        "weeks_ago":      "{n}周前",
        "months_ago":     "{n}个月前",
        "all_channels":   "全部频道",
        "btn_prev":       "◀ 上一页",
        "btn_next":       "下一页 ▶",
        "recent_label":   "最新消息",
        "browse_title": (
            "💎 <b>信息索引与智能检索大厅</b>\n\n"
            "<blockquote>📋 <b>当前过滤状态：</b>\n"
            "• 🏷️ <b>热门分类：</b> {service}\n"
            "• 🏙️ <b>目标城市：</b> {city}\n"
            "• 📍 <b>地标区域：</b> {district}</blockquote>\n\n"
            "💡 <i>点击下方按钮展开对应分类，完成设置后点击 <b>“🚀 立即查询结果”</b>。</i>"
        ),
        "browse_service": "🏷️ 项目: {value}",
        "browse_city":    "🏙️ 城市: {value}",
        "browse_district":"📍 区域: {value}",
        "browse_price":   "💰 价格: {value}",
        "browse_any":     "任意",
        "browse_pick_service": "🏷️ <b>请选择服务项目类型：</b>",
        "browse_pick_city":    "🏙️ <b>请选择目标城市：</b>",
        "browse_pick_district":"📍 <b>请选择特定区域：</b>",
        "browse_pick_price": "💰 <b>请选择价格区间：</b>",
        "browse_no_locs":    "暂无可用地点（尚未提取）。",
        "browse_no_results": "没有匹配的列表。",
        "btn_show":       "▶ 显示结果",
        "btn_reset":      "✕ 重置筛选",
        "btn_back":       "← 返回",
        "btn_filters":    "← 返回筛选",
        "type_massage":    "按摩",
        "type_wellness":   "养生/SPA",
        "type_experience": "手推/4T",
        "type_bathing":    "洗浴/泡澡",
        "type_other":      "其他",
        "price_lt100":    "< 100",
        "price_100_500":  "100 – 500",
        "price_500_1k":   "500 – 1k",
        "price_1k_5k":    "1k – 5k",
        "price_5k_plus":  "5k+",
        "listing_line":   "🏷️ <b>{type}</b> · 🏙️ <b>{city} {district}</b>",
        "browse_footer":  "<i>共 {total} 条 · 第 {page}/{total_pages} 页</i>",
        "btn_menu":       "🏠 返回主菜单",
        "btn_ads":        "📢 广告合作",
        "btn_cities":     "🏙️ 城市选择",
        "btn_subscribe":  "💎 订阅解锁",
        "btn_mode":       "🔄 切换模式",
        "ads_placeholder": (
            "<b>📢 广告合作</b>\n\n"
            "<blockquote>欢迎商务合作与广告投放。\n请联系商务咨询专属推广与赞助合作。</blockquote>"
        ),
        "cities_placeholder": (
            "<b>🏙️ 城市选择 (内测中)</b>\n\n"
            "<blockquote>请选择您感兴趣的目标城市：\n"
            "• 北京 · 上海 · 广州 · 深圳</blockquote>\n\n"
            "<i>更多城市数据正持续接入上线...</i>"
        ),
        "subscribe_placeholder": (
            "<b>💎 订阅解锁更多高级功能</b>\n\n"
            "<blockquote>解锁 VIP 权限，享受极致搜索体验：\n"
            "• 无限次高频检索\n"
            "• 关键词实时变动推送\n"
            "• 多维度精准数据导出</blockquote>\n\n"
            "点击下方按钮查看订阅详情。"
        ),
        "mode_placeholder": (
            "<b>🔄 切换机器人工作模式</b>\n\n"
            "<blockquote>当前工作模式：<b>普通搜索</b>\n\n"
            "可选模式：\n"
            "• 专业模式 (全字段详细对比)\n"
            "• 精简模式 (纯文本速览)\n"
            "• 交易模式 (专注价格与商家)</blockquote>"
        ),
        "news_feed_placeholder": (
            "<b>📰 行业新闻与资讯动态</b>\n\n"
            "<blockquote>1. 【动态】本周新增索引频道 5 个，数据覆盖面进一步扩大。\n"
            "2. 【通知】系统维护已完成，搜索响应速度提升 30%。\n"
            "3. 【行业】关于防范虚假信息与欺诈列表的安全提示。</blockquote>\n\n"
            "<i>我们将持续为您推送精选资讯。</i>"
        ),
        "err_server_busy_alert": "⚠️ 系统繁忙，请稍后再试。",
        "err_server_busy_msg": "⚠️ <b>系统通知</b>\n<blockquote>系统繁忙，请稍后再试。</blockquote>",
    },
}



DEFAULT_LANG = "zh"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("zh",)


def get_lang(language_code: str | None = None) -> str:
    """Return active language for the user.

    English is disabled for now; all users are served Chinese ('zh').
    The i18n structure is preserved so English (or other locales) can be seamlessly re-enabled.
    """
    return DEFAULT_LANG


def t(key: str, lang: str = DEFAULT_LANG, **kwargs: object) -> str:
    """Translate string key with interpolation, strictly falling back to DEFAULT_LANG ('zh')."""
    effective_lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANG

    if key.startswith("group_"):
        from .service_registry import category_groups
        group_code = key[6:].upper()
        if group_code in category_groups.groups:
            return category_groups.get_label(group_code, effective_lang)

    if key.startswith("type_"):
        from .service_registry import category_groups, registry
        category_code = key[5:].upper()
        if category_code in category_groups.groups:
            return category_groups.get_label(category_code, effective_lang)
        if category_code in registry.categories:
            return registry.get_label(category_code, effective_lang)

    text = STRINGS.get(effective_lang, {}).get(key) or STRINGS[DEFAULT_LANG].get(key, f"[{key}]")
    return text.format(**kwargs) if kwargs else text
