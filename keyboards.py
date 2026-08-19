# -*- coding: utf-8 -*-
"""
keyboards.py
------------
سازنده‌ی کیبوردهای شیشه‌ای (inline) ربات.
"""
from __future__ import annotations

import math
from typing import List

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup,
                      KeyboardButton, ReplyKeyboardMarkup, WebAppInfo)

from site_client import Movie, SearchResult
from categorize import (categorize_episodes, categorize_with_indices, QUALITY_ORDER,
                      QUALITY_LABELS, TYPE_LABELS, get_available_qualities,
                      get_available_types, count_quality, count_type)


# ---------------- منوی اصلی (دکمه‌های دائمی پایین صفحه) ----------------
BTN_SEARCH = "🔍 جستجوی فیلم"
BTN_FAVORITES = "❤️ علاقه‌مندی‌ها"
BTN_HISTORY = "🕒 تماشا شده‌ها"
BTN_RECENT = "📜 جستجوهای اخیر"
BTN_HELP = "📖 راهنما"
BTN_ADMIN = "🛠 پنل مدیریت"


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_SEARCH)],
        [KeyboardButton(BTN_HISTORY), KeyboardButton(BTN_FAVORITES)],
        [KeyboardButton(BTN_RECENT), KeyboardButton(BTN_HELP)],
    ]
    if is_admin:
        rows.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True,
                               input_field_placeholder="نام فیلم را بنویسید…")


def start_inline_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    """دکمه‌های شیشه‌ای برای پیام استارت/خوش‌آمد."""
    rows = [
        [InlineKeyboardButton("🔍 جستجوی فیلم", callback_data="menu:search")],
        [InlineKeyboardButton("❤️ علاقه‌مندی‌ها", callback_data="menu:fav"),
         InlineKeyboardButton("🕒 تماشا شده‌ها", callback_data="menu:hist")],
        [InlineKeyboardButton("📜 جستجوهای اخیر", callback_data="menu:recent"),
         InlineKeyboardButton("📖 راهنما", callback_data="menu:help")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("🛠 پنل مدیریت", callback_data="menu:admin")])
    return InlineKeyboardMarkup(rows)


def search_results_kb(results: List[SearchResult]) -> InlineKeyboardMarkup:
    """لیست نتایج جستجو در چت خصوصی — هر فیلم یک دکمه."""
    rows = []
    for r in results:
        year = f" ({r.year})" if r.year else ""
        imdb = f" ⭐{r.imdb}" if r.imdb else ""
        rows.append([InlineKeyboardButton(f"🎬 {r.title}{year}{imdb}",
                                          callback_data=f"mv:{r.movie_id}")])
    return InlineKeyboardMarkup(rows)


def movie_card_kb(movie: Movie, is_fav: bool) -> InlineKeyboardMarkup:
    """کیبورد مرحله‌ی ۱: انتخاب کیفیت."""
    rows: List[List[InlineKeyboardButton]] = []
    cats = categorize_episodes(movie.episodes)
    quals = get_available_qualities(cats)

    if not quals and "other" not in cats:
        rows.append([InlineKeyboardButton("\u26a0\ufe0f \u0644\u06cc\u0646\u06a9\u06cc \u0645\u0648\u062c\u0648\u062f \u0646\u06cc\u0633\u062a", callback_data="noop")])
    else:
        for q in quals:
            cnt = count_quality(cats, q)
            label = QUALITY_LABELS.get(q, q)
            rows.append([InlineKeyboardButton(
                f"\U0001f4cf {label} ({cnt} \u0644\u06cc\u0646\u06a9)",
                callback_data=f"q:{movie.movie_id}:{q}")])
        if "other" in cats:
            cnt = count_quality(cats, "other")
            rows.append([InlineKeyboardButton(
                f"\U0001f4cf \u0633\u0627\u06cc\u0631 ({cnt} \u0644\u06cc\u0646\u06a9)",
                callback_data=f"q:{movie.movie_id}:other")])

    if is_fav:
        rows.append([InlineKeyboardButton("💔 \u062d\u0630\u0641 \u0627\u0632 \u0639\u0644\u0627\u0642\u0647\u200c\u0645\u0646\u062f\u06cc\u200c\u0647\u0627",
                                          callback_data=f"unfav:{movie.movie_id}")])
    else:
        rows.append([InlineKeyboardButton("❤️ \u0627\u0641\u0632\u0648\u062f\u0646 \u0628\u0647 \u0639\u0644\u0627\u0642\u0647\u200c\u0645\u0646\u062f\u06cc\u200c\u0647\u0627",
                                          callback_data=f"fav:{movie.movie_id}")])

    return InlineKeyboardMarkup(rows)


