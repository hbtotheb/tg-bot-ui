from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from telegram import InputMediaPhoto, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from core.rate_limiter import rate_limiter
from core.shared import db
from ui.teachers_card import (
    format_empty_card,
    format_review_detail,
    format_teacher_card,
    format_teacher_reviews,
    get_teacher_photo,
)
try:
    from extractor.photo_filter import is_valid_teacher_photo, is_blacklisted_or_group_photo
except ImportError:
    def is_valid_teacher_photo(p: object) -> bool:
        return bool(p and Path(str(p)).exists())

    def is_blacklisted_or_group_photo(p: object) -> bool:
        return False

logger = logging.getLogger(__name__)

# In-memory Telegram file_id cache to avoid re-uploading identical photos (photo_path -> file_id)
_PHOTO_FILE_ID_CACHE: dict[str, str] = {}


async def _resolve_teacher_link(teacher: dict | None) -> None:
    """Ensure teacher dictionary has teacher_account and teacher_post_link resolved from associated reviews if missing."""
    if not teacher or teacher.get("_link_resolved"):
        return
    teacher["_link_resolved"] = True
    tid = teacher.get("id")
    if tid:
        try:
            has_contact = bool(teacher.get("teacher_account") or teacher.get("booking_url"))
            has_post_link = bool(teacher.get("teacher_post_link"))
            if not has_contact or not has_post_link:
                revs = await db.get_teacher_reviews(tid, limit=5)
                for r in revs:
                    if not teacher.get("teacher_account") and r.get("teacher_account"):
                        teacher["teacher_account"] = r["teacher_account"]
                    if not teacher.get("teacher_post_link") and r.get("teacher_post_link"):
                        teacher["teacher_post_link"] = r["teacher_post_link"]
                    if not teacher.get("booking_url") and r.get("booking_url"):
                        teacher["booking_url"] = r["booking_url"]
                    if not (teacher.get("teacher_account") or teacher.get("booking_url")) or not teacher.get("teacher_post_link"):
                        if r.get("content"):
                            from extractor.post_reader import extract_teacher_meta_from_text
                            acc, plink, b_url = extract_teacher_meta_from_text(r["content"])
                            if not teacher.get("teacher_account") and acc:
                                teacher["teacher_account"] = acc
                            if not teacher.get("teacher_post_link") and plink:
                                teacher["teacher_post_link"] = plink
                            if not teacher.get("booking_url") and b_url:
                                teacher["booking_url"] = b_url
                    if (teacher.get("teacher_account") or teacher.get("booking_url")) and teacher.get("teacher_post_link"):
                        break
                if teacher.get("teacher_account") or teacher.get("teacher_post_link") or teacher.get("booking_url"):
                    try:
                        sql = "UPDATE teachers SET teacher_account = coalesce(?, teacher_account), teacher_post_link = coalesce(?, teacher_post_link), booking_url = coalesce(?, booking_url) WHERE id = ?"
                        await db.execute_write(sql, [teacher.get("teacher_account"), teacher.get("teacher_post_link"), teacher.get("booking_url"), tid])
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Failed to resolve fallback teacher_account/post_link for teacher %s: %s", tid, e)


