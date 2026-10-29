import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import content  # noqa: E402
import prepare_images  # noqa: E402
import requests  # noqa: E402
from meta_api import MetaClient, MetaError  # noqa: E402

TOKEN = "SECRET_TOKEN_123"


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body


class FakeSession:
    """Replays queued responses (or exceptions) and records calls."""
    def __init__(self, *responses):
        self.queue = list(responses)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def paths(self):
        return [(m, u.split("/v26.0/")[1]) for m, u, _ in self.calls]


def make(*responses):
    s = FakeSession(*responses)
    return MetaClient("PAGE", TOKEN, "IG", version="v26.0", session=s, sleep=lambda _: None), s


class RotationTests(unittest.TestCase):
    def test_covers_all_flyers_and_variants(self):
        n = len(content.Content().flyers)
        start = date(2026, 1, 1)
        seen = [content.rotation(start + timedelta(days=i), n) for i in range(n * 3)]
        self.assertEqual({f for f, _ in seen[:n]}, set(range(n)))
        self.assertEqual({v for _, v in seen}, {0, 1, 2})
        # consecutive days rotate one flyer at a time
        for a, b in zip(seen, seen[1:]):
            self.assertEqual((a[0] + 1) % n, b[0])

    def test_text_posts_cycle_all(self):
        c = content.Content()
        start = date(2026, 1, 1)
        n = len(c.text["posts"])
        days = n // content.TEXT_SLOTS
        idx = [content.text_index(start + timedelta(days=i), n, s)
               for i in range(days) for s in range(content.TEXT_SLOTS)]
        self.assertEqual(len(set(idx)), len(idx))  # no repeats within a full cycle
        self.assertNotEqual(c.text_post(start, 0), c.text_post(start, 1))
        self.assertIn("073 153 1188", c.text_post(start))


class CaptionTests(unittest.TestCase):
    def test_validate_clean(self):
        self.assertEqual(content.validate(), [])

    def test_limits(self):
        c = content.Content()
        for f in c.flyers:
            for v in range(3):
                ig, fb = f.caption(v, "instagram"), f.caption(v, "facebook")
                self.assertLessEqual(len(ig), 2200)
                self.assertLessEqual(content.count_hashtags(ig), 12)
                self.assertLessEqual(content.count_hashtags(fb), 4)
                self.assertNotIn("{", ig)
            for g in f.group_texts():
                self.assertNotIn("{", g)

    def test_no_unsubstantiated_stats(self):
        raw = (content.ROOT / "captions.json").read_text()
        for bad in content.BANNED_CLAIMS:
            self.assertNotIn(bad, raw)

    def test_validate_catches_long_caption(self):
        c = content.Content()
        c.flyers[0].captions[0] = "x" * 2300
        self.assertTrue(any("2200" in p for p in content.validate(c)))

    def test_unknown_flyer(self):
        with self.assertRaises(ValueError):
            content.Content().flyer_for(date(2026, 1, 1), "nope")


class ImageTests(unittest.TestCase):
    def test_sizes_and_rgba(self):
        with tempfile.TemporaryDirectory() as d:
            src = Image.new("RGBA", (1100, 1500), (0, 0, 0, 0))
            flat = prepare_images.flatten(src)
            self.assertEqual(flat.mode, "RGB")
            self.assertEqual(flat.getpixel((5, 5)), (255, 255, 255))
            self.assertEqual(prepare_images.compose(flat, prepare_images.FEED_SIZE).size, (1080, 1350))
            story = prepare_images.compose(flat, prepare_images.STORY_SIZE, 220)
            self.assertEqual(story.size, (1080, 1920))

    def test_generated_files(self):
        for f in content.Content().flyers:
            if f.feed_jpg().exists():
                with Image.open(f.feed_jpg()) as a, Image.open(f.story_jpg()) as b:
                    self.assertEqual(a.size, (1080, 1350))
                    self.assertEqual(b.size, (1080, 1920))


