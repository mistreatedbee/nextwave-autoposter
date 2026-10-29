#!/usr/bin/env python3
"""NextWave auto-poster CLI.

  python3 post.py validate
  python3 post.py check
  python3 post.py flyer [--dry-run] [--flyer ID] [--only facebook_feed,...] [--date YYYY-MM-DD]
  python3 post.py text  [--dry-run] [--date ...]
  python3 post.py reel  [--dry-run] [--only instagram_reel,facebook_reel]
  python3 post.py pack  [--dry-run] [--flyer ID] [--date ...]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

import content
import emailer
from meta_api import MetaClient, MetaError

STEPS = ["facebook_feed", "facebook_story", "instagram_feed", "instagram_story"]
ON_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"


def load_env(path: Path = content.ROOT / ".env") -> None:
    """Tiny .env loader; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def annotate_error(title: str, message: str) -> None:
    if ON_GITHUB:
        msg = message.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::error title={title}::{msg}")


def image_url(kind: str, flyer_id: str, dry_run: bool) -> str:
    base = os.environ.get("IMAGE_BASE_URL")
    if not base:
        repo, ref = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_REF_NAME")
        if repo and ref:
            base = f"https://raw.githubusercontent.com/{repo}/{ref}/images"
        elif dry_run:
            base = "https://raw.githubusercontent.com/<user>/<repo>/<branch>/images"
        else:
            raise MetaError("Cannot build the public image URL: set IMAGE_BASE_URL "
                            "(or GITHUB_REPOSITORY and GITHUB_REF_NAME).")
    return f"{base.rstrip('/')}/{kind}/{flyer_id}.jpg"


def video_url(flyer_id: str, dry_run: bool) -> str:
    base = os.environ.get("VIDEO_BASE_URL")
    if not base:
        img = os.environ.get("IMAGE_BASE_URL")
        if img:
            base = img.rstrip("/").removesuffix("/images") + "/videos"
        else:
            repo, ref = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_REF_NAME")
            if repo and ref:
                base = f"https://raw.githubusercontent.com/{repo}/{ref}/videos"
            elif dry_run:
                base = "https://raw.githubusercontent.com/<user>/<repo>/<branch>/videos"
            else:
                raise MetaError("Cannot build the public video URL: set VIDEO_BASE_URL "
                                "(or GITHUB_REPOSITORY and GITHUB_REF_NAME).")
    return f"{base.rstrip('/')}/{flyer_id}.mp4"


def client() -> MetaClient:
    missing = [k for k in ("META_PAGE_ID", "META_PAGE_TOKEN") if not os.environ.get(k)]
    if missing:
        raise MetaError(f"Missing environment variable(s): {', '.join(missing)}. "
                        "Create .env with get_tokens.py or set the GitHub secrets.")
    return MetaClient(os.environ["META_PAGE_ID"], os.environ["META_PAGE_TOKEN"],
                      os.environ.get("META_IG_USER_ID"))


def run_steps(steps: list[tuple[str, callable]]) -> int:
    failed = 0
    for name, fn in steps:
        try:
            result = fn()
            print(f"OK    {name}" + (f" -> {result}" if result else ""))
        except Exception as e:  # one failure must not stop the others
            failed += 1
            print(f"FAIL  {name}: {e}")
            annotate_error(name, str(e))
    return 1 if failed else 0


def cmd_validate(args) -> int:
    problems = content.validate()
    if problems:
        for p in problems:
            print(f"PROBLEM: {p}")
            annotate_error("validate", p)
        return 1
    c = content.Content()
    print(f"OK: {len(c.flyers)} flyers x {content.VARIANTS} captions, "
          f"{len(c.text['posts'])} text posts ({content.TEXT_SLOTS}/day), all limits respected.")
    return 0


def cmd_check(args) -> int:
    def go():
        res = client().check()
        page = res["page"]
        line = f"Page '{page.get('name')}' ({page.get('id')})"
        if "instagram" in res:
            line += f", Instagram @{res['instagram'].get('username')}"
        return line
    return run_steps([("check", go)])


def pick(args, c: content.Content):
    day = content.parse_date(args.date)
    flyer, variant = c.flyer_for(day, args.flyer)
    return day, flyer, variant


def cmd_flyer(args) -> int:
    c = content.Content()
    problems = content.validate(c)
    if problems:
        for p in problems:
            print(f"PROBLEM: {p}")
        annotate_error("validate", "; ".join(problems))
        return 1
    day, flyer, variant = pick(args, c)
    wanted = args.only.split(",") if args.only else STEPS
    bad = [s for s in wanted if s not in STEPS]
    if bad:
        print(f"Unknown step(s): {', '.join(bad)}. Choose from: {', '.join(STEPS)}")
        return 2
    fb_caption = flyer.caption(variant, "facebook")
    ig_caption = flyer.caption(variant, "instagram")
    print(f"{day} -> flyer '{flyer.id}', caption variant {variant + 1}/{content.VARIANTS}")

    if args.dry_run:
        for s in wanted:
            kind = "story" if s.endswith("story") else "feed"
            print(f"\n--- DRY RUN: {s} ---")
            if s.startswith("instagram"):
                print(f"image_url: {image_url(kind, flyer.id, True)}")
            else:
                print(f"file: {(flyer.png if s == 'facebook_feed' else flyer.story_jpg()).relative_to(content.ROOT)}")
            if s.endswith("feed"):
                print(s.startswith("instagram") and ig_caption or fb_caption)
        return 0

    jobs = {}
    try:
        meta = client()
    except MetaError as e:
        print(f"FAIL  setup: {e}")
        annotate_error("setup", str(e))
        return 1
    jobs["facebook_feed"] = lambda: meta.fb_post_photo(flyer.png, fb_caption)
    jobs["facebook_story"] = lambda: meta.fb_post_story(flyer.story_jpg())
    jobs["instagram_feed"] = lambda: meta.ig_post_image(image_url("feed", flyer.id, False), caption=ig_caption)
    jobs["instagram_story"] = lambda: meta.ig_post_image(image_url("story", flyer.id, False), story=True)
    return run_steps([(s, jobs[s]) for s in wanted])


