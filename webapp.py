# -*- coding: utf-8 -*-
"""
webapp.py
----------
Flask سرور برای سرو index.html + ساخت لینک WebApp.
"""
from __future__ import annotations

import base64
import os
import threading
from urllib.parse import quote


def build_player_url(video_url: str, title: str = "", episode: str = "") -> str:
    """
    لینک WebApp میسازه.
    لینک فیلم base64 میشه و میره تو hash fragment.
    """
    base = os.environ.get("WEBAPP_URL", "").rstrip("/")
    b64 = base64.urlsafe_b64encode(video_url.encode()).decode().rstrip("=")
    url = base + "/#v=" + b64
    if title:
        url += "&t=" + quote(title)
    if episode:
        url += "&e=" + quote(episode)
    return url


def start_player_server() -> None:
    """
    Flask رو تو یه thread daemon ران میکنه.
    هر درخواستی index.html سرو میشه.
    """
    try:
        from flask import Flask, send_file
    except ImportError:
        print("[webapp] flask نصب نیست")
        return

    app = Flask(__name__)

    @app.route("/")
    def index():
        return send_file("index.html")

    port = int(os.environ.get("PORT", "10000"))
    t = threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=port,
            threaded=True,
            use_reloader=False,
        ),
        daemon=True,
    )
    t.start()
    print(f"[webapp] player server started on port {port}")
