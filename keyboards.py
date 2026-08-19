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
from categorize import categorize_episodes, QUALITY_ORDER, QUALITY_LABELS, TYPE_LABELS


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


def search_results_kb(results: List[SearchResult]) -> InlineKeyboardMarkup:
    """لیست نتایج جستجو در چت خصوصی — هر فیلم یک دکمه."""
    rows = []
    for r in results:
        year = f" ({r.year})" if r.year else ""
        imdb = f" ⭐{r.imdb}" if r.imdb else ""
        rows.append([InlineKeyboardButton(f"🎬 {r.title}{year}{imdb}",
                                          callback_data=f"mv:{r.movie_id}")])
    return InlineKeyboardMarkup(rows)


def movie_card_kb(movie: Movie, page: int, page_size: int,
                  is_fav: bool) -> InlineKeyboardMarkup:
    """کیبورد کارت فیلم: قسمت‌ها دسته‌بندی‌شده (کیفیت + نوع) + صفحه‌بندی."""
    rows: List[List[InlineKeyboardButton]] = []
    eps = movie.episodes
    total = len(eps)

    if total == 0:
        rows.append([InlineKeyboardButton("⚠️ لینکی موجود نیست", callback_data="noop")])
    else:
        cats = categorize_episodes(eps)
        # ساختن لیست مسطح: [(text, callback_data), ...]
        flat = []
        for q in QUALITY_ORDER:
            if q not in cats:
                continue
            groups = cats[q]
            for t_key, t_label in TYPE_LABELS:
                ep_list = groups.get(t_key, [])
                if not ep_list:
                    continue
                flat.append((f"📋 {QUALITY_LABELS.get(q, q)} — {t_label}", "noop"))
                for ep_obj in ep_list:
                    idx = eps.index(ep_obj)
                    short = ep_obj.label[:48]
                    if len(ep_obj.label) > 48:
                        short += "..."
                    flat.append((f"▶️ {short}", f"ep:{movie.movie_id}:{idx}"))
        # اگه کیفیت "other" هست
        if "other" in cats:
            for t_key, t_label in TYPE_LABELS:
                ep_list = cats["other"].get(t_key, [])
                if not ep_list:
                    continue
                flat.append((f"📋 سایر — {t_label}", "noop"))
                for ep_obj in ep_list:
                    idx = eps.index(ep_obj)
                    short = ep_obj.label[:48]
                    if len(ep_obj.label) > 48:
                        short += "..."
                    flat.append((f"▶️ {short}", f"ep:{movie.movie_id}:{idx}"))

        # صفحه‌بندی
        pages = max(1, math.ceil(len(flat) / page_size))
        page = max(0, min(page, pages - 1))
        start = page * page_size
        chunk = flat[start:start + page_size]
        for text, cb in chunk:
            if cb == "noop":
                rows.append([InlineKeyboardButton(text, callback_data="noop")])
            else:
                rows.append([InlineKeyboardButton(text, callback_data=cb)])

        # ناوبری
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"epp:{movie.movie_id}:{page-1}"))
        if pages > 1:
            nav.append(InlineKeyboardButton(f"صفحه {page+1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"epp:{movie.movie_id}:{page+1}"))
        if nav:
            rows.append(nav)

    # علاقه‌مندی
    if is_fav:
        rows.append([InlineKeyboardButton("💔 حذف از علاقه‌مندی‌ها",
                                          callback_data=f"unfav:{movie.movie_id}")])
    else:
        rows.append([InlineKeyboardButton("❤️ افزودن به علاقه‌مندی‌ها",
                                          callback_data=f"fav:{movie.movie_id}")])

    return InlineKeyboardMarkup(rows)


def webapp_play_kb(webapp_url: str) -> InlineKeyboardMarkup:
    """کیبورد پخش WebApp: دکمه‌ی تماشای آنلاین که صفحه‌ی پلیر را باز می‌کند."""
    rows = [[InlineKeyboardButton(
        "▶️ تماشای آنلاین",
        web_app=WebAppInfo(url=webapp_url)
    )]]
    return InlineKeyboardMarkup(rows)


def play_kb(https_link: str) -> InlineKeyboardMarkup:
    """کیبورد پیام پخش: لینک مستقیم به صورت دکمه‌ی URL."""
    rows = [[InlineKeyboardButton("🌐 لینک مستقیم (باز کردن/کپی)", url=https_link)]]
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