REEL_STEPS = ["instagram_reel", "facebook_reel"]
REEL_DAY_OFFSET = 2  # the reel shows a different flyer than today's image post


def cmd_reel(args) -> int:
    c = content.Content()
    day = content.parse_date(args.date) + timedelta(days=REEL_DAY_OFFSET)
    flyer, variant = c.flyer_for(day, args.flyer)
    wanted = args.only.split(",") if args.only else REEL_STEPS
    bad = [s for s in wanted if s not in REEL_STEPS]
    if bad:
        print(f"Unknown step(s): {', '.join(bad)}. Choose from: {', '.join(REEL_STEPS)}")
        return 2
    video = flyer.video
    ig_caption, fb_caption = flyer.caption(variant, "instagram"), flyer.caption(variant, "facebook")
    print(f"reel for flyer '{flyer.id}', caption variant {variant + 1}/{content.VARIANTS}")
    if not video.exists():
        msg = f"Missing video file {video.relative_to(content.ROOT)} (run make_videos.py)"
        print(f"FAIL  setup: {msg}")
        annotate_error("reel", msg)
        return 1
    if args.dry_run:
        for s in wanted:
            print(f"\n--- DRY RUN: {s} ---")
            print(f"video_url: {video_url(flyer.id, True)}" if s == "instagram_reel"
                  else f"file: {video.relative_to(content.ROOT)}")
            print(ig_caption if s == "instagram_reel" else fb_caption)
        return 0
    try:
        meta = client()
    except MetaError as e:
        print(f"FAIL  setup: {e}")
        annotate_error("setup", str(e))
        return 1
    jobs = {"instagram_reel": lambda: meta.ig_post_reel(video_url(flyer.id, False), ig_caption),
            "facebook_reel": lambda: meta.fb_post_reel(video, fb_caption)}
    return run_steps([(s, jobs[s]) for s in wanted])


def cmd_text(args) -> int:
    c = content.Content()
    message = c.text_post(content.parse_date(args.date), args.slot)
    if args.dry_run:
        print(f"--- DRY RUN: facebook text post (slot {args.slot}) ---")
        print(message)
        return 0
    try:
        meta = client()
    except MetaError as e:
        print(f"FAIL  setup: {e}")
        annotate_error("setup", str(e))
        return 1
    return run_steps([("facebook_text", lambda: meta.fb_post_text(message))])


def build_pack(flyer: content.Flyer, day) -> tuple[str, str]:
    g1, g2 = flyer.group_texts()
    subject = f"NextWave group pack {day}: {flyer.title}"
    body = (f"Today's flyer: {flyer.title}\n"
            "Attached image: save it and post it in your Facebook groups (check each group's rules first).\n\n"
            f"=== CAPTION 1 ===\n{g1}\n\n=== CAPTION 2 ===\n{g2}\n")
    return subject, body


def cmd_pack(args) -> int:
    c = content.Content()
    day, flyer, _ = pick(args, c)
    subject, body = build_pack(flyer, day)
    if args.dry_run:
        print(f"--- DRY RUN: email '{subject}' (attach {flyer.feed_jpg().relative_to(content.ROOT)}) ---")
        print(body)
        return 0
    if not emailer.smtp_configured():
        print("SMTP_USER / SMTP_APP_PASSWORD not set; skipping group pack email.")
        return 0
    return run_steps([("pack_email",
                       lambda: "sent to " + emailer.send_pack(subject, body, flyer.feed_jpg()))])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["validate", "check", "flyer", "text", "pack", "reel"])
    ap.add_argument("--dry-run", action="store_true", help="show what would be posted; post nothing")
    ap.add_argument("--flyer", help="flyer id override")
    ap.add_argument("--only", help="comma-separated steps: " + ",".join(STEPS + REEL_STEPS))
    ap.add_argument("--slot", type=int, choices=range(content.TEXT_SLOTS), default=0,
                    help="text mode: which of the day's posts (0=morning, 1=midday, 2=evening)")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, South Africa time)")
    args = ap.parse_args(argv)
    load_env()
    try:
        return {"validate": cmd_validate, "check": cmd_check, "flyer": cmd_flyer,
                "text": cmd_text, "pack": cmd_pack, "reel": cmd_reel}[args.mode](args)
    except ValueError as e:
        print(f"ERROR: {e}")
        annotate_error(args.mode, str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
