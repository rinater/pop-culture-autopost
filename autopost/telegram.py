import json
import logging
import os
import time
from datetime import datetime

import httpx

log = logging.getLogger("autopost.telegram")

API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024  # UTF-16 units
TEXT_LIMIT = 4096


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class Telegram:
    def __init__(self, token: str, chat_id: str, dry_run: bool, out_dir: str = "out"):
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run
        self.out_dir = out_dir

    def send(self, text: str, photo_url: str | None = None) -> bool:
        if self.dry_run:
            return self._dry(text, photo_url)

        if photo_url and _utf16_len(text) <= CAPTION_LIMIT:
            ok = self._call("sendPhoto", {
                "chat_id": self.chat_id, "photo": photo_url,
                "caption": text, "parse_mode": "HTML",
            })
            if ok:
                return True
            log.warning("sendPhoto не сработал, отправляю текстом")

        return self._call("sendMessage", {
            "chat_id": self.chat_id, "text": text[:TEXT_LIMIT],
            "parse_mode": "HTML", "disable_web_page_preview": True,
        })

    def _call(self, method: str, data: dict) -> bool:
        url = API.format(token=self.token, method=method)
        for attempt in range(3):
            try:
                r = httpx.post(url, data=data, timeout=30)
                if r.status_code == 429:
                    wait = r.json().get("parameters", {}).get("retry_after", 5)
                    time.sleep(wait)
                    continue
                if r.status_code == 200 and r.json().get("ok"):
                    return True
                log.error("Telegram %s: %s %s", method, r.status_code, r.text[:300])
                if 400 <= r.status_code < 500:
                    return False
            except httpx.HTTPError as e:
                log.warning("Telegram %s: сетевая ошибка %s", method, e)
            time.sleep(2 ** attempt)
        return False

    def _dry(self, text: str, photo_url: str | None) -> bool:
        os.makedirs(self.out_dir, exist_ok=True)
        name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json"
        payload = {"text": text, "photo": photo_url, "text_len_utf16": _utf16_len(text)}
        with open(os.path.join(self.out_dir, name), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log.info("[DRY-RUN] пост сохранён в %s/%s (%d симв. UTF-16)",
                 self.out_dir, name, payload["text_len_utf16"])
        log.info("[DRY-RUN]\n%s", text)
        return True
