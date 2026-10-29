"""Content loading, rotation, caption building and validation (no network)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
SAST = ZoneInfo("Africa/Johannesburg")

IG_MAX_HASHTAGS = 12
FB_MAX_HASHTAGS = 4
IG_HARD_HASHTAGS = 30
IG_MAX_CHARS = 2200
FB_MAX_CHARS = 5000
VARIANTS = 3
GROUP_VARIANTS = 2
BANNED_CLAIMS = ("120+", "350+", "85%")


def load_json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def today_sast() -> date:
    return datetime.now(SAST).date()


def parse_date(value: str | None) -> date:
    return date.fromisoformat(value) if value else today_sast()


def rotation(day: date, n_flyers: int) -> tuple[int, int]:
    """Return (flyer_index, variant_index) for a date. Stateless."""
    ordinal = day.toordinal()
    return ordinal % n_flyers, (ordinal // n_flyers) % VARIANTS


TEXT_SLOTS = 3  # text posts per day: morning, midday, evening


def text_index(day: date, n_posts: int, slot: int = 0) -> int:
    """Stateless tip index; each day uses TEXT_SLOTS consecutive tips."""
    return (day.toordinal() * TEXT_SLOTS + slot) % n_posts


def _fill(text: str, data: dict) -> str:
    return text.format_map({k: data[k] for k in ("site", "phone", "email")})


def _tags(items: list[str]) -> str:
    return " ".join("#" + t.lstrip("#") for t in items)


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for t in items:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


class Flyer:
    def __init__(self, data: dict, flyer: dict):
        self._d = data
        self.id = flyer["id"]
        self.title = flyer["title"]
        self.hashtags = flyer["hashtags"]
        self.captions = flyer["captions"]
        self.group_captions = flyer["group_captions"]

    @property
    def png(self) -> Path:
        return ROOT / "flyers" / f"{self.id}.png"

    def feed_jpg(self) -> Path:
        return ROOT / "images" / "feed" / f"{self.id}.jpg"

    def story_jpg(self) -> Path:
        return ROOT / "images" / "story" / f"{self.id}.jpg"

    def _hashtags(self, platform: str) -> list[str]:
        common = self._d["common_hashtags"]
        if platform == "facebook":
            return _dedupe(self.hashtags[:2] + common[:2])[:FB_MAX_HASHTAGS]
        return _dedupe(self.hashtags + common)[:IG_MAX_HASHTAGS]

    def caption(self, variant: int, platform: str) -> str:
        body = _fill(self.captions[variant % len(self.captions)], self._d)
        return f"{body}\n\n{_tags(self._hashtags(platform))}"

    def group_texts(self) -> list[str]:
        return [_fill(c, self._d) for c in self.group_captions]


class Content:
    def __init__(self):
        self.data = load_json("captions.json")
        self.text = load_json("text_posts.json")
        self.flyers = [Flyer(self.data, f) for f in self.data["flyers"]]

    def flyer_for(self, day: date, flyer_id: str | None = None) -> tuple[Flyer, int]:
        idx, variant = rotation(day, len(self.flyers))
        if flyer_id:
            ids = [f.id for f in self.flyers]
            if flyer_id not in ids:
                raise ValueError(f"Unknown flyer '{flyer_id}'. Choose from: {', '.join(ids)}")
            idx = ids.index(flyer_id)
        return self.flyers[idx], variant

    def text_post(self, day: date, slot: int = 0) -> str:
        posts = self.text["posts"]
        body = posts[text_index(day, len(posts), slot)]
        return body + "\n\n" + _fill(self.text["footer"], self.data)


def count_hashtags(text: str) -> int:
    return len(re.findall(r"(?<!\w)#\w+", text))


def validate(content: Content | None = None, check_images: bool = True) -> list[str]:
    """Return a list of problems (empty list = all good)."""
    c = content or Content()
    problems: list[str] = []
    ids = [f.id for f in c.flyers]
    if len(set(ids)) != len(ids):
        problems.append("Duplicate flyer ids")
    for f in c.flyers:
        if len(f.captions) != VARIANTS:
            problems.append(f"{f.id}: needs {VARIANTS} captions, has {len(f.captions)}")
        if len(f.group_captions) != GROUP_VARIANTS:
            problems.append(f"{f.id}: needs {GROUP_VARIANTS} group_captions")
        for i in range(len(f.captions)):
            for platform, max_tags in (("instagram", IG_MAX_HASHTAGS), ("facebook", FB_MAX_HASHTAGS)):
                try:
                    cap = f.caption(i, platform)
                except (KeyError, IndexError, ValueError) as e:
                    problems.append(f"{f.id} caption {i}: bad placeholder ({e})")
                    continue
                n = count_hashtags(cap)
                if n > max_tags:
                    problems.append(f"{f.id} caption {i} {platform}: {n} hashtags (max {max_tags})")
                if platform == "instagram":
                    if len(cap) > IG_MAX_CHARS:
                        problems.append(f"{f.id} caption {i}: {len(cap)} chars > {IG_MAX_CHARS}")
                    if n > IG_HARD_HASHTAGS:
                        problems.append(f"{f.id} caption {i}: {n} hashtags > {IG_HARD_HASHTAGS}")
                elif len(cap) > FB_MAX_CHARS:
                    problems.append(f"{f.id} caption {i} facebook: too long")
                if "{" in cap or "}" in cap:
                    problems.append(f"{f.id} caption {i}: unfilled placeholder")
                if any(b in cap for b in BANNED_CLAIMS):
                    problems.append(f"{f.id} caption {i}: contains an unsubstantiated stat")
        if check_images and not f.png.exists():
            problems.append(f"Missing flyer image {f.png.relative_to(ROOT)}")
    posts = c.text.get("posts", [])
    if len(posts) < TEXT_SLOTS * 14:
        problems.append(f"text_posts.json needs at least {TEXT_SLOTS * 14} posts, has {len(posts)}")
    if len(set(posts)) != len(posts):
        problems.append("text_posts.json has duplicate posts")
    for i, p in enumerate(posts):
        if not p.strip():
            problems.append(f"text post {i} is empty")
    return problems