async def _resolve_teacher_photo(teacher: dict | None) -> None:
    """Ensure teacher dictionary has photo_path resolved using strict priority:
    1. Teacher direct account's profile pic (@teacher_account) [Highest Priority]
    2. Review attached pic (genuine review photo, non-group) [2nd Priority]
    3. Teacher introduction post pic (teacher_post_link) [3rd Priority]
    4. Default placeholder image (never use group/channel avatar) [Fallback]
    """
    if not teacher or teacher.get("_photo_resolved"):
        return
    teacher["_photo_resolved"] = True
    tid = teacher.get("id")
    if not tid:
        return

    curr_photo = teacher.get("photo_path")
    # If current photo is a blacklisted group logo, purge it immediately
    if curr_photo and is_blacklisted_or_group_photo(curr_photo):
        curr_photo = None
        teacher["photo_path"] = None
        try:
            await db.execute_write("UPDATE teachers SET photo_path = NULL WHERE id = ?", [tid])
        except Exception:
            pass

    # PRIORITY 1: Teacher's direct account profile pic
    account = teacher.get("teacher_account")
    if account:
        clean_acc = account.split("/")[-1].lstrip("@").strip().lower()
        from extractor.post_reader import PHOTOS_DIR
        local_acc_path = PHOTOS_DIR / f"account_{clean_acc}.jpg"
        if local_acc_path.exists() and is_valid_teacher_photo(local_acc_path):
            teacher["photo_path"] = str(local_acc_path)
            return

        # If no photo is set, attempt to fetch direct account avatar online
        if not curr_photo:
            try:
                from extractor.post_reader import fetch_account_avatar
                avatar_path = await fetch_account_avatar(account, timeout=1.5, download_photo=True)
                if avatar_path and is_valid_teacher_photo(avatar_path):
                    teacher["photo_path"] = avatar_path
                    try:
                        await db.update_teacher_photo(tid, avatar_path)
                    except Exception:
                        pass
                    return
            except Exception as e:
                logger.debug("Failed fetching direct account avatar for %s: %s", account, e)

    # If teacher already has an existing valid (non-blacklisted) photo, keep it
    if curr_photo:
        return

    # PRIORITY 2: Reviews attached pic if any (strictly non-group)
    try:
        revs = await db.get_teacher_reviews(tid, limit=10)
        for r in revs:
            r_photo = r.get("photo_path")
            if r_photo and is_valid_teacher_photo(r_photo):
                teacher["photo_path"] = r_photo
                try:
                    await db.update_teacher_photo(tid, r_photo)
                except Exception:
                    pass
                return
    except Exception as e:
        logger.debug("Failed checking review photos for teacher %s: %s", tid, e)

    # PRIORITY 3: Teacher introduction post pic (strictly non-group)
    post_link = teacher.get("teacher_post_link")
    if post_link:
        try:
            from extractor.post_reader import fetch_teacher_post
            post_data = await fetch_teacher_post(post_link, timeout=1.5, download_photo=True)
            if post_data and post_data.get("photo_path"):
                p_photo = post_data["photo_path"]
                if is_valid_teacher_photo(p_photo):
                    teacher["photo_path"] = p_photo
                    try:
                        await db.update_teacher_photo(tid, p_photo)
                    except Exception:
                        pass
                    return
        except Exception as e:
            logger.debug("Failed fetching post photo for teacher %s: %s", tid, e)

    # PRIORITY 4: Fallback to placeholder image (handled in get_teacher_photo)


