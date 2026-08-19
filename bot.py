# -*- coding: utf-8 -*-
"""
bot.py
------
ربات تلگرامی فیلم/سریال «SilentMovie».

امکانات کاربر:
  • جستجوی فیلم با نوشتن نام آن (یا از طریق دکمه‌ی «🔍 جستجوی فیلم»)
  • نمایش کارت فیلم با پوستر و اطلاعات کامل
  • دکمه‌های شیشه‌ای برای هر قسمت → ساخت لینک تازه‌ی VLC
  • علاقه‌مندی‌ها (Favorites)
  • عضویت اجباری در کانال‌ها

پنل مدیریت (دکمه‌ی «🛠 پنل مدیریت» یا /admin):
  • آمار، مدیریت کانال‌های عضویت اجباری، پیام همگانی، مدیریت ادمین‌ها، لاگ خطا
  • ارسال دستی فایل دیتابیس و بازیابی آن از فایل آپلودی

زمان‌بندی:
  • هر N ساعت (پیش‌فرض ۲) فایل دیتابیس برای همه‌ی ادمین‌ها ارسال می‌شود
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
from dataclasses import asdict
from datetime import time as dt_time
from typing import Dict, List, Optional

import requests
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InputFile,
                      Update, InlineQueryResultArticle, InlineQueryResultPhoto,
                      InputTextMessageContent)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, InlineQueryHandler, MessageHandler,
                          filters)

import config
import keyboards as kb
from database import Database
from formatting import esc, movie_caption, play_message, webapp_play_message
from site_client import BASE, Episode, Movie, SearchResult, SiteClient, LoginError
from webapp import start_player_server
from categorize import (categorize_with_indices, get_available_types,
                      QUALITY_LABELS, TYPE_LABELS)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# ---------------- وضعیت سراسری ----------------
db: Database = None            # مقداردهی در main
site: SiteClient = None        # مقداردهی در main
# حالت گفتگوی ادمین (منتظر ورودی): user_id -> action
pending_admin: Dict[int, str] = {}


# ---------------- کمک‌کننده‌ها ----------------
def super_admin() -> Optional[int]:
    admins = db.list_admins()
    return admins[0] if admins else (config.ADMIN_IDS[0] if config.ADMIN_IDS else None)


async def is_member_all_channels(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> List[dict]:
    """کانال‌هایی که کاربر عضو آن‌ها نیست را برمی‌گرداند (لیست خالی = عضو همه)."""
    not_joined = []
    for ch in db.list_channels():
        chat_id = ch["chat_id"]
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in ("left", "kicked"):
                not_joined.append(dict(ch))
        except TelegramError as e:
            # اگر ربات ادمین کانال نباشد یا خطا بدهد، آن کانال را نادیده می‌گیریم
            log.warning("بررسی عضویت کانال %s ناموفق: %s", chat_id, e)
            db.log_error("membership_check", f"{chat_id}: {e}")
    return not_joined


async def require_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """اگر عضو نیست، پیام عضویت اجباری می‌فرستد و False برمی‌گرداند."""
    user_id = update.effective_user.id
    if db.is_admin(user_id):
        return True
    missing = await is_member_all_channels(user_id, context)
    if not missing:
        return True
    text = ("🔒 برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید، "
            "سپس روی «✅ عضو شدم» بزنید:")
    markup = kb.join_kb(missing)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    else:
        await update.effective_message.reply_text(text, reply_markup=markup)
    return False


def cache_movie(movie: Movie) -> None:
    try:
        payload = json.dumps(_movie_to_dict(movie), ensure_ascii=False)
        db.cache_put(movie.movie_id, payload)
    except Exception as e:
        log.warning("cache_put failed: %s", e)


def _movie_to_dict(movie: Movie) -> dict:
    d = asdict(movie)
    return d


def _movie_from_dict(d: dict) -> Movie:
    eps = [Episode(**e) for e in d.get("episodes", [])]
    d = dict(d)
    d["episodes"] = eps
    return Movie(**d)


def get_movie_cached(movie_id: str) -> Movie:
    """اول از کش، بعد از سایت."""
    payload = db.cache_get(movie_id, config.MOVIE_CACHE_TTL)
    if payload:
        try:
            return _movie_from_dict(json.loads(payload))
        except Exception:
            pass
    movie = site.movie(movie_id)
    cache_movie(movie)
    return movie


async def download_bytes(url: str) -> Optional[bytes]:
    """دانلود پوستر در ترد جداگانه — با سشن سایت و پشتیبانی از فرمت‌های مختلف."""
    def _dl():
        try:
            # اول سشن سایت را امتحان کن (عکس ممکنه پشت لاگین باشه)
            if site and site.s.cookies:
                r = site.s.get(url, headers={"User-Agent": UA, "Referer": BASE},
                               timeout=25, verify=False)
                if r.status_code == 200 and len(r.content) > 2000:
                    return r.content
            # بعد بدون سشن (CDN عمومی)
            r = requests.get(url, headers={"User-Agent": UA, "Referer": BASE},
                             timeout=25, verify=False)
            if r.status_code == 200 and len(r.content) > 2000:
                return r.content
        except Exception:
            pass
        return None
    return await asyncio.to_thread(_dl)


# ---------------- دستورات کاربر ----------------
WELCOME = (
    "🎬 <b>به ربات SilentMovie خوش آمدید!</b>\n\n"
    
    "🍿 نام فیلم یا سریال موردنظرتان را ارسال کنید "
    "تا در سریع‌ترین زمان برایتان جستجو کنیم.\n\n"
    
    "🔎 <b>مثال:</b> <code>The Lord of the Rings</code>\n\n"
    
    "<blockquote>"
    "🎥 <b>فیلم موردنظرتان را انتخاب کنید، کیفیت و قسمت را مشخص کنید "
    "و مستقیماً داخل پلیر تماشا کنید.</b>"
    "</blockquote>\n\n"
    
    "⚡ سریع، ساده و بدون نیاز به برنامه‌های اضافی"
)

SEARCH_PROMPT = "🔍 نام فیلم یا سریالی که می‌خواهید را بنویسید:"

# مسیر عکس خوش‌آمد؛ اگر این فایل موجود باشد همراه پیام استارت نمایش داده می‌شود.
WELCOME_IMAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "welcome.jpg")


def user_menu(uid: int):
    """منوی دکمه‌ای مناسب کاربر (اگر ادمین باشد دکمه‌ی پنل هم اضافه می‌شود)."""
    return kb.main_menu_kb(is_admin=db.is_admin(uid))


async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیام خوش‌آمد را با عکس (در صورت وجود) و دکمه‌های شیشه‌ای می‌فرستد."""
    uid = update.effective_user.id
    menu = user_menu(uid)
    inline_menu = kb.start_inline_kb(is_admin=db.is_admin(uid))
    if os.path.exists(WELCOME_IMAGE):
        try:
            with open(WELCOME_IMAGE, "rb") as f:
                await update.effective_message.reply_photo(
                    photo=InputFile(f, filename="welcome.jpg"),
                    caption=WELCOME, parse_mode=ParseMode.HTML,
                    reply_markup=inline_menu)
            return
        except Exception as e:
            log.warning("ارسال عکس خوش‌آمد ناموفق بود: %s", e)
    await update.effective_message.reply_html(WELCOME, reply_markup=inline_menu)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    db.upsert_user(u.id, u.username or "", u.first_name or "")
    # اگر ادمین اولیه هنوز ثبت نشده، ثبتش کن
    for aid in config.ADMIN_IDS:
        if not db.is_admin(aid):
            db.add_admin(aid)
    if not await require_membership(update, context):
        return
    await send_welcome(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_html(
        "📖 <b>راهنما</b>\n\n"
        "• دکمه‌ی «🔍 جستجوی فیلم» را بزنید یا مستقیم نام فیلم را بنویسید.\n"
        "• روی نتیجه بزنید تا کارت فیلم باز شود.\n"
        "• روی هر قسمت بزنید تا لینک VLC ساخته شود.\n"
        "• «❤️ علاقه‌مندی‌ها» فیلم‌هایی که ثبت کرده‌اید را نشان می‌دهد.\n"
        "• «🕒 تماشا شده‌ها» فیلم‌هایی که لینک پخش گرفته‌اید را نشان می‌دهد.\n"
        "• «📜 جستجوهای اخیر» جستجوهای قبلی شما را با یک کلیک تکرار می‌کند.",
        reply_markup=user_menu(update.effective_user.id))


async def cmd_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    db.upsert_user(u.id, u.username or "", u.first_name or "")
    if not await require_membership(update, context):
        return
    favs = db.list_favorites(u.id)
    if not favs:
        await update.effective_message.reply_text(
            "لیست علاقه‌مندی‌های شما خالی است. ❤️\n"
            "با زدن «❤️ افزودن به علاقه‌مندی‌ها» روی هر فیلم، آن را اینجا ذخیره کنید.",
            reply_markup=user_menu(u.id))
        return
    await update.effective_message.reply_text(
        f"❤️ علاقه‌مندی‌های شما ({len(favs)} مورد):",
        reply_markup=kb.favorites_kb(favs))


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """فیلم‌هایی که کاربر تماشا کرده (لینک پخش گرفته)."""
    u = update.effective_user
    db.upsert_user(u.id, u.username or "", u.first_name or "")
    if not await require_membership(update, context):
        return
    items = db.list_watch(u.id, 15)
    if not items:
        await update.effective_message.reply_text(
            "🕒 هنوز فیلمی تماشا نکرده‌اید.\n"
            "وقتی روی یک قسمت بزنید و لینک پخش بگیرید، اینجا ثبت می‌شود.",
            reply_markup=user_menu(u.id))
        return
    await update.effective_message.reply_text(
        f"🕒 فیلم‌هایی که تماشا کرده‌اید ({len(items)} مورد):",
        reply_markup=kb.history_kb(items))


async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """جستجوهای اخیر کاربر — با یک کلیک دوباره جستجو می‌شوند."""
    u = update.effective_user
    db.upsert_user(u.id, u.username or "", u.first_name or "")
    if not await require_membership(update, context):
        return
    queries = db.recent_searches(u.id, 10)
    if not queries:
        await update.effective_message.reply_text(
            "📜 هنوز جستجویی انجام نداده‌اید.",
            reply_markup=user_menu(u.id))
        return
    # لیست را برای نگاشت ایندکس در callback نگه می‌داریم
    context.user_data["recent"] = queries
    await update.effective_message.reply_text(
        "📜 جستجوهای اخیر شما — روی هرکدام بزنید تا دوباره جستجو شود:",
        reply_markup=kb.recent_searches_kb(queries))


async def on_text_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیام متنی: دکمه‌های منو، ورودی پنل ادمین، یا جستجو."""
    u = update.effective_user
    text = (update.effective_message.text or "").strip()

    # اگر ادمین در حال وارد کردن چیزی است (اولویت با پنل)
    if u.id in pending_admin:
        await handle_admin_input(update, context, text)
        return

    db.upsert_user(u.id, u.username or "", u.first_name or "")

    # دکمه‌های منوی اصلی
    if text == kb.BTN_ADMIN:
        await cmd_admin(update, context)
        return
    if text == kb.BTN_HELP:
        await cmd_help(update, context)
        return
    if text == kb.BTN_FAVORITES:
        await cmd_favorites(update, context)
        return
    if text == kb.BTN_HISTORY:
        await cmd_history(update, context)
        return
    if text == kb.BTN_RECENT:
        await cmd_recent(update, context)
        return
    if text == kb.BTN_SEARCH:
        if not await require_membership(update, context):
            return
        await update.effective_message.reply_text(
            SEARCH_PROMPT, reply_markup=user_menu(u.id))
        return

    # در غیر این صورت: جستجو
    if not await require_membership(update, context):
        return
    if not text or text.startswith("/"):
        return
    await do_search(update, context, text)


async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    msg = update.effective_message
    await context.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
    db.log_search(update.effective_user.id, query)
    try:
        results = await asyncio.to_thread(site.search, query, 1)
    except LoginError as e:
        db.log_error("search_login", str(e))
        await msg.reply_text("⚠️ ورود به سایت ممکن نشد. کمی بعد دوباره تلاش کنید.")
        return
    except Exception as e:
        log.exception("search error")
        db.log_error("search", f"{query}: {e}")
        await msg.reply_text("⚠️ خطا در جستجو. لطفاً دوباره تلاش کنید.")
        return

    if not results:
        await msg.reply_text(f"نتیجه‌ای برای «{query}» پیدا نشد. 🔍")
        return

    results = results[:config.SEARCH_PAGE_SIZE]
    await msg.reply_text(
        f"🔍 نتایج جستجو برای «<b>{esc(query)}</b>»:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.search_results_kb(results))


# ---------------- نمایش کارت فیلم ----------------
async def show_movie_card(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          movie_id: str, page: int = 0) -> None:
    q = update.callback_query
    await context.bot.send_chat_action(q.message.chat_id, ChatAction.UPLOAD_PHOTO)
    try:
        movie = await asyncio.to_thread(get_movie_cached, movie_id)
    except LoginError:
        await q.message.reply_text("⚠️ ورود به سایت ممکن نشد. بعداً تلاش کنید.")
        return
    except Exception as e:
        log.exception("movie load error")
        db.log_error("movie", f"{movie_id}: {e}")
        await q.message.reply_text("⚠️ خطا در دریافت اطلاعات فیلم.")
        return

    is_fav = db.is_favorite(update.effective_user.id, movie_id)
    caption = movie_caption(movie)
    markup = kb.movie_card_kb(movie, is_fav)

    sent = False
    # روش ۱: ارسال URL مستقیم به تلگرام (سرورهای تلگرام دانلود می‌کنند)
    if movie.poster:
        try:
            await q.message.reply_photo(
                photo=movie.poster,
                caption=caption[:1024], parse_mode=ParseMode.HTML,
                reply_markup=markup)
            sent = True
            log.info("پوستر با URL مستقیم ارسال شد: %s", movie.poster[:80])
        except (BadRequest, TelegramError) as e:
            log.warning("ارسال پوستر با URL ناموفق (%s)، تلاش با دانلود دستی: %s", e, movie.poster[:80])

    # روش ۲: دانلود دستی با سشن سایت و ارسال bytes
    if not sent and movie.poster:
        poster_bytes = await download_bytes(movie.poster)
        if poster_bytes:
            try:
                ext = ".jpg"
                if poster_bytes[:4] == b"RIFF":
                    ext = ".webp"
                elif poster_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                    ext = ".png"
                await q.message.reply_photo(
                    photo=InputFile(io.BytesIO(poster_bytes), filename=f"{movie_id}{ext}"),
                    caption=caption[:1024], parse_mode=ParseMode.HTML, reply_markup=markup)
                sent = True
                log.info("پوستر با bytes ارسال شد (%d bytes)", len(poster_bytes))
            except (BadRequest, TelegramError) as e:
                log.warning("ارسال پوستر با bytes هم ناموفق: %s", e)

    # روش ۳: بدون عکس (فقط متن)
    if not sent:
        log.warning("پوستر ارسال نشد برای فیلم %s — poster='%s'", movie_id, (movie.poster or "")[:100])
        await q.message.reply_html(caption[:4096], reply_markup=markup)


# مرحله 2
async def select_quality(update, context, movie_id, quality):
    q = update.callback_query
    await q.answer()
    try:
        movie = await asyncio.to_thread(get_movie_cached, movie_id)
    except Exception:
        await q.answer("Error", show_alert=True)
        return
    cats = categorize_with_indices(movie.episodes)
    groups = cats.get(quality, {})
    is_fav = db.is_favorite(update.effective_user.id, movie_id)
    types = get_available_types(groups)
    if len(types) <= 1:
        ep_type = types[0] if types else "original"
        await show_episode_list(update, context, movie_id, quality, ep_type)
    else:
        markup = kb.type_select_kb(movie_id, quality, groups, is_fav)
        try:
            await q.edit_message_reply_markup(reply_markup=markup)
        except BadRequest:
            pass


# مرحله 3
async def show_episode_list(update, context, movie_id, quality, ep_type, page=0):
    q = update.callback_query
    await q.answer()
    try:
        movie = await asyncio.to_thread(get_movie_cached, movie_id)
    except Exception:
        await q.answer("Error", show_alert=True)
        return
    cats = categorize_with_indices(movie.episodes)
    groups = cats.get(quality, {})
    indexed_eps = groups.get(ep_type, [])
    is_fav = db.is_favorite(update.effective_user.id, movie_id)
    markup = kb.episode_list_kb(movie_id, quality, ep_type,
                                  indexed_eps, page, config.SEARCH_PAGE_SIZE, is_fav)
    try:
        await q.edit_message_reply_markup(reply_markup=markup)
    except BadRequest:
        pass


async def back_to_quality(update, context, movie_id):
    q = update.callback_query
    await q.answer()
    try:
        movie = await asyncio.to_thread(get_movie_cached, movie_id)
    except Exception:
        await q.answer("Error", show_alert=True)
        return
    is_fav = db.is_favorite(update.effective_user.id, movie_id)
    markup = kb.movie_card_kb(movie, is_fav)
    try:
        await q.edit_message_reply_markup(reply_markup=markup)
    except BadRequest:
        pass


async def back_to_type(update, context, movie_id, quality):
    q = update.callback_query
    await q.answer()
    try:
        movie = await asyncio.to_thread(get_movie_cached, movie_id)
    except Exception:
        await q.answer("Error", show_alert=True)
        return
    cats = categorize_with_indices(movie.episodes)
    groups = cats.get(quality, {})
    is_fav = db.is_favorite(update.effective_user.id, movie_id)
    types = get_available_types(groups)
    if len(types) <= 1:
        await back_to_quality(update, context, movie_id)
    else:
        markup = kb.type_select_kb(movie_id, quality, groups, is_fav)
        try:
            await q.edit_message_reply_markup(reply_markup=markup)
        except BadRequest:
            pass


# پخش (WebApp یا لینک VLC) ----------------
async def play_episode(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       movie_id: str, ep_index: int) -> None:
    q = update.callback_query
    await q.answer("در حال ساخت لینک پخش…")
    await context.bot.send_chat_action(q.message.chat_id, ChatAction.TYPING)
    try:
        movie = await asyncio.to_thread(get_movie_cached, movie_id)
        if ep_index < 0 or ep_index >= len(movie.episodes):
            await q.message.reply_text("قسمت نامعتبر است.")
            return
        ep = movie.episodes[ep_index]
        vlc_link = await asyncio.to_thread(site.resolve_play, ep.play_url, movie_id)
    except LoginError:
        await q.message.reply_text("⚠️ ورود به سایت ممکن نشد. بعداً تلاش کنید.")
        return
    except Exception as e:
        log.exception("play error")
        db.log_error("play", f"{movie_id}/{ep_index}: {e}")
        await q.message.reply_text("⚠️ خطا در ساخت لینک پخش.")
        return

    if not vlc_link:
        await q.message.reply_text("⚠️ لینک پخش در دسترس نیست. دوباره تلاش کنید.")
        return

    http_link = SiteClient.vlc_to_http(vlc_link)
    # ثبت در تاریخچه‌ی تماشا
    try:
        db.add_watch(update.effective_user.id, movie_id, movie.title, ep.label)
    except Exception:
        pass

    # دکمه‌ی تماشا — لینک HTTP مستقیم (بدون نمایش لینک در چت)
    await q.message.reply_html(
        webapp_play_message(movie, ep),
        reply_markup=kb.play_kb(http_link),
        disable_web_page_preview=True)


# ---------------- علاقه‌مندی ----------------
async def toggle_fav(update: Update, context: ContextTypes.DEFAULT_TYPE,
                     movie_id: str, add: bool) -> None:
    q = update.callback_query
    uid = update.effective_user.id
    if add:
        try:
            movie = await asyncio.to_thread(get_movie_cached, movie_id)
            title = movie.title
        except Exception:
            title = movie_id
        db.add_favorite(uid, movie_id, title)
        await q.answer("به علاقه‌مندی‌ها اضافه شد ❤️")
    else:
        db.remove_favorite(uid, movie_id)
        await q.answer("از علاقه‌مندی‌ها حذف شد 💔")
    # به‌روزرسانی کیبورد
    try:
        movie = await asyncio.to_thread(get_movie_cached, movie_id)
        # صفحه‌ی فعلی را نمی‌دانیم؛ صفحه ۰
        markup = kb.movie_card_kb(movie, db.is_favorite(uid, movie_id))
        await q.edit_message_reply_markup(reply_markup=markup)
    except BadRequest:
        pass


# ---------------- روتر Callback ----------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data or ""
    u = update.effective_user
    db.upsert_user(u.id, u.username or "", u.first_name or "")

    if data == "noop":
        await q.answer()
        return

    # دکمه‌های شیشه‌ای منوی استارت
    if data == "menu:search":
        await q.answer()
        await q.message.reply_text(SEARCH_PROMPT, reply_markup=user_menu(u.id))
        return
    if data == "menu:fav":
        await q.answer()
        await cmd_favorites(update, context)
        return
    if data == "menu:hist":
        await q.answer()
        await cmd_history(update, context)
        return
    if data == "menu:recent":
        await q.answer()
        await cmd_recent(update, context)
        return
    if data == "menu:help":
        await q.answer()
        await cmd_help(update, context)
        return
    if data == "menu:admin":
        await q.answer()
        await cmd_admin(update, context)
        return

    if data == "checkjoin":
        missing = await is_member_all_channels(u.id, context)
        if missing:
            await q.answer("هنوز عضو همه‌ی کانال‌ها نیستید.", show_alert=True)
        else:
            await q.answer("عضویت تأیید شد ✅")
            try:
                await q.message.delete()
            except BadRequest:
                pass
            if os.path.exists(WELCOME_IMAGE):
                try:
                    with open(WELCOME_IMAGE, "rb") as f:
                        await context.bot.send_photo(
                            q.message.chat_id, photo=InputFile(f, filename="welcome.jpg"),
                            caption=WELCOME, parse_mode=ParseMode.HTML,
                            reply_markup=user_menu(u.id))
                    return
                except Exception:
                    pass
            await context.bot.send_message(
                q.message.chat_id, WELCOME, parse_mode=ParseMode.HTML,
                reply_markup=user_menu(u.id))
        return

    # دستورات ادمین
    if data.startswith("adm:"):
        await on_admin_callback(update, context, data[4:])
        return

    # دستورات نیازمند عضویت
    if not db.is_admin(u.id):
        missing = await is_member_all_channels(u.id, context)
        if missing:
            await q.answer("ابتدا در کانال‌ها عضو شوید.", show_alert=True)
            await q.message.reply_text("🔒 عضویت اجباری:", reply_markup=kb.join_kb(missing))
            return

    if data.startswith("mv:"):
        await show_movie_card(update, context, data[3:], 0)
        await q.answer()
    elif data.startswith("ep:"):
        _, mid, idx = data.split(":")
        await play_episode(update, context, mid, int(idx))
    elif data.startswith("q:"):
        parts = data.split(":")
        await select_quality(update, context, parts[1], parts[2])
    elif data.startswith("qt:"):
        parts = data.split(":")
        await show_episode_list(update, context, parts[1], parts[2], parts[3])
    elif data.startswith("epl:"):
        parts = data.split(":")
        await show_episode_list(update, context, parts[1], parts[2], parts[3], int(parts[4]))
    elif data.startswith("bq:"):
        await back_to_quality(update, context, data[3:])
    elif data.startswith("bqt:"):
        parts = data.split(":")
        await back_to_type(update, context, parts[1], parts[2])
    elif data.startswith("fav:"):
        await toggle_fav(update, context, data[4:], add=True)
    elif data.startswith("unfav:"):
        await toggle_fav(update, context, data[6:], add=False)
    elif data.startswith("rs:"):
        # جستجوی مجدد از تاریخچه
        idx = int(data[3:])
        queries = context.user_data.get("recent") or db.recent_searches(u.id, 10)
        if 0 <= idx < len(queries):
            await q.answer()
            await do_search(update, context, queries[idx])
        else:
            await q.answer("این مورد دیگر موجود نیست.", show_alert=True)
    elif data == "clearwatch":
        db.clear_watch(u.id)
        await q.answer("تاریخچه پاک شد")
        try:
            await q.edit_message_text("🕒 تاریخچه‌ی تماشای شما پاک شد.")
        except BadRequest:
            pass
    elif data == "clearsearch":
        db.clear_searches(u.id)
        context.user_data.pop("recent", None)
        await q.answer("تاریخچه‌ی جستجو پاک شد")
        try:
            await q.edit_message_text("📜 تاریخچه‌ی جستجوی شما پاک شد.")
        except BadRequest:
            pass
    else:
        await q.answer()


# ---------------- جستجوی درون‌خطی (inline) ----------------
async def on_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = (update.inline_query.query or "").strip()
    if len(query) < 2:
        await update.inline_query.answer([], cache_time=5)
        return
    try:
        results = await asyncio.to_thread(site.search, query, 1)
    except Exception as e:
        db.log_error("inline_search", f"{query}: {e}")
        await update.inline_query.answer([], cache_time=5)
        return

    items = []
    for r in results[:20]:
        year = f" ({r.year})" if r.year else ""
        imdb = f" ⭐{r.imdb}" if r.imdb else ""
        title_text = f"{r.title}{year}{imdb}"

        if r.poster:
            # نمایش پوستر در نتایج inline
            items.append(InlineQueryResultPhoto(
                id=r.movie_id,
                photo_url=r.poster,
                thumbnail_url=r.poster,
                title=title_text,
                description="برای دیدن اطلاعات و لینک پخش بزنید",
                caption=f"🎬 <b>{esc(r.title)}</b>{year}{imdb}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎬 مشاهده قسمت‌ها و اطلاعات",
                                          callback_data=f"mv:{r.movie_id}")
                ]]),
            ))
        else:
            # بدون پوستر — فقط متن
            items.append(InlineQueryResultArticle(
                id=r.movie_id,
                title=title_text,
                description="برای دیدن اطلاعات و لینک پخش بزنید",
                input_message_content=InputTextMessageContent(
                    message_text=f"/movie_{r.movie_id}"),
            ))
    await update.inline_query.answer(items, cache_time=10)


async def cmd_movie_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیام /movie_<id> که از نتیجه‌ی inline می‌آید."""
    text = (update.effective_message.text or "").strip()
    if not text.startswith("/movie_"):
        return
    movie_id = text[len("/movie_"):].strip()
    if not movie_id.isdigit():
        return
    u = update.effective_user
    db.upsert_user(u.id, u.username or "", u.first_name or "")
    if not await require_membership(update, context):
        return
    try:
        movie = await asyncio.to_thread(get_movie_cached, movie_id)
    except Exception as e:
        db.log_error("deeplink", f"{movie_id}: {e}")
        await update.effective_message.reply_text("⚠️ خطا در دریافت فیلم.")
        return
    is_fav = db.is_favorite(u.id, movie_id)
    caption = movie_caption(movie)
    markup = kb.movie_card_kb(movie, is_fav)

    sent = False
    if movie.poster:
        try:
            await update.effective_message.reply_photo(
                photo=movie.poster,
                caption=caption[:1024], parse_mode=ParseMode.HTML, reply_markup=markup)
            sent = True
        except (BadRequest, TelegramError):
            pass
    if not sent and movie.poster:
        poster_bytes = await download_bytes(movie.poster)
        if poster_bytes:
            try:
                ext = ".jpg"
                if poster_bytes[:4] == b"RIFF":
                    ext = ".webp"
                elif poster_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                    ext = ".png"
                await update.effective_message.reply_photo(
                    photo=InputFile(io.BytesIO(poster_bytes), filename=f"{movie_id}{ext}"),
                    caption=caption[:1024], parse_mode=ParseMode.HTML, reply_markup=markup)
                sent = True
            except (BadRequest, TelegramError):
                pass
    if not sent:
        await update.effective_message.reply_html(caption[:4096], reply_markup=markup)


# ================= پنل مدیریت =================
# (در ماژول admin_panel.py پیاده‌سازی و اینجا وارد می‌شود)
from admin_panel import (cmd_admin, on_admin_callback, handle_admin_input,
                         handle_admin_document, job_send_db_backup)


# ---------------- خطاها ----------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Exception:", exc_info=context.error)
    try:
        db.log_error("handler", repr(context.error))
    except Exception:
        pass


# ---------------- راه‌اندازی ----------------
def build_application() -> Application:
    global db, site
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    db = Database(config.DB_PATH)
    for aid in config.ADMIN_IDS:
        db.add_admin(aid)
    site = SiteClient(config.SITE_MOBILE, config.SITE_PASSWORD, config.SESSION_PATH)

    # وابستگی‌ها را به admin_panel تزریق می‌کنیم
    import admin_panel
    admin_panel.init(db, site, pending_admin)

    builder = Application.builder().token(config.BOT_TOKEN)
    # پروکسی اختیاری (برای اجرا روی سیستمی که تلگرام مسدود است).
    # روی VPS خارج از ایران این خالی است و نادیده گرفته می‌شود.
    if config.TELEGRAM_PROXY:
        builder = builder.proxy(config.TELEGRAM_PROXY).get_updates_proxy(config.TELEGRAM_PROXY)
        log.info("استفاده از پروکسی برای تلگرام: %s", config.TELEGRAM_PROXY)
    app = builder.build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("favorites", cmd_favorites))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(MessageHandler(filters.Regex(r"^/movie_\d+"), cmd_movie_deeplink))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(InlineQueryHandler(on_inline))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_admin_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_search))
    app.add_error_handler(on_error)

    # زمان‌بندی بکاپ دیتابیس
    interval = max(0.1, config.BACKUP_INTERVAL_HOURS) * 3600
    app.job_queue.run_repeating(job_send_db_backup, interval=interval,
                                first=interval, name="db_backup")
    log.info("بکاپ دیتابیس هر %.1f ساعت ارسال می‌شود", config.BACKUP_INTERVAL_HOURS)
    return app


def _start_player_server(port: int) -> None:
    """Flask سرور پلیر WebApp — index.html را سرو می‌کند."""
    start_player_server()


def main() -> None:
    if config.token_is_placeholder():
        raise SystemExit("❌ BOT_TOKEN تنظیم نشده است. فایل .env را ویرایش کنید.")
    # لاگین اولیه به سایت (اختیاری ولی مفید)
    app = build_application()
    try:
        ok = site.ensure_login()
        log.info("وضعیت لاگین اولیه به سایت: %s", "موفق" if ok else "ناموفق")
    except Exception as e:
        log.warning("لاگین اولیه ناموفق: %s", e)

    # وب‌سرور پلیر ترد جداگانه (برای Render)
    port = int(os.environ.get("PORT", "10000"))
    import threading
    t = threading.Thread(target=_start_player_server, args=(port,), daemon=True)
    t.start()

    log.info("🤖 ربات در حال اجراست…")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
