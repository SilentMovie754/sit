# -*- coding: utf-8 -*-
"""
ai_search.py
------------
جستجوی هوشمند فیلم با استفاده از Anthropic Claude API.

کاربر عکس پوستر فیلم را می‌فرستد و نام فیلم را می‌نویسد.
AI عکس را تحلیل کرده و نام دقیق انگلیسی فیلم را برمی‌گرداند.
"""
from __future__ import annotations

import base64
import logging
import re

log = logging.getLogger("ai_search")

DEFAULT_BASE_URL = "https://seekai.cc"
DEFAULT_MODEL = "claude-sonnet-5"


def identify_movie(image_bytes: bytes, user_text: str, api_key: str,
                   base_url: str = DEFAULT_BASE_URL,
                   model: str = DEFAULT_MODEL) -> str:
    """
    عکس و نام فیلم را به Claude می‌فرستد و نام دقیق انگلیسی را برمی‌گرداند.
    
    Returns:
        نام فیلم به انگلیسی (مثلاً "Inception 2010")
    """
    import anthropic

    client = anthropic.Anthropic(base_url=base_url, api_key=api_key)

    # تشخیص فرمت عکس
    mime = "image/jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"

    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        f"A user sent this image and said the movie/series name is '{user_text}'. "
                        f"Identify the exact original English title of this movie/series and its release year. "
                        f"Reply ONLY with the title and year in this format: Title (Year)\n"
                        f"For example: Inception (2010) or Breaking Bad (2008)\n"
                        f"If you can also provide the Persian name, write it after a dash.\n"
                        f"Example: Inception (2010) - آغاز"
                    ),
                },
            ],
        }],
    )

    result = message.content[0].text.strip()
    log.info("AI result: %s", result)

    # پاک‌سازی نتیجه — فقط نام و سال را نگه می‌داریم
    # فرمت مورد انتظار: "Title (Year)" یا "Title (Year) - نام فارسی"
    match = re.search(r'(.+?)\s*\((\d{4})\)', result)
    if match:
        title = match.group(1).strip()
        year = match.group(2)
        return f"{title} {year}"

    # اگر فرمت متفاوت بود، کل نتیجه را برمی‌گردانیم
    return result