async def cmd_teachers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point command /teachers to open the Tinder-like teacher swipe card."""
    user = update.effective_user
    if user:
        await db.register_user(
            chat_id=update.effective_chat.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language=user.language_code,
        )

    total = await db.count_teachers()
    if total == 0:
        text, markup = format_empty_card()
        if update.effective_message:
            await update.effective_message.reply_text(
                text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
            )
        return

    teachers = await db.search_teachers(sort_by="rank", limit=1, offset=0)
    if not teachers:
        text, markup = format_empty_card()
        if update.effective_message:
            await update.effective_message.reply_text(
                text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
            )
        return

    teacher = teachers[0]
    await _resolve_teacher_link(teacher)
    await _resolve_teacher_photo(teacher)
    caption, markup = format_teacher_card(teacher, 0, total)
    photo_path = get_teacher_photo(teacher)

    if update.effective_message:
        try:
            cached_file_id = _PHOTO_FILE_ID_CACHE.get(photo_path)
            if cached_file_id:
                sent = await update.effective_message.reply_photo(
                    photo=cached_file_id, caption=caption, parse_mode="HTML", reply_markup=markup
                )
            else:
                with open(photo_path, "rb") as f:
                    sent = await update.effective_message.reply_photo(
                        photo=f, caption=caption, parse_mode="HTML", reply_markup=markup
                    )
                if sent and hasattr(sent, "photo") and sent.photo:
                    _PHOTO_FILE_ID_CACHE[photo_path] = sent.photo[-1].file_id

            if context and getattr(context, "user_data", None) is not None:
                context.user_data["current_card_photo"] = photo_path
        except Exception as e:
            logger.warning("Failed to reply with photo card, falling back to text: %s", e)
            await update.effective_message.reply_text(
                caption, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
            )


async def on_teacher_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback query dispatcher for teacher swipe cards (prefixed with tc:)."""
    if not update.callback_query or not update.callback_query.data:
        return

    user = update.effective_user
    if user and rate_limiter.is_callback_rate_limited(user.id, user.username):
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

    if action == "noop":
        return

    if action == "swipe":
        target_index = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        total = await db.count_teachers()
        if total == 0:
            text, markup = format_empty_card()
            msg = update.callback_query.message
            if msg and msg.photo:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                await update.callback_query.edit_message_text(
                    text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
                )
            return

        clamped_index = max(0, min(target_index, total - 1))
        teachers = await db.search_teachers(sort_by="rank", limit=1, offset=clamped_index)
        if not teachers:
            text, markup = format_empty_card()
            await update.callback_query.edit_message_text(
                text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
            )
            return

        teacher = teachers[0]
        await _resolve_teacher_link(teacher)
        await _resolve_teacher_photo(teacher)
        caption, markup = format_teacher_card(teacher, clamped_index, total)
        photo_path = get_teacher_photo(teacher)

        msg = update.callback_query.message
        current_user_photo = (
            context.user_data.get("current_card_photo")
            if (context and getattr(context, "user_data", None) is not None)
            else None
        )

        if msg and msg.photo:
            # 1. OPTIMIZATION: If the current card already displays this exact photo,
            # edit caption only without touching media (instantaneous ~30ms, zero upload/flicker)
            if current_user_photo == photo_path:
                try:
                    await update.callback_query.edit_message_caption(
                        caption=caption, parse_mode="HTML", reply_markup=markup
                    )
                    return
                except BadRequest as e:
                    if "not modified" not in str(e).lower():
                        logger.warning("Failed to edit teacher swipe caption: %s", e)
                    return
                except Exception as e:
                    logger.error("Error editing teacher card caption: %s", e)

            # 2. OPTIMIZATION: If photo changed, use cached Telegram file_id to avoid binary upload
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

                if context and getattr(context, "user_data", None) is not None:
                    context.user_data["current_card_photo"] = photo_path
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    logger.warning("Failed to edit teacher swipe media: %s", e)
            except Exception as e:
                logger.error("Error editing teacher card media: %s", e)
        else:
            # Transitioning from text menu to photo card:
            if msg:
                try:
                    await msg.delete()
                except Exception:
                    pass
            try:
                cached_file_id = _PHOTO_FILE_ID_CACHE.get(photo_path)
                if cached_file_id:
                    sent = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=cached_file_id,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=markup,
                    )
                else:
                    with open(photo_path, "rb") as f:
                        sent = await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=f,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=markup,
                        )
                    if sent and hasattr(sent, "photo") and sent.photo:
                        _PHOTO_FILE_ID_CACHE[photo_path] = sent.photo[-1].file_id

                if context and getattr(context, "user_data", None) is not None:
                    context.user_data["current_card_photo"] = photo_path
            except Exception as e:
                logger.error("Failed to send teacher photo card: %s", e)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )

    elif action == "rev":
        # Format: tc:rev:{teacher_id}:{from_index} or tc:rev:{teacher_id}:{from_index}:{page}
        try:
            teacher_id = int(parts[2])
            from_index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        except (IndexError, ValueError):
            return

        page = 0
        if len(parts) > 4 and parts[4].isdigit():
            page = int(parts[4])

        expanded_idx = -1
        if len(parts) > 5:
            try:
                expanded_idx = int(parts[5])
            except ValueError:
                expanded_idx = -1

        teacher = await db.get_teacher(teacher_id)
        if not teacher:
            total = await db.count_teachers()
            clamped_index = max(0, min(from_index, max(0, total - 1)))
            teachers = await db.search_teachers(sort_by="rank", limit=1, offset=clamped_index)
            if teachers:
                teacher = teachers[0]
            else:
                return

        await _resolve_teacher_link(teacher)
        await _resolve_teacher_photo(teacher)
        rc = teacher.get("review_count")
        limit = max(50, int(rc)) if rc is not None else 50
        reviews = await db.get_teacher_reviews(teacher_id, limit=limit)
        raw_bot_user = getattr(context.bot, "username", None)
        bot_username = raw_bot_user if isinstance(raw_bot_user, str) and raw_bot_user else None
        caption, markup = format_teacher_reviews(
            teacher, reviews, from_index, page=page, page_size=6, bot_username=bot_username
        )

        msg = update.callback_query.message
        if msg and msg.photo:
            try:
                await update.callback_query.edit_message_caption(
                    caption=caption, parse_mode="HTML", reply_markup=markup
                )
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    logger.warning("Failed to edit teacher reviews caption: %s", e)
                    if "parse entities" in str(e).lower():
                        try:
                            clean_caption = re.sub(r"<[^>]+>", "", caption)
                            await update.callback_query.edit_message_caption(
                                caption=clean_caption, reply_markup=markup
                            )
                        except Exception as fallback_err:
                            logger.error("Failed plain text fallback caption: %s", fallback_err)
            except Exception as e:
                logger.error("Error editing teacher reviews caption: %s", e)
        elif msg:
            try:
                await update.callback_query.edit_message_text(
                    text=caption, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
                )
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    logger.warning("Failed to edit teacher reviews: %s", e)
                    if "parse entities" in str(e).lower():
                        try:
                            clean_caption = re.sub(r"<[^>]+>", "", caption)
                            await update.callback_query.edit_message_text(
                                text=clean_caption, reply_markup=markup, disable_web_page_preview=True
                            )
                        except Exception as fallback_err:
                            logger.error("Failed plain text fallback text: %s", fallback_err)
            except Exception as e:
                logger.error("Error displaying teacher reviews: %s", e)

    elif action == "rdtl":
        # Format: tc:rdtl:{teacher_id}:{from_index}:{review_id}:{page}:{review_num}
        try:
            teacher_id = int(parts[2])
            from_index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            review_id = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
            page = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
            review_num = int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 1
        except (IndexError, ValueError):
            return

        await show_review_detail(
            update, context, teacher_id, review_id, from_index, page, review_num
        )

    elif action == "inq":
        # Format: tc:inq:{teacher_id}:{from_index}
        try:
            teacher_id = int(parts[2])
            from_index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        except (IndexError, ValueError):
            return

        from inquiry.handlers import start_inquiry
        await start_inquiry(update, context, teacher_id, from_index)