def type_select_kb(movie_id: str, quality: str, groups: dict,
                    is_fav: bool) -> InlineKeyboardMarkup:
    """کیبورد مرحله‌ی ۲: انتخاب نوع (دوبله/زیرنویس)."""
    rows = []
    for t_key, t_label in TYPE_LABELS:
        cnt = count_type(groups, t_key)
        if cnt:
            rows.append([InlineKeyboardButton(
                f"{t_label} ({cnt} \u0644\u06cc\u0646\u06a9)",
                callback_data=f"qt:{movie_id}:{quality}:{t_key}")])

    if not rows:
        rows.append([InlineKeyboardButton("\u26a0\ufe0f \u0644\u06cc\u0646\u06a9\u06cc \u06cc\u0627\u0641\u062a \u0646\u0634\u062f", callback_data="noop")])

    rows.append([InlineKeyboardButton("\u2b05\ufe0f \u0628\u0627\u0632\u06af\u0634\u062a", callback_data=f"bq:{movie_id}")])

    if is_fav:
        rows.append([InlineKeyboardButton("💔 \u062d\u0630\u0641 \u0627\u0632 \u0639\u0644\u0627\u0642\u0647\u200c\u0645\u0646\u062f\u06cc\u200c\u0647\u0627",
                                          callback_data=f"unfav:{movie_id}")])
    else:
        rows.append([InlineKeyboardButton("❤️ \u0627\u0641\u0632\u0648\u062f\u0646 \u0628\u0647 \u0639\u0644\u0627\u0642\u0647\u200c\u0645\u0646\u062f\u06cc\u200c\u0647\u0627",
                                          callback_data=f"fav:{movie_id}")])

    return InlineKeyboardMarkup(rows)


