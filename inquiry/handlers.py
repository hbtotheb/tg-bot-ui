from __future__ import annotations

import html
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import ContextTypes

try:
    from bot.core.shared import db
except ImportError:
    from core.shared import db

from .llm import generate_search_query, normalize_combo_key
from .rate_limiter import inquiry_rate_limiter
from .search import search_and_rank_teachers
from .state import InquirySession, InquiryStep, inquiry_state_manager
from .ui import (
    render_body_step,
    render_confirm_step,
    render_inquiry_summary,
    render_look_step,
    render_map_step,
    render_matched_teacher_card,
    render_price_step,
    render_value_step,
)

logger = logging.getLogger(__name__)


async def start_inquiry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    teacher_id: int | None = None,
    from_index: int = 0,
) -> None:
    """Initiate the 4-step preference matching wizard (from homepage or teacher card)."""
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    # 1. Quota Check (Enforces daily submission cap)
    limited, reason = inquiry_rate_limiter.is_submission_limited(user.id, user.username)
    if limited and "Daily" in (reason or ""):
        if update.callback_query:
            try:
                await update.callback_query.answer(reason, show_alert=True)
            except Exception:
                pass
        elif update.effective_message:
            await update.effective_message.reply_text(reason)
        return

    # 2. Fetch Teacher Profile (if initiated from a teacher card)
    teacher = None
    if teacher_id:
        teacher = await db.get_teacher(teacher_id)
        if not teacher:
            if update.callback_query:
                try:
                    await update.callback_query.answer("未找到该老师信息，请返回重试。", show_alert=True)
                except Exception:
                    pass
            return

    raw_bot_user = getattr(context.bot, "username", None) if context and context.bot else None
    bot_username = (
        raw_bot_user
        if isinstance(raw_bot_user, str) and raw_bot_user
        else (os.getenv("TELEGRAM_BOT_USERNAME") or os.getenv("BOT_USERNAME") or "tg_search_bot")
    )

    # 3. Create Session (Starts at Question #1: LOOK)
    session = inquiry_state_manager.create_session(
        user_id=user.id,
        chat_id=chat.id,
        teacher_id=teacher_id or 0,
        from_index=from_index,
        teacher=teacher or {},
        bot_username=bot_username,
    )
    if context and getattr(context, "user_data", None) is not None:
        context.user_data["inquiry_active"] = True

    # 4. Render Question #1: Preferred Look
    text, markup = render_look_step(teacher, session)
    if update.callback_query and update.callback_query.message:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        msg = update.callback_query.message
        if msg.photo:
            try:
                await msg.delete()
            except Exception:
                pass
            sent = await context.bot.send_message(
                chat_id=chat.id,
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
            session.prompt_message_id = sent.message_id
        else:
            try:
                await update.callback_query.edit_message_text(
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                session.prompt_message_id = msg.message_id
            except Exception as err:
                logger.debug("edit_message_text failed in start_inquiry (%s), falling back to send_message", err)
                try:
                    await msg.delete()
                except Exception:
                    pass
                sent = await context.bot.send_message(
                    chat_id=chat.id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                session.prompt_message_id = sent.message_id
    elif update.effective_message:
        sent = await update.effective_message.reply_text(
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
        session.prompt_message_id = sent.message_id


async def on_inquiry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback router for inq: prefixed inline button queries."""
    if not update.callback_query or not update.callback_query.data:
        return

    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    if inquiry_rate_limiter.is_action_limited(user.id, user.username):
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        return

    data = update.callback_query.data
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        await update.callback_query.answer()
    except Exception:
        pass

    # Swiping through inquiry matching search results
    if action == "swipe":
        target_index = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        matched_ids = context.user_data.get("inquiry_matched_ids", [])
        query_info = context.user_data.get("inquiry_query_info", {})

        if not matched_ids:
            return

        clamped_idx = max(0, min(target_index, len(matched_ids) - 1))
        tid = matched_ids[clamped_idx]
        matched_teachers = context.user_data.get("inquiry_matched_teachers", {})
        teacher = matched_teachers.get(tid)
        if not teacher:
            teacher = await db.get_teacher(tid)
            if teacher and isinstance(matched_teachers, dict):
                matched_teachers[tid] = teacher
        if not teacher:
            return

        try:
            from bot.handlers.teachers import _resolve_teacher_link, _resolve_teacher_photo, get_teacher_photo
        except ImportError:
            from handlers.teachers import _resolve_teacher_link, _resolve_teacher_photo, get_teacher_photo

        await _resolve_teacher_link(teacher)
        await _resolve_teacher_photo(teacher)
        caption, markup = render_matched_teacher_card(teacher, clamped_idx, len(matched_ids), query_info)
        photo_path = get_teacher_photo(teacher)

        msg = update.callback_query.message
        if msg and msg.photo:
            if photo_path and os.path.exists(photo_path):
                try:
                    from bot.handlers.teachers import _PHOTO_FILE_ID_CACHE
                except ImportError:
                    _PHOTO_FILE_ID_CACHE = {}
                cached_file_id = _PHOTO_FILE_ID_CACHE.get(photo_path)
                try:
                    if cached_file_id:
                        media = InputMediaPhoto(media=cached_file_id, caption=caption, parse_mode="HTML")
                        res = await update.callback_query.edit_message_media(media=media, reply_markup=markup)
                    else:
                        with open(photo_path, "rb") as f:
                            media = InputMediaPhoto(media=f, caption=caption, parse_mode="HTML")
                            res = await update.callback_query.edit_message_media(media=media, reply_markup=markup)
                        if res and hasattr(res, "photo") and res.photo:
                            _PHOTO_FILE_ID_CACHE[photo_path] = res.photo[-1].file_id
                except Exception:
                    try:
                        await update.callback_query.edit_message_caption(caption=caption, parse_mode="HTML", reply_markup=markup)
                    except Exception:
                        pass
            else:
                try:
                    await update.callback_query.edit_message_caption(caption=caption, parse_mode="HTML", reply_markup=markup)
                except Exception:
                    pass
        elif msg:
            if photo_path and os.path.exists(photo_path):
                try:
                    await msg.delete()
                except Exception:
                    pass
                try:
                    from bot.handlers.teachers import _PHOTO_FILE_ID_CACHE
                except ImportError:
                    _PHOTO_FILE_ID_CACHE = {}
                cached_file_id = _PHOTO_FILE_ID_CACHE.get(photo_path)
                try:
                    if cached_file_id:
                        sent = await context.bot.send_photo(
                            chat_id=chat.id,
                            photo=cached_file_id,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=markup,
                        )
                    else:
                        with open(photo_path, "rb") as f:
                            sent = await context.bot.send_photo(
                                chat_id=chat.id,
                                photo=f,
                                caption=caption,
                                parse_mode="HTML",
                                reply_markup=markup,
                            )
                        if sent and hasattr(sent, "photo") and sent.photo:
                            _PHOTO_FILE_ID_CACHE[photo_path] = sent.photo[-1].file_id
                    return
                except Exception as e:
                    logger.warning("Failed sending photo in inq:swipe: %s", e)
            try:
                await update.callback_query.edit_message_text(text=caption, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
            except Exception:
                pass
        return

    # View summary report from matched teacher card
    if action == "summary":
        curr_index = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        matched_ids = context.user_data.get("inquiry_matched_ids", [])
        query_info = context.user_data.get("inquiry_query_info", {})
        summary_data = context.user_data.get("inquiry_summary_data", {})

        summary_text, summary_markup = render_inquiry_summary(
            summary_data,
            query_info,
            len(matched_ids),
            current_index=curr_index,
        )

        msg = update.callback_query.message
        if msg and msg.photo:
            try:
                await update.callback_query.edit_message_caption(
                    caption=summary_text, parse_mode="HTML", reply_markup=summary_markup
                )
            except Exception:
                pass
        elif msg:
            try:
                await update.callback_query.edit_message_text(
                    text=summary_text, parse_mode="HTML", reply_markup=summary_markup, disable_web_page_preview=True
                )
            except Exception:
                pass
        return

    # Reviews overview for matched inquiry teacher card
    if action == "rev":
        # Format: inq:rev:{teacher_id}:{from_index} or inq:rev:{teacher_id}:{from_index}:{page}
        try:
            teacher_id = int(parts[2])
            from_index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        except (IndexError, ValueError):
            return

        page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0

        teacher = await db.get_teacher(teacher_id)
        if not teacher:
            return

        try:
            from bot.handlers.teachers import _resolve_teacher_link, _resolve_teacher_photo, format_teacher_reviews
        except ImportError:
            from handlers.teachers import _resolve_teacher_link, _resolve_teacher_photo, format_teacher_reviews

        await _resolve_teacher_link(teacher)
        await _resolve_teacher_photo(teacher)
        rc = teacher.get("review_count")
        limit = max(50, int(rc)) if rc is not None else 50
        reviews = await db.get_teacher_reviews(teacher_id, limit=limit)
        raw_bot_user = getattr(context.bot, "username", None)
        bot_username = raw_bot_user if isinstance(raw_bot_user, str) and raw_bot_user else None

        caption, markup = format_teacher_reviews(
            teacher,
            reviews,
            from_index,
            page=page,
            page_size=6,
            bot_username=bot_username,
            back_callback=f"inq:swipe:{from_index}",
            review_callback_prefix="inq",
        )

        msg = update.callback_query.message
        if msg and msg.photo:
            try:
                await update.callback_query.edit_message_caption(
                    caption=caption, parse_mode="HTML", reply_markup=markup
                )
            except Exception:
                pass
        elif msg:
            try:
                await update.callback_query.edit_message_text(
                    text=caption, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
                )
            except Exception:
                pass
        return

    # Review detail view for matched inquiry teacher card
    if action == "rdtl":
        # Format: inq:rdtl:{teacher_id}:{from_index}:{review_id}:{page}:{review_num}
        try:
            teacher_id = int(parts[2])
            from_index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            review_id = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
            page = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
            review_num = int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 1
        except (IndexError, ValueError):
            return

        try:
            from bot.handlers.teachers import show_review_detail
        except ImportError:
            from handlers.teachers import show_review_detail

        await show_review_detail(
            update,
            context,
            teacher_id,
            review_id,
            from_index,
            page,
            review_num,
            back_callback=f"inq:swipe:{from_index}",
            review_list_callback=f"inq:rev:{teacher_id}:{from_index}:{page}",
        )
        return

    # Start action (e.g. from homepage)
    if action == "start":
        await start_inquiry(update, context)
        return

    # Cancel action
    if action == "cancel":
        inquiry_state_manager.clear_session(user.id)
        if context and getattr(context, "user_data", None) is not None:
            context.user_data.pop("inquiry_active", None)
        cancel_text = "❌ <b>已取消 AI 对话匹配。</b>"
        await update.callback_query.edit_message_text(
            text=cancel_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 返回机器人首页", callback_data="feat:start")]]),
        )
        return

    # Restart action
    if action == "restart":
        tid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        from_idx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        if tid > 0:
            await start_inquiry(update, context, tid, from_idx)
        else:
            await start_inquiry(update, context)
        return

    # Back to teacher card action
    if action == "back":
        tid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        from_idx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        inquiry_state_manager.clear_session(user.id)
        if context and getattr(context, "user_data", None) is not None:
            context.user_data.pop("inquiry_active", None)
        try:
            from bot.handlers.teachers import on_teacher_card_callback
        except ImportError:
            from handlers.teachers import on_teacher_card_callback
        update.callback_query.data = f"tc:swipe:{from_idx}"
        await on_teacher_card_callback(update, context)
        return

    session = inquiry_state_manager.get_session(user.id)
    if not session:
        await update.callback_query.edit_message_text(
            "⏳ 匹配会话已过期，请重新点击「AI对话」发起。",
            parse_mode="HTML",
        )
        return

    teacher = (await db.get_teacher(session.teacher_id)) if session.teacher_id else {}
    if not teacher:
        teacher = {}

    # Navigation redirect actions
    if action == "goto":
        target = parts[2] if len(parts) > 2 else ""
        if target == "look":
            inquiry_state_manager.update_step(user.id, InquiryStep.LOOK)
            look_text, look_markup = render_look_step(teacher, session)
            await update.callback_query.edit_message_text(
                text=look_text,
                parse_mode="HTML",
                reply_markup=look_markup,
            )
            return
        elif target == "body":
            inquiry_state_manager.update_step(user.id, InquiryStep.BODY)
            body_text, body_markup = render_body_step(teacher, session)
            await update.callback_query.edit_message_text(
                text=body_text,
                parse_mode="HTML",
                reply_markup=body_markup,
            )
            return
        elif target == "price":
            inquiry_state_manager.update_step(user.id, InquiryStep.PRICE)
            price_text, price_markup = render_price_step(teacher, session)
            await update.callback_query.edit_message_text(
                text=price_text,
                parse_mode="HTML",
                reply_markup=price_markup,
            )
            return
        elif target == "val":
            inquiry_state_manager.update_step(user.id, InquiryStep.VALUE)
            val_text, val_markup = render_value_step(teacher, session)
            await update.callback_query.edit_message_text(
                text=val_text,
                parse_mode="HTML",
                reply_markup=val_markup,
            )
            return
        elif target == "map":
            inquiry_state_manager.update_step(user.id, InquiryStep.MAP)
            map_text, map_markup = render_map_step(teacher, session)
            msg = update.callback_query.message
            if msg:
                try:
                    await msg.delete()
                except Exception:
                    pass
            sent = await context.bot.send_message(
                chat_id=chat.id,
                text=map_text,
                parse_mode="HTML",
                reply_markup=map_markup,
            )
            session.prompt_message_id = sent.message_id
            return
        elif target == "confirm":
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            await update.callback_query.edit_message_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            return

    # Submit action from confirmation review screen
    if action == "submit":
        await _complete_inquiry(update, context, session, teacher)
        return

    # Question #1 (Look) -> Question #2 (Body) or Confirmation if confirmed_once
    if action == "look":
        look_val = parts[2] if len(parts) > 2 else "不限风格"
        session.preferred_look = look_val
        if session.confirmed_once:
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            await update.callback_query.edit_message_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            return

        inquiry_state_manager.update_step(user.id, InquiryStep.BODY)
        body_text, body_markup = render_body_step(teacher, session)
        try:
            await update.callback_query.edit_message_text(
                text=body_text,
                parse_mode="HTML",
                reply_markup=body_markup,
            )
        except Exception as err:
            logger.debug("edit_message_text failed in look step (%s), falling back to send_message", err)
            sent = await context.bot.send_message(
                chat_id=chat.id,
                text=body_text,
                parse_mode="HTML",
                reply_markup=body_markup,
            )
            session.prompt_message_id = sent.message_id
        return

    # Question #2 (Body) -> Question #3 (Price Range) or Confirmation if confirmed_once
    if action == "body":
        body_val = parts[2] if len(parts) > 2 else "不限身材"
        session.preferred_body = body_val
        if session.confirmed_once:
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            await update.callback_query.edit_message_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            return

        inquiry_state_manager.update_step(user.id, InquiryStep.PRICE)
        price_text, price_markup = render_price_step(teacher, session)
        try:
            await update.callback_query.edit_message_text(
                text=price_text,
                parse_mode="HTML",
                reply_markup=price_markup,
            )
        except Exception as err:
            logger.debug("edit_message_text failed in body step (%s), falling back to send_message", err)
            sent = await context.bot.send_message(
                chat_id=chat.id,
                text=price_text,
                parse_mode="HTML",
                reply_markup=price_markup,
            )
            session.prompt_message_id = sent.message_id
        return

    # Question #3 (Price Range) -> Question #4 (Value Most) or Confirmation if confirmed_once
    if action == "price":
        price_val = parts[2] if len(parts) > 2 else "不限预算"
        session.preferred_price = price_val
        if session.confirmed_once:
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            await update.callback_query.edit_message_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            return

        inquiry_state_manager.update_step(user.id, InquiryStep.VALUE)
        val_text, val_markup = render_value_step(teacher, session)
        try:
            await update.callback_query.edit_message_text(
                text=val_text,
                parse_mode="HTML",
                reply_markup=val_markup,
            )
        except Exception as err:
            logger.debug("edit_message_text failed in price step (%s), falling back to send_message", err)
            sent = await context.bot.send_message(
                chat_id=chat.id,
                text=val_text,
                parse_mode="HTML",
                reply_markup=val_markup,
            )
            session.prompt_message_id = sent.message_id
        return

    # Question #3 (Value Most) -> Question #4 (Map Pin) or Confirmation if confirmed_once
    if action == "val":
        val_choice = parts[2] if len(parts) > 2 else "综合体验"
        session.value_most = val_choice
        if session.confirmed_once:
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            await update.callback_query.edit_message_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            return

        inquiry_state_manager.update_step(user.id, InquiryStep.MAP)
        # Delete previous inline message and present location ReplyKeyboard
        map_text, map_markup = render_map_step(teacher, session)
        msg = update.callback_query.message
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        sent = await context.bot.send_message(
            chat_id=chat.id,
            text=map_text,
            parse_mode="HTML",
            reply_markup=map_markup,
        )
        session.prompt_message_id = sent.message_id
        return


async def on_inquiry_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Question #4 location update sent via Telegram map pin or share location button."""
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or not update.message or not update.message.location:
        return

    session = inquiry_state_manager.get_session(user.id)
    if not session or session.step != InquiryStep.MAP:
        return

    loc = update.message.location
    session.latitude = loc.latitude
    session.longitude = loc.longitude
    session.location_text = None
    session.location_skipped = False
    session.confirmed_once = True
    inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)

    await update.message.reply_text(
        "📍 <b>已成功采集到您的位置坐标。</b>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    teacher = (await db.get_teacher(session.teacher_id)) if session.teacher_id else {}
    if not teacher:
        teacher = {}
    confirm_text, confirm_markup = render_confirm_step(teacher, session)
    sent = await update.message.reply_text(
        text=confirm_text,
        parse_mode="HTML",
        reply_markup=confirm_markup,
    )
    session.prompt_message_id = sent.message_id


async def on_inquiry_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle plain text inputs during wizard questions (allowing users to type custom answers).
    Returns True if consumed by an active inquiry session, False otherwise.
    """
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or not update.message or not update.message.text:
        return False

    session = inquiry_state_manager.get_session(user.id)
    if not session:
        return False

    raw_text = update.message.text.strip()
    teacher = (await db.get_teacher(session.teacher_id)) if session.teacher_id else {}
    if not teacher:
        teacher = {}

    # Global Cancel check
    if raw_text in ("取消", "取消匹配", "取消预约", "/cancel") or raw_text.lower() == "cancel":
        inquiry_state_manager.clear_session(user.id)
        if context and getattr(context, "user_data", None) is not None:
            context.user_data.pop("inquiry_active", None)
        await update.message.reply_text(
            "❌ <b>已取消 AI 对话匹配。</b>\n\n💡 随时发送 /start 返回首页重新开启。",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        return True

    # In-chat edit commands (e.g. /edit_look, /edit_body, /look, /body, /edit_price, /price)
    if raw_text in ("/edit_look", "/look", "/edit_1"):
        inquiry_state_manager.update_step(user.id, InquiryStep.LOOK)
        text, markup = render_look_step(teacher, session)
        sent = await update.message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
        return True
    if raw_text in ("/edit_body", "/body", "/edit_2"):
        inquiry_state_manager.update_step(user.id, InquiryStep.BODY)
        text, markup = render_body_step(teacher, session)
        sent = await update.message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
        return True
    if raw_text in ("/edit_price", "/price", "/edit_3"):
        inquiry_state_manager.update_step(user.id, InquiryStep.PRICE)
        text, markup = render_price_step(teacher, session)
        sent = await update.message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
        return True
    if raw_text in ("/edit_val", "/val", "/edit_4"):
        inquiry_state_manager.update_step(user.id, InquiryStep.VALUE)
        text, markup = render_value_step(teacher, session)
        sent = await update.message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
        return True
    if raw_text in ("/edit_map", "/map", "/edit_5"):
        inquiry_state_manager.update_step(user.id, InquiryStep.MAP)
        text, markup = render_map_step(teacher, session)
        sent = await update.message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
        return True
    if raw_text in ("/edit_confirm", "/confirm"):
        inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
        text, markup = render_confirm_step(teacher, session)
        sent = await update.message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
        return True

    # #1 Question: Preferred Look typed text
    if session.step == InquiryStep.LOOK:
        session.preferred_look = raw_text[:50]
        if session.confirmed_once:
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            sent = await update.message.reply_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            session.prompt_message_id = sent.message_id
            return True

        inquiry_state_manager.update_step(user.id, InquiryStep.BODY)
        body_text, body_markup = render_body_step(teacher, session)
        sent = await update.message.reply_text(
            text=body_text,
            parse_mode="HTML",
            reply_markup=body_markup,
        )
        session.prompt_message_id = sent.message_id
        return True

    # #2 Question: Preferred Body Type typed text
    if session.step == InquiryStep.BODY:
        session.preferred_body = raw_text[:50]
        if session.confirmed_once:
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            sent = await update.message.reply_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            session.prompt_message_id = sent.message_id
            return True

        inquiry_state_manager.update_step(user.id, InquiryStep.PRICE)
        price_text, price_markup = render_price_step(teacher, session)
        sent = await update.message.reply_text(
            text=price_text,
            parse_mode="HTML",
            reply_markup=price_markup,
        )
        session.prompt_message_id = sent.message_id
        return True

    # #3 Question: Price Range typed text (RESTRICTED INPUT)
    if session.step == InquiryStep.PRICE:
        PRICE_MAPPINGS = {
            # 300 range granularity (1P standard)
            "600以下": "600以下(1P)",
            "<600": "600以下(1P)",
            "< 600": "600以下(1P)",
            "<=600": "600以下(1P)",
            "600以下(1p)": "600以下(1P)",
            "600以下(1p标准)": "600以下(1P)",
            "600-900": "600-900(1P)",
            "600 - 900": "600-900(1P)",
            "600~900": "600-900(1P)",
            "600到900": "600-900(1P)",
            "600至900": "600-900(1P)",
            "600-900(1p)": "600-900(1P)",
            "900-1200": "900-1200(1P)",
            "900 - 1200": "900-1200(1P)",
            "900~1200": "900-1200(1P)",
            "900到1200": "900-1200(1P)",
            "900至1200": "900-1200(1P)",
            "900-1200(1p)": "900-1200(1P)",
            "1200-1500": "1200-1500(1P)",
            "1200 - 1500": "1200-1500(1P)",
            "1200~1500": "1200-1500(1P)",
            "1200到1500": "1200-1500(1P)",
            "1200至1500": "1200-1500(1P)",
            "1200-1500(1p)": "1200-1500(1P)",
            "1500-1800": "1500-1800(1P)",
            "1500 - 1800": "1500-1800(1P)",
            "1500~1800": "1500-1800(1P)",
            "1500到1800": "1500-1800(1P)",
            "1500至1800": "1500-1800(1P)",
            "1500-1800(1p)": "1500-1800(1P)",
            "1800以上": "1800以上(1P)",
            ">1800": "1800以上(1P)",
            "> 1800": "1800以上(1P)",
            ">=1800": "1800以上(1P)",
            "1800+": "1800以上(1P)",
            "1800以上(1p)": "1800以上(1P)",
            # Legacy inputs
            "800以下": "600-900(1P)",
            "<800": "600-900(1P)",
            "< 800": "600-900(1P)",
            "800-1200": "900-1200(1P)",
            "800 - 1200": "900-1200(1P)",
            "800~1200": "900-1200(1P)",
            "1200-1800": "1200-1500(1P)",
            "1200 - 1800": "1200-1500(1P)",
            "1200~1800": "1200-1500(1P)",
            # No limit
            "不限": "不限预算",
            "不限预算": "不限预算",
            "均可不限": "不限预算",
            "均可": "不限预算",
            "any": "不限预算",
        }
        clean_input = raw_text.strip().lower().replace(" ", "").replace("（", "(").replace("）", ")")
        matched = None
        for k, v in PRICE_MAPPINGS.items():
            if clean_input == k.replace(" ", ""):
                matched = v
                break

        if not matched:
            # Check general range pattern
            m_range = re.search(r"(\d+)\s*[-~至到]\s*(\d+)", clean_input)
            if m_range:
                high = float(m_range.group(2))
                if high <= 600:
                    matched = "600以下(1P)"
                elif high <= 900:
                    matched = "600-900(1P)"
                elif high <= 1200:
                    matched = "900-1200(1P)"
                elif high <= 1500:
                    matched = "1200-1500(1P)"
                elif high <= 1800:
                    matched = "1500-1800(1P)"
                else:
                    matched = "1800以上(1P)"
            elif clean_input.isdigit():
                num = float(clean_input)
                if num <= 600:
                    matched = "600以下(1P)"
                elif num <= 900:
                    matched = "600-900(1P)"
                elif num <= 1200:
                    matched = "900-1200(1P)"
                elif num <= 1500:
                    matched = "1200-1500(1P)"
                elif num <= 1800:
                    matched = "1500-1800(1P)"
                else:
                    matched = "1800以上(1P)"

        if matched:
            session.preferred_price = matched
            if session.confirmed_once:
                inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
                confirm_text, confirm_markup = render_confirm_step(teacher, session)
                sent = await update.message.reply_text(
                    text=confirm_text,
                    parse_mode="HTML",
                    reply_markup=confirm_markup,
                )
                session.prompt_message_id = sent.message_id
                return True

            inquiry_state_manager.update_step(user.id, InquiryStep.VALUE)
            val_text, val_markup = render_value_step(teacher, session)
            sent = await update.message.reply_text(
                text=val_text,
                parse_mode="HTML",
                reply_markup=val_markup,
            )
            session.prompt_message_id = sent.message_id
            return True

        # Restrict user input in chat: reject arbitrary free-text and present range buttons
        reject_text = (
            "⚠️ <b>单次预算（1P）请点击下方按钮选择</b>\n"
            "<i>为保障匹配精准度，本项仅支持预设区间选项（300梯度），暂不支持自定义文字输入。</i>\n\n"
            "<i>Please select a 1P price range using the buttons below:</i>"
        )
        _, markup = render_price_step(teacher, session)
        sent = await update.message.reply_text(
            text=reject_text,
            parse_mode="HTML",
            reply_markup=markup,
        )
        session.prompt_message_id = sent.message_id
        return True

    # #4 Question: What You Value Most typed text
    if session.step == InquiryStep.VALUE:
        session.value_most = raw_text[:50]
        if session.confirmed_once:
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            sent = await update.message.reply_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            session.prompt_message_id = sent.message_id
            return True

        inquiry_state_manager.update_step(user.id, InquiryStep.MAP)
        map_text, map_markup = render_map_step(teacher, session)
        sent = await update.message.reply_text(
            text=map_text,
            parse_mode="HTML",
            reply_markup=map_markup,
        )
        session.prompt_message_id = sent.message_id
        return True

    # #4 Question: Map Pin typed text (e.g. "跳过位置", "skip", custom district/landmark, or "返回确认清单")
    if session.step == InquiryStep.MAP:
        if "返回确认清单" in raw_text or raw_text == "返回":
            session.confirmed_once = True
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            await update.message.reply_text(
                "↩️ <b>已返回确认清单。</b>",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove(),
            )
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            sent = await update.message.reply_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            session.prompt_message_id = sent.message_id
            return True

        if "跳过" in raw_text or "skip" in raw_text.lower():
            session.location_skipped = True
            session.latitude = None
            session.longitude = None
            session.location_text = None
            session.confirmed_once = True
            inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
            await update.message.reply_text(
                "⏭️ <b>已跳过位置设置。</b>",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove(),
            )
            confirm_text, confirm_markup = render_confirm_step(teacher, session)
            sent = await update.message.reply_text(
                text=confirm_text,
                parse_mode="HTML",
                reply_markup=confirm_markup,
            )
            session.prompt_message_id = sent.message_id
            return True

        # Custom typed location text (district, landmark, address, etc.)
        session.location_text = raw_text[:50]
        session.latitude = None
        session.longitude = None
        session.location_skipped = False
        session.confirmed_once = True
        inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
        await update.message.reply_text(
            f"📍 <b>已记录您的位置区域：</b> <code>{html.escape(session.location_text)}</code>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        confirm_text, confirm_markup = render_confirm_step(teacher, session)
        sent = await update.message.reply_text(
            text=confirm_text,
            parse_mode="HTML",
            reply_markup=confirm_markup,
        )
        session.prompt_message_id = sent.message_id
        return True

    # #5 Confirmed Step: User types text while viewing confirmation list
    if session.step == InquiryStep.CONFIRMED:
        confirm_text, confirm_markup = render_confirm_step(teacher, session)
        sent = await update.message.reply_text(
            text=f"💡 <i>您已处于需求确认清单。点击下方对应按钮可修改要求，确认无误后点击「🚀 确认需求，开始智能匹配」开始匹配：</i>\n\n{confirm_text}",
            parse_mode="HTML",
            reply_markup=confirm_markup,
        )
        session.prompt_message_id = sent.message_id
        return True

    return False


async def handle_inquiry_deeplink(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    param: str,
) -> None:
    """
    Handle deep link parameters from in-chat answer edit links (e.g. /start inq_look).
    Directs the user straight to the requested step to edit their answer.
    """
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or not update.effective_message:
        return

    session = inquiry_state_manager.get_session(user.id)
    if not session:
        await update.effective_message.reply_text(
            "⏳ <b>匹配会话已过期，请点击下方「AI对话」重新发起。</b>",
            parse_mode="HTML",
        )
        return

    raw_bot_user = getattr(context.bot, "username", None) if context and context.bot else None
    if raw_bot_user and not session.bot_username:
        session.bot_username = raw_bot_user

    teacher = (await db.get_teacher(session.teacher_id)) if session.teacher_id else {}
    if not teacher:
        teacher = {}

    target = param.replace("inq_", "")
    if target == "look":
        inquiry_state_manager.update_step(user.id, InquiryStep.LOOK)
        text, markup = render_look_step(teacher, session)
        sent = await update.effective_message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
    elif target == "body":
        inquiry_state_manager.update_step(user.id, InquiryStep.BODY)
        text, markup = render_body_step(teacher, session)
        sent = await update.effective_message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
    elif target == "price":
        inquiry_state_manager.update_step(user.id, InquiryStep.PRICE)
        text, markup = render_price_step(teacher, session)
        sent = await update.effective_message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
    elif target == "val":
        inquiry_state_manager.update_step(user.id, InquiryStep.VALUE)
        text, markup = render_value_step(teacher, session)
        sent = await update.effective_message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
    elif target == "map":
        inquiry_state_manager.update_step(user.id, InquiryStep.MAP)
        text, markup = render_map_step(teacher, session)
        sent = await update.effective_message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id
    elif target == "confirm":
        inquiry_state_manager.update_step(user.id, InquiryStep.CONFIRMED)
        text, markup = render_confirm_step(teacher, session)
        sent = await update.effective_message.reply_text(text=text, parse_mode="HTML", reply_markup=markup)
        session.prompt_message_id = sent.message_id


async def _complete_inquiry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: InquirySession,
    teacher: dict[str, Any],
) -> None:
    """
    Synthesize user preferences into an LLM search query, execute weighted search,
    and display the top matching teacher card with swipe navigation.
    """
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    # Check submission cooldown / daily quota
    limited, reason = inquiry_rate_limiter.is_submission_limited(user.id, user.username)
    if limited and reason and "wait" in reason.lower():
        if update.effective_message:
            await update.effective_message.reply_text(f"⏳ {reason}")
        return

    loading_msg = None
    combo_key = normalize_combo_key(session.preferred_look, session.preferred_body, session.value_most)
    if not combo_key and update.effective_message:
        try:
            loading_msg = await update.effective_message.reply_text(
                "⚡ <b>正在通过 AI 转换偏好检索式并智能排序推荐...</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass

    # 1. LLM synthesizes search query keywords and custom weights
    query_info = await generate_search_query(session, teacher)
    inquiry_rate_limiter.record_submission(user.id)

    # 2. Search database and rank candidate teachers using custom query weights
    ranked_teachers = await search_and_rank_teachers(
        db=db,
        query_info=query_info,
        user_lat=session.latitude,
        user_lon=session.longitude,
        location_text=session.location_text,
        limit=20,
    )

    # 3. Clean up loading placeholder
    if loading_msg:
        try:
            await loading_msg.delete()
        except Exception:
            pass

    # Fallback to current teacher if no candidates found
    if not ranked_teachers:
        ranked_teachers = [teacher] if teacher else []

    if not ranked_teachers:
        if update.effective_message:
            await update.effective_message.reply_text("暂未找到符合条件的老师，请稍后重试。")
        inquiry_state_manager.clear_session(user.id)
        return

    # Cache matched results and summary data for swiping and viewing summary report
    if context and getattr(context, "user_data", None) is not None:
        context.user_data["inquiry_matched_ids"] = [t["id"] for t in ranked_teachers]
        context.user_data["inquiry_matched_teachers"] = {t["id"]: dict(t) for t in ranked_teachers}
        context.user_data["inquiry_query_info"] = query_info
        context.user_data["inquiry_summary_data"] = {
            "preferred_look": session.preferred_look,
            "preferred_body": session.preferred_body,
            "value_most": session.value_most,
            "latitude": session.latitude,
            "longitude": session.longitude,
            "location_text": session.location_text,
            "location_skipped": session.location_skipped,
        }

    total = len(ranked_teachers)

    # 4. Render and display the AI preference matching summary report (single unified message)
    summary_text, summary_markup = render_inquiry_summary(session, query_info, total, current_index=0)
    if update.callback_query and update.callback_query.message:
        try:
            await update.callback_query.edit_message_text(
                text=summary_text,
                parse_mode="HTML",
                reply_markup=summary_markup,
                disable_web_page_preview=True,
            )
        except Exception:
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=summary_text,
                    parse_mode="HTML",
                    reply_markup=summary_markup,
                    disable_web_page_preview=True,
                )
            except Exception as err:
                logger.debug("Failed sending summary in _complete_inquiry: %s", err)
    elif update.effective_message:
        try:
            await update.effective_message.reply_text(
                text=summary_text,
                parse_mode="HTML",
                reply_markup=summary_markup,
                disable_web_page_preview=True,
            )
        except Exception as err:
            logger.debug("Failed sending summary in _complete_inquiry: %s", err)

    # Evict active state
    inquiry_state_manager.clear_session(user.id)
    if context and getattr(context, "user_data", None) is not None:
        context.user_data.pop("inquiry_active", None)