async def show_review_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    teacher_id: int,
    review_id: int,
    from_index: int = 0,
    page: int = 0,
    review_num: int = 1,
    back_callback: str | None = None,
    review_list_callback: str | None = None,
) -> None:
    """Display single review full detail card with link to original post."""
    teacher = await db.get_teacher(teacher_id)
    if not teacher:
        total = await db.count_teachers()
        clamped_index = max(0, min(from_index, max(0, total - 1)))
        teachers = await db.search_teachers(sort_by="rank", limit=1, offset=clamped_index)
        if teachers:
            teacher = teachers[0]
        else:
            return

    await _resolve_teacher_link(teacher)
    await _resolve_teacher_photo(teacher)

    review = await db.get_review(review_id)
    if not review:
        revs = await db.get_teacher_reviews(teacher_id, limit=50)
        review = next((r for r in revs if r.get("id") == review_id), None)
        if not review and revs:
            review = revs[0]

    if not review:
        return

    caption, markup = format_review_detail(
        teacher,
        review,
        review_num,
        from_index,
        page=page,
        back_callback=back_callback,
        review_list_callback=review_list_callback,
    )

    if update.callback_query:
        msg = update.callback_query.message
        if msg and msg.photo:
            try:
                await update.callback_query.edit_message_caption(
                    caption=caption, parse_mode="HTML", reply_markup=markup
                )
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    logger.warning("Failed to edit review detail caption: %s", e)
                    if "parse entities" in str(e).lower():
                        try:
                            clean_caption = re.sub(r"<[^>]+>", "", caption)
                            await update.callback_query.edit_message_caption(
                                caption=clean_caption, reply_markup=markup
                            )
                        except Exception as fallback_err:
                            logger.error("Failed plain text fallback review caption: %s", fallback_err)
            except Exception as e:
                logger.error("Error editing review detail caption: %s", e)
        elif msg:
            try:
                await update.callback_query.edit_message_text(
                    text=caption, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
                )
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    logger.warning("Failed to edit review detail: %s", e)
                    if "parse entities" in str(e).lower():
                        try:
                            clean_caption = re.sub(r"<[^>]+>", "", caption)
                            await update.callback_query.edit_message_text(
                                text=clean_caption, reply_markup=markup, disable_web_page_preview=True
                            )
                        except Exception as fallback_err:
                            logger.error("Failed plain text fallback review text: %s", fallback_err)
            except Exception as e:
                logger.error("Error displaying review detail: %s", e)
    else:
        # Came from command (/start rdtl_...)
        photo_path = get_teacher_photo(teacher)
        if update.effective_message:
            try:
                cached_file_id = _PHOTO_FILE_ID_CACHE.get(photo_path)
                if cached_file_id:
                    await update.effective_message.reply_photo(
                        photo=cached_file_id, caption=caption, parse_mode="HTML", reply_markup=markup
                    )
                else:
                    with open(photo_path, "rb") as f:
                        sent = await update.effective_message.reply_photo(
                            photo=f, caption=caption, parse_mode="HTML", reply_markup=markup
                        )
                    if sent and hasattr(sent, "photo") and sent.photo:
                        _PHOTO_FILE_ID_CACHE[photo_path] = sent.photo[-1].file_id
            except Exception as e:
                logger.warning("Failed to reply with photo review detail, falling back to text: %s", e)
                await update.effective_message.reply_text(
                    caption, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
                )