def episode_list_kb(movie_id: str, quality: str, ep_type: str,
                      indexed_eps: list, page: int, page_size: int,
                      is_fav: bool) -> InlineKeyboardMarkup:
    """کیبورد مرحله‌ی ۳: لیست قسمت‌ها."""
    rows = []
    total = len(indexed_eps)
    pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, pages - 1))
    start = page * page_size
    chunk = indexed_eps[start:start + page_size]

    for orig_idx, ep in chunk:
        short = ep.label[:52]
        if len(ep.label) > 52:
            short += "..."
        rows.append([InlineKeyboardButton(
            f"\u25b6\ufe0f {short}",
            callback_data=f"ep:{movie_id}:{orig_idx}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ \u0642\u0628\u0644\u06cc",
                     callback_data=f"epl:{movie_id}:{quality}:{ep_type}:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(f"\u0635\u0641\u062d\u0647 {page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("\u0628\u0639\u062f\u06cc \u27a1\ufe0f",
                     callback_data=f"epl:{movie_id}:{quality}:{ep_type}:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("\u2b05\ufe0f \u0628\u0627\u0632\u06af\u0634\u062a", callback_data=f"bqt:{movie_id}:{quality}")])

    if is_fav:
        rows.append([InlineKeyboardButton("💔 \u062d\u0630\u0641 \u0627\u0632 \u0639\u0644\u0627\u0642\u0647\u200c\u0645\u0646\u062f\u06cc\u200c\u0647\u0627",
                                          callback_data=f"unfav:{movie_id}")])
    else:
        rows.append([InlineKeyboardButton("❤️ \u0627\u0641\u0632\u0648\u062f\u0646 \u0628\u0647 \u0639\u0644\u0627\u0642\u0647\u200c\u0645\u0646\u062f\u06cc\u200c\u0647\u0627",
                                          callback_data=f"fav:{movie_id}")])

    return InlineKeyboardMarkup(rows)


def webapp_play_kb(webapp_url: str) -> InlineKeyboardMarkup:
    """کیبورد پخش WebApp: دکمه‌ی تماشای آنلاین که صفحه‌ی پلیر را باز می‌کند."""
    rows = [[InlineKeyboardButton(
        "▶️ تماشای آنلاین",
        web_app=WebAppInfo(url=webapp_url)
    )]]
    return InlineKeyboardMarkup(rows)


def play_kb(https_link: str) -> InlineKeyboardMarkup:
    """دکمه‌ی تماشای آنلاین — لینک مستقیم HTTP بدون نمایش در چت."""
    rows = [[InlineKeyboardButton("\u25b6\ufe0f \u062a\u0645\u0627\u0634\u0627\u06cc \u0622\u0646\u0644\u0627\u06cc\u0646", url=https_link)]]
    return InlineKeyboardMarkup(rows)


def join_kb(channels, check_cb: str = "checkjoin") -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        link = ch["invite_link"] or (f"https://t.me/{ch['chat_id'].lstrip('@')}"
                                     if str(ch["chat_id"]).startswith("@") else None)
        title = ch["title"] or ch["chat_id"]
        if link:
            rows.append([InlineKeyboardButton(f"📢 {title}", url=link)])
    rows.append([InlineKeyboardButton("✅ عضو شدم", callback_data=check_cb)])
    return InlineKeyboardMarkup(rows)


def favorites_kb(favs) -> InlineKeyboardMarkup:
    rows = []
    for f in favs:
        rows.append([InlineKeyboardButton(f"🎬 {f['title']}", callback_data=f"mv:{f['movie_id']}")])
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([])


def history_kb(items) -> InlineKeyboardMarkup:
    """تاریخچه‌ی تماشا: هر مورد دکمه‌ای برای باز کردن دوباره‌ی فیلم."""
    rows = []
    for it in items:
        ep = f" — {it['episode']}" if it["episode"] else ""
        rows.append([InlineKeyboardButton(f"🎬 {it['title']}{ep}",
                                          callback_data=f"mv:{it['movie_id']}")])
    if rows:
        rows.append([InlineKeyboardButton("🗑 پاک کردن تاریخچه", callback_data="clearwatch")])
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([])


def recent_searches_kb(queries) -> InlineKeyboardMarkup:
    """جستجوهای اخیر: هر مورد دکمه‌ای برای جستجوی دوباره."""
    rows = []
    for i, q in enumerate(queries):
        rows.append([InlineKeyboardButton(f"🔍 {q}", callback_data=f"rs:{i}")])
    if rows:
        rows.append([InlineKeyboardButton("🗑 پاک کردن تاریخچه جستجو", callback_data="clearsearch")])
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([])


# ---------------- پنل مدیریت ----------------
def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار ربات", callback_data="adm:stats")],
        [InlineKeyboardButton("📢 کانال‌های عضویت اجباری", callback_data="adm:channels")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="adm:broadcast")],
        [InlineKeyboardButton("📤 ارسال فایل دیتابیس", callback_data="adm:senddb"),
         InlineKeyboardButton("♻️ بازیابی دیتابیس", callback_data="adm:restoredb")],
        [InlineKeyboardButton("👤 مدیریت ادمین‌ها", callback_data="adm:admins")],
        [InlineKeyboardButton("🐞 لاگ خطاها", callback_data="adm:errors")],
        [InlineKeyboardButton("❌ بستن", callback_data="adm:close")],
    ])


def channels_kb(channels) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        title = ch["title"] or ch["chat_id"]
        rows.append([
            InlineKeyboardButton(f"📢 {title}", callback_data="noop"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"adm:delch:{ch['chat_id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ افزودن کانال", callback_data="adm:addch")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm:home")])
    return InlineKeyboardMarkup(rows)


def admins_kb(admin_ids, super_admin: int) -> InlineKeyboardMarkup:
    rows = []
    for aid in admin_ids:
        label = f"👑 {aid}" + (" (سوپر‌ادمین)" if aid == super_admin else "")
        btns = [InlineKeyboardButton(label, callback_data="noop")]
        if aid != super_admin:
            btns.append(InlineKeyboardButton("🗑", callback_data=f"adm:deladmin:{aid}"))
        rows.append(btns)
    rows.append([InlineKeyboardButton("➕ افزودن ادمین", callback_data="adm:addadmin")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm:home")])
    return InlineKeyboardMarkup(rows)


def back_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="adm:home")]])
