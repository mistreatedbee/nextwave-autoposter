"""Minimal Meta Graph API client for Facebook Page + Instagram publishing.

Safety rules baked in:
  * the access token is sent in the body/params and scrubbed from every error;
  * only safe calls (GETs, Instagram container creation) are retried;
  * publishing calls are never retried, so a flaky response cannot double-post.
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

import requests

DEFAULT_VERSION = "v26.0"
TIMEOUT = 60
UPLOAD_TIMEOUT = 180
MAX_ATTEMPTS = 3
RETRY_DELAY = 2.0

ERROR_HINTS = {
    190: "The access token is invalid or has expired. Run get_tokens.py again and update the META_PAGE_TOKEN secret.",
    10: "Missing permission. Re-create the token with pages_manage_posts, pages_read_engagement, instagram_basic and instagram_content_publish.",
    200: "Missing permission. Re-create the token with pages_manage_posts, pages_read_engagement, instagram_basic and instagram_content_publish.",
    4: "Rate limit reached. Wait a while and try again.",
    17: "Rate limit reached. Wait a while and try again.",
    32: "Rate limit reached. Wait a while and try again.",
    613: "Rate limit reached. Wait a while and try again.",
    368: "Meta has temporarily blocked this action (it may look like spam). Wait and post less often; check the Page's quality in Meta Business Suite.",
}


class MetaError(Exception):
    def __init__(self, message: str, code: int | None = None, subcode: int | None = None,
                 transient: bool = False):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.transient = transient


class MetaClient:
    def __init__(self, page_id: str, page_token: str, ig_user_id: str | None = None,
                 version: str | None = None, session=None, sleep=time.sleep):
        self.page_id = page_id
        self.token = page_token
        self.ig_user_id = ig_user_id
        self.version = version or os.environ.get("GRAPH_API_VERSION") or DEFAULT_VERSION
        self.base = f"https://graph.facebook.com/{self.version}"
        self.session = session or requests.Session()
        self.sleep = sleep

    # ---- helpers -------------------------------------------------------
    def _scrub(self, text) -> str:
        text = str(text)
        return text.replace(self.token, "***") if self.token else text

    def _error_from(self, status: int, body) -> MetaError:
        err = body.get("error", {}) if isinstance(body, dict) else {}
        code, sub = err.get("code"), err.get("error_subcode")
        msg = err.get("error_user_msg") or err.get("message") or f"HTTP {status}"
        text = f"Graph API error (HTTP {status}, code {code}" + (f"/{sub}" if sub else "") + f"): {msg}"
        hint = ERROR_HINTS.get(code)
        if hint:
            text += f" -> {hint}"
        transient = status >= 500 or bool(err.get("is_transient")) or code in (1, 2)
        return MetaError(self._scrub(text), code, sub, transient)

    def _request(self, method: str, path: str, *, params=None, data=None, files=None,
                 retry: bool = False, timeout: int = TIMEOUT) -> dict:
        url = f"{self.base}/{path.lstrip('/')}"
        attempts = MAX_ATTEMPTS if retry else 1
        last: MetaError | None = None
        for attempt in range(1, attempts + 1):
            if files:  # file handles must be rewound if we ever re-send
                for f in files.values():
                    if hasattr(f[1], "seek"):
                        f[1].seek(0)
            kwargs = {"timeout": timeout}
            if method == "GET":
                kwargs["params"] = {**(params or {}), "access_token": self.token}
            else:
                kwargs["data"] = {**(data or {}), "access_token": self.token}
                if files:
                    kwargs["files"] = files
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.RequestException as e:
                last = MetaError(self._scrub(f"Network error calling {path}: {type(e).__name__}: {e}"),
                                 transient=True)
            else:
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                if resp.status_code >= 400 or (isinstance(body, dict) and "error" in body):
                    last = self._error_from(resp.status_code, body)
                else:
                    return body
            if not (retry and last.transient and attempt < attempts):
                raise last
            self.sleep(RETRY_DELAY * attempt)
        raise last  # pragma: no cover

    def _get(self, path: str, params=None) -> dict:
        return self._request("GET", path, params=params, retry=True)

    # ---- checks --------------------------------------------------------
    def check(self) -> dict:
        out = {"page": self._get(self.page_id, {"fields": "id,name"})}
        if self.ig_user_id:
            out["instagram"] = self._get(self.ig_user_id, {"fields": "id,username"})
        return out

    # ---- Facebook ------------------------------------------------------
    def fb_post_text(self, message: str) -> dict:
        return self._request("POST", f"{self.page_id}/feed", data={"message": message})

    def _upload_photo(self, image: Path, published: bool, caption: str | None = None) -> dict:
        image = Path(image)
        data = {"published": "true" if published else "false"}
        if caption:
            data["caption"] = caption
        mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        with open(image, "rb") as fh:
            return self._request("POST", f"{self.page_id}/photos", data=data,
                                 files={"source": (image.name, fh, mime)}, timeout=UPLOAD_TIMEOUT)

    def fb_post_photo(self, image: Path, caption: str) -> dict:
        return self._upload_photo(image, published=True, caption=caption)

    def fb_post_story(self, image: Path) -> dict:
        # A photo already used in a published post can't be reused for a story,
        # so upload a fresh unpublished copy first.
        photo = self._upload_photo(image, published=False)
        return self._request("POST", f"{self.page_id}/photo_stories", data={"photo_id": photo["id"]})

    def fb_post_reel(self, video: Path, description: str) -> dict:
        """Facebook Page Reel: start -> upload bytes -> finish (publish). None of it is retried."""
        video = Path(video)
        size = video.stat().st_size
        start = self._request("POST", f"{self.page_id}/video_reels", data={"upload_phase": "start"})
        video_id, upload_url = start["video_id"], start["upload_url"]
        headers = {"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size)}
        try:
            resp = self.session.request("POST", upload_url, headers=headers,
                                        data=video.read_bytes(), timeout=UPLOAD_TIMEOUT)
        except requests.RequestException as e:
            raise MetaError(self._scrub(f"Network error uploading reel: {type(e).__name__}: {e}"))
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400 or not body.get("success", True) or "error" in body:
            raise self._error_from(resp.status_code, body)
        return self._request("POST", f"{self.page_id}/video_reels", data={
            "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
            "description": description})

    # ---- Instagram -----------------------------------------------------
    def ig_post_image(self, image_url: str, caption: str | None = None, story: bool = False,
                      poll_interval: float = 3.0, timeout: float = 90.0) -> dict:
        data = {"image_url": image_url}
        if story:
            data["media_type"] = "STORIES"
        elif caption:
            data["caption"] = caption
        return self._ig_publish(data, poll_interval, timeout)

    def ig_post_reel(self, video_url: str, caption: str, poll_interval: float = 5.0,
                     timeout: float = 300.0) -> dict:
        data = {"media_type": "REELS", "video_url": video_url, "caption": caption,
                "share_to_feed": "true"}
        return self._ig_publish(data, poll_interval, timeout)

    def _ig_publish(self, data: dict, poll_interval: float, timeout: float) -> dict:
        if not self.ig_user_id:
            raise MetaError("META_IG_USER_ID is not set.")
        # Creating a container publishes nothing, so retrying it is safe.
        container = self._request("POST", f"{self.ig_user_id}/media", data=data, retry=True)
        cid = container["id"]
        polls = math.ceil(timeout / poll_interval) + 1
        status = None
        for i in range(polls):
            status = self._get(cid, {"fields": "status_code"}).get("status_code")
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                raise MetaError(f"Instagram could not process the media (status {status}). "
                                "Check the URL is public and the file format is valid.")
            if i < polls - 1:
                self.sleep(poll_interval)
        else:
            raise MetaError(f"Timed out after {timeout:.0f}s waiting for Instagram to process the media "
                            f"(last status {status}).")
        # Publishing is NEVER retried.
        return self._request("POST", f"{self.ig_user_id}/media_publish", data={"creation_id": cid})