async def show_teachers_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    query: str | None = None,
    sort_by: str = "rank",
) -> None:
    """Render and send or edit paginated teachers list with search query support."""
    total = await db.count_teachers(query=query, status="active")
    max_pages = max(1, (total + 8 - 1) // 8)
    clamped_page = max(0, min(page, max_pages - 1))

    teachers = await db.search_teachers(
        query=query, status="active", sort_by=sort_by, limit=8, offset=clamped_page * 8
    )
    try:
        from bot.ui.teachers_list import format_teachers_list
    except ImportError:
        from ui.teachers_list import format_teachers_list

    raw_bot_user = (
        getattr(context.bot, "username", None)
        if context and getattr(context, "bot", None)
        else None
    )
    bot_username = raw_bot_user if isinstance(raw_bot_user, str) and raw_bot_user else None

    text, markup = format_teachers_list(
        teachers=teachers,
        page=clamped_page,
        total=total,
        page_size=8,
        query=query,
        sort_by=sort_by,
        bot_username=bot_username,
    )

    if update.callback_query:
        msg = update.callback_query.message
        if msg and msg.photo:
            try:
                await msg.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        else:
            try:
                await update.callback_query.edit_message_text(
                    text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
                )
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    logger.warning("Failed to edit teachers list message: %s", e)
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
        )


async def show_teacher_card_by_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    teacher_id: int,
    from_page: int = 0,
) -> None:
    """Display single teacher card triggered via in-chat deep link (/start tc_{tid}_{page})."""
    teacher = await db.get_teacher(teacher_id)
    if not teacher:
        await show_teachers_list(update, context, page=from_page)
        return

    await _resolve_teacher_link(teacher)
    await _resolve_teacher_photo(teacher)
    caption, markup = format_teacher_card(
        teacher, 0, 1, back_callback=f"tl:page:{from_page}"
    )
    photo_path = get_teacher_photo(teacher)

    if update.effective_message:
        try:
            cached_file_id = _PHOTO_FILE_ID_CACHE.get(photo_path)
            if cached_file_id:
                sent = await update.effective_message.reply_photo(
                    photo=cached_file_id, caption=caption, parse_mode="HTML", reply_markup=markup
                )
            else:
                with open(photo_path, "rb") as f:
                    sent = await update.effective_message.reply_photo(
                        photo=f, caption=caption, parse_mode="HTML", reply_markup=markup
                    )
                if sent and hasattr(sent, "photo") and sent.photo:
                    _PHOTO_FILE_ID_CACHE[photo_path] = sent.photo[-1].file_id

            if context and getattr(context, "user_data", None) is not None:
                context.user_data["current_card_photo"] = photo_path
        except Exception as e:
            logger.warning("Failed sending teacher card photo via deep link: %s", e)
            await update.effective_message.reply_text(
                caption, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True
            )