class MetaClientTests(unittest.TestCase):
    def setUp(self):
        self.img = Path(tempfile.mkdtemp()) / "a.jpg"
        Image.new("RGB", (10, 10)).save(self.img)

    def test_check(self):
        c, s = make(FakeResp(body={"id": "PAGE", "name": "P"}), FakeResp(body={"id": "IG", "username": "u"}))
        self.assertEqual(c.check()["instagram"]["username"], "u")
        self.assertEqual(s.paths(), [("GET", "PAGE"), ("GET", "IG")])
        self.assertEqual(s.calls[0][2]["params"]["access_token"], TOKEN)

    def test_fb_text(self):
        c, s = make(FakeResp(body={"id": "1"}))
        c.fb_post_text("hi")
        self.assertEqual(s.paths(), [("POST", "PAGE/feed")])
        self.assertEqual(s.calls[0][2]["data"]["message"], "hi")

    def test_fb_photo(self):
        c, s = make(FakeResp(body={"id": "1"}))
        c.fb_post_photo(self.img, "cap")
        kw = s.calls[0][2]
        self.assertEqual(kw["data"]["published"], "true")
        self.assertIn("source", kw["files"])

    def test_story_flow_uploads_unpublished_then_story(self):
        c, s = make(FakeResp(body={"id": "PH1"}), FakeResp(body={"success": True}))
        c.fb_post_story(self.img)
        self.assertEqual(s.paths(), [("POST", "PAGE/photos"), ("POST", "PAGE/photo_stories")])
        self.assertEqual(s.calls[0][2]["data"]["published"], "false")
        self.assertEqual(s.calls[1][2]["data"]["photo_id"], "PH1")

    def test_ig_flow(self):
        c, s = make(FakeResp(body={"id": "C1"}), FakeResp(body={"status_code": "IN_PROGRESS"}),
                    FakeResp(body={"status_code": "FINISHED"}), FakeResp(body={"id": "M1"}))
        c.ig_post_image("https://x/y.jpg", caption="hello")
        self.assertEqual(s.paths(), [("POST", "IG/media"), ("GET", "C1"), ("GET", "C1"),
                                     ("POST", "IG/media_publish")])
        self.assertEqual(s.calls[0][2]["data"]["caption"], "hello")
        self.assertEqual(s.calls[3][2]["data"]["creation_id"], "C1")

    def test_ig_story_has_no_caption(self):
        c, s = make(FakeResp(body={"id": "C1"}), FakeResp(body={"status_code": "FINISHED"}),
                    FakeResp(body={"id": "M1"}))
        c.ig_post_image("https://x/y.jpg", caption="ignored", story=True)
        data = s.calls[0][2]["data"]
        self.assertEqual(data["media_type"], "STORIES")
        self.assertNotIn("caption", data)

    def test_ig_error_and_timeout(self):
        c, _ = make(FakeResp(body={"id": "C1"}), FakeResp(body={"status_code": "ERROR"}))
        with self.assertRaises(MetaError):
            c.ig_post_image("u", caption="c")
        c, s = make(FakeResp(body={"id": "C1"}), *[FakeResp(body={"status_code": "IN_PROGRESS"})] * 40)
        with self.assertRaisesRegex(MetaError, "Timed out"):
            c.ig_post_image("u", caption="c", poll_interval=3, timeout=9)
        self.assertNotIn(("POST", "IG/media_publish"), s.paths())

    def test_publish_not_retried(self):
        c, s = make(FakeResp(500, {"error": {"message": "boom", "code": 2}}), FakeResp(body={"id": "1"}))
        with self.assertRaises(MetaError):
            c.fb_post_text("x")
        self.assertEqual(len(s.calls), 1)
        c, s = make(FakeResp(body={"id": "C1"}), FakeResp(body={"status_code": "FINISHED"}),
                    FakeResp(500, {"error": {"message": "boom"}}), FakeResp(body={"id": "M"}))
        with self.assertRaises(MetaError):
            c.ig_post_image("u", caption="c")
        self.assertEqual(s.paths().count(("POST", "IG/media_publish")), 1)

    def test_safe_calls_are_retried(self):
        c, s = make(FakeResp(503, {}), requests.ConnectionError("down"), FakeResp(body={"id": "PAGE", "name": "n"}))
        self.assertEqual(c._get("PAGE")["id"], "PAGE")
        self.assertEqual(len(s.calls), 3)
        c, s = make(FakeResp(500, {}), FakeResp(body={"id": "C1"}), FakeResp(body={"status_code": "FINISHED"}),
                    FakeResp(body={"id": "M"}))
        c.ig_post_image("u", caption="c")
        self.assertEqual(s.paths()[:2], [("POST", "IG/media"), ("POST", "IG/media")])

    def test_ig_reel_flow(self):
        c, s = make(FakeResp(body={"id": "C1"}), FakeResp(body={"status_code": "IN_PROGRESS"}),
                    FakeResp(body={"status_code": "FINISHED"}), FakeResp(body={"id": "M1"}))
        c.ig_post_reel("https://x/v.mp4", "cap")
        data = s.calls[0][2]["data"]
        self.assertEqual((data["media_type"], data["video_url"], data["caption"]), ("REELS", "https://x/v.mp4", "cap"))
        self.assertEqual(s.paths(), [("POST", "IG/media"), ("GET", "C1"), ("GET", "C1"),
                                     ("POST", "IG/media_publish")])

    def test_fb_reel_flow(self):
        vid = self.img.parent / "v.mp4"
        vid.write_bytes(b"0123456789")
        c, s = make(FakeResp(body={"video_id": "V1", "upload_url": "https://rupload.example/v1"}),
                    FakeResp(body={"success": True}), FakeResp(body={"success": True}))
        c.fb_post_reel(vid, "desc")
        self.assertEqual([m for m, _, _ in s.calls], ["POST"] * 3)
        self.assertTrue(s.calls[0][1].endswith("PAGE/video_reels"))
        self.assertEqual(s.calls[0][2]["data"]["upload_phase"], "start")
        self.assertEqual(s.calls[1][1], "https://rupload.example/v1")
        self.assertEqual(s.calls[1][2]["headers"]["file_size"], "10")
        self.assertEqual(s.calls[1][2]["data"], b"0123456789")
        fin = s.calls[2][2]["data"]
        self.assertEqual((fin["upload_phase"], fin["video_id"], fin["video_state"]),
                         ("finish", "V1", "PUBLISHED"))

    def test_fb_reel_failures_not_retried_and_scrubbed(self):
        vid = self.img.parent / "v.mp4"
        vid.write_bytes(b"x")
        c, s = make(FakeResp(body={"video_id": "V1", "upload_url": "https://r/u"}),
                    requests.ConnectionError(f"boom {TOKEN}"))
        with self.assertRaises(MetaError) as cm:
            c.fb_post_reel(vid, "d")
        self.assertNotIn(TOKEN, str(cm.exception))
        self.assertEqual(len(s.calls), 2)  # no finish call, no retry

    def test_reel_videos_exist_and_valid(self):
        for f in content.Content().flyers:
            if f.video.exists():
                self.assertGreater(f.video.stat().st_size, 10_000)

    def test_non_transient_not_retried(self):
        c, s = make(FakeResp(400, {"error": {"message": "bad", "code": 100}}), FakeResp(body={}))
        with self.assertRaises(MetaError):
            c._get("PAGE")
        self.assertEqual(len(s.calls), 1)

    def test_token_never_in_errors_and_hints(self):
        c, _ = make(FakeResp(400, {"error": {"message": f"Invalid token {TOKEN}", "code": 190}}))
        with self.assertRaises(MetaError) as cm:
            c.fb_post_text("x")
        self.assertNotIn(TOKEN, str(cm.exception))
        self.assertIn("expired", str(cm.exception))
        c, _ = make(requests.ConnectionError(f"https://g?access_token={TOKEN}"))
        with self.assertRaises(MetaError) as cm:
            c.fb_post_text("x")
        self.assertNotIn(TOKEN, str(cm.exception))

    def test_hint_codes(self):
        for code in (10, 200, 4, 17, 32, 613, 368):
            c, _ = make(FakeResp(400, {"error": {"message": "m", "code": code}}))
            with self.assertRaises(MetaError) as cm:
                c.fb_post_text("x")
            self.assertIn("->", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