async def cmd_teachers_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command /teachers_list or /list to open teachers directory list view."""
    user = update.effective_user
    if user:
        await db.register_user(
            chat_id=update.effective_chat.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language=user.language_code,
        )
    query = (
        context.user_data.get("teacher_search_query")
        if (context and getattr(context, "user_data", None) is not None)
        else None
    )
    await show_teachers_list(update, context, page=0, query=query)


async def on_teacher_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback query dispatcher for teacher list view (prefixed with tl:)."""
    if not update.callback_query or not update.callback_query.data:
        return

    user = update.effective_user
    if user and rate_limiter.is_callback_rate_limited(user.id, user.username):
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

    if action == "noop":
        return

    if action == "page":
        target_page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        query = (
            context.user_data.get("teacher_search_query")
            if (context and getattr(context, "user_data", None) is not None)
            else None
        )
        await show_teachers_list(update, context, page=target_page, query=query)
        return

    if action == "search":
        if context and getattr(context, "user_data", None) is not None:
            context.user_data["awaiting_teacher_search"] = True
        try:
            from bot.ui.teachers_list import format_teacher_search_prompt
        except ImportError:
            from ui.teachers_list import format_teacher_search_prompt
        text, markup = format_teacher_search_prompt()
        msg = update.callback_query.message
        if msg and msg.photo:
            try:
                await msg.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        else:
            await update.callback_query.edit_message_text(
                text=text, parse_mode="HTML", reply_markup=markup
            )
        return

    if action == "clearsearch":
        if context and getattr(context, "user_data", None) is not None:
            context.user_data.pop("teacher_search_query", None)
            context.user_data.pop("awaiting_teacher_search", None)
        await show_teachers_list(update, context, page=0, query=None)
        return

    if action == "kw":
        raw = parts[2] if len(parts) > 2 else ""
        kw = ""
        if raw.startswith("b64_"):
            try:
                import base64
                b64_str = raw[4:]
                padding = "=" * (-len(b64_str) % 4)
                kw = base64.urlsafe_b64decode(b64_str + padding).decode("utf-8")
            except Exception:
                kw = ""
        else:
            kw = raw.strip()
        if kw:
            if context and getattr(context, "user_data", None) is not None:
                context.user_data["teacher_search_query"] = kw
            await show_teachers_list(update, context, page=0, query=kw)
            return

    if action == "view":
        teacher_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        from_page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

        teacher = await db.get_teacher(teacher_id)
        if not teacher:
            await show_teachers_list(update, context, page=from_page)
            return

        await _resolve_teacher_link(teacher)
        await _resolve_teacher_photo(teacher)
        caption, markup = format_teacher_card(teacher, 0, 1, back_callback=f"tl:page:{from_page}")
        photo_path = get_teacher_photo(teacher)

        msg = update.callback_query.message
        if msg and msg.photo:
            cached_file_id = _PHOTO_FILE_ID_CACHE.get(photo_path)
            try:
                if cached_file_id:
                    media = InputMediaPhoto(media=cached_file_id, caption=caption, parse_mode="HTML")
                    await update.callback_query.edit_message_media(media=media, reply_markup=markup)
                else:
                    with open(photo_path, "rb") as f:
                        media = InputMediaPhoto(media=f, caption=caption, parse_mode="HTML")
                        res = await update.callback_query.edit_message_media(media=media, reply_markup=markup)
                    if res and hasattr(res, "photo") and res.photo:
                        _PHOTO_FILE_ID_CACHE[photo_path] = res.photo[-1].file_id
            except Exception as e:
                logger.error("Error editing teacher card from list view: %s", e)
        else:
            if msg:
                try:
                    await msg.delete()
                except Exception:
                    pass
            try:
                cached_file_id = _PHOTO_FILE_ID_CACHE.get(photo_path)
                if cached_file_id:
                    sent = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=cached_file_id,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=markup,
                    )
                else:
                    with open(photo_path, "rb") as f:
                        sent = await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=f,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=markup,
                        )
                    if sent and hasattr(sent, "photo") and sent.photo:
                        _PHOTO_FILE_ID_CACHE[photo_path] = sent.photo[-1].file_id

                if context and getattr(context, "user_data", None) is not None:
                    context.user_data["current_card_photo"] = photo_path
            except Exception as e:
                logger.warning("Failed sending photo card from list view, falling back to text: %s", e)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
        return


