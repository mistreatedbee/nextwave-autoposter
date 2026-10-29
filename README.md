# NextWave Auto-Poster

Posts one NextWave Digital Solutions flyer a day to a Facebook Page (feed + story) and Instagram (feed + story), a text tip to the Page, and emails you a "group pack" to paste into Facebook groups by hand. Runs free on GitHub Actions using the Meta Graph API (`v26.0`, override with `GRAPH_API_VERSION`).

**Not automated on purpose:** Facebook Groups and WhatsApp have no official posting API and automating them breaks Meta's rules. That is why you get the group pack email instead.

## Schedule (South Africa time, UTC+2)

| Time | What |
|---|---|
| ~08:07 | Group pack email, then flyer → Facebook feed, Facebook story, Instagram feed, Instagram story |
| ~13:13 | Text-only tip → Facebook Page (Instagram has no text-only posts) |

Rotation is stateless: with the SAST date ordinal, `flyer = ordinal % 5` and `caption variant = ordinal // 5 % 3`. Text tips cycle through 14 in order. Check any day with `python3 post.py flyer --dry-run --date 2026-12-01`.

## Setup (macOS, beginner)

### 1. Install and prepare
```bash
cd ~/Desktop/autoposter
python3 -m venv .venv
source .venv/bin/activate          # run this in every new Terminal window
pip3 install -r requirements.txt
```

### 2. Flyers → images
The five PNGs are already in `flyers/`. If you change a flyer, re-export it (keep the file name) and run:
```bash
python3 prepare_images.py
```
This writes Instagram-ready JPEGs to `images/feed/` (1080×1350) and `images/story/` (1080×1920). **Commit the `images/` folder**: Instagram downloads the images from GitHub.

### 3. Create the Meta app
1. Go to <https://developers.facebook.com> → **My Apps → Create App**, choose the **Business** type (or "Other" → Business).
2. Note the **App ID** and **App Secret** (App settings → Basic).
3. Keep the app in **Development mode**. No App Review is needed for your own Page and Instagram.
4. Your Instagram must be a **Business or Creator** account **linked to your Facebook Page** (Instagram → Settings → Account type, then Page settings → Linked accounts).
5. Open **Tools → Graph API Explorer**, select your app, **User token**, and add these permissions: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`. Click **Generate Access Token**, tick your Page (and Instagram) in the dialog, and copy the token.

### 4. Get a permanent Page token
```bash
python3 get_tokens.py
```
Paste the App ID, App Secret and the short-lived token (secrets are hidden). It writes `META_PAGE_ID`, `META_PAGE_TOKEN` and `META_IG_USER_ID` to `.env` (git-ignored) and prints only masked values. Page tokens made from a long-lived user token do not expire.

### 5. Test the connection (posts nothing)
```bash
python3 post.py validate
python3 post.py check
python3 post.py flyer --dry-run
```

### 6. Optional: email setup
Turn on 2-step verification on your Google account, then create an app password at <https://myaccount.google.com/apppasswords>. Put `SMTP_USER` (your Gmail), `SMTP_APP_PASSWORD` and optionally `NOTIFY_EMAIL` in `.env`. Test with `python3 post.py pack --dry-run`. Without SMTP settings, pack mode skips quietly.

### 7. Put it on GitHub (public repo)
The repo must be **public** so Instagram can fetch `raw.githubusercontent.com` image URLs. That is safe because `.env` is git-ignored and secrets live in GitHub Actions secrets.
```bash
git init -b main
git status          # confirm .env is NOT listed
git add .
git commit -m "NextWave auto-poster"
```
Create an empty **public** repo on github.com, then:
```bash
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```
Add secrets in **Repo → Settings → Secrets and variables → Actions → New repository secret**: `META_PAGE_ID`, `META_PAGE_TOKEN`, `META_IG_USER_ID`, and (for email) `SMTP_USER`, `SMTP_APP_PASSWORD`, `NOTIFY_EMAIL`. Copy the values from `.env`.

### 8. Run the workflow
**Actions → Daily post → Run workflow.**
1. Mode `check`, dry run on: confirms the secrets work.
2. Mode `flyer`, dry run **on**: look at the log.
3. Mode `flyer`, dry run **off**: a real post to all four places. Look at your Page and Instagram.

After that the schedules run by themselves.

## Good to know
- GitHub **pauses scheduled workflows after ~60 days without repo activity**. Push a small commit (or run the workflow manually) now and then; GitHub emails you before it pauses.
- Schedules can start a few minutes (sometimes more) late.
- Instagram allows about **100 API-published posts per 24 hours**; this uses 2 a day.
- One failed step never stops the others; the run turns red and shows an `::error` annotation.
- Publishing calls are never retried, so a hiccup can't create double posts. If one platform fails, re-run with e.g. `--only instagram_feed` (manual run locally: `python3 post.py flyer --only instagram_feed`).

## Commands
```
python3 post.py validate | check | flyer | text | pack
  --dry-run   --flyer <id>   --only facebook_feed,facebook_story,instagram_feed,instagram_story   --date YYYY-MM-DD
python3 -m unittest discover -s tests
```
Flyer ids: `web-design-packages`, `ecommerce-store`, `ai-automation`, `landing-page`, `mobile-app`.
Image URLs default to `https://raw.githubusercontent.com/$GITHUB_REPOSITORY/$GITHUB_REF_NAME/images/<kind>/<id>.jpg`; set `IMAGE_BASE_URL` (the `.../images` folder) to override for local runs.

Edit wording in `captions.json` and `text_posts.json` (placeholders `{site}`, `{phone}`, `{email}`), then run `python3 post.py validate`. Limits enforced: Instagram ≤ 12 hashtags used (≤ 2200 characters, never more than 30), Facebook ≤ 4 hashtags.

## Troubleshooting
| Code / message | Meaning and fix |
|---|---|
| **190** | Token invalid/expired (or password changed). Run `get_tokens.py` again and update the `META_PAGE_TOKEN` secret. |
| **10 / 200** | Missing permission. Regenerate the Explorer token with all five permissions and make sure your Page is ticked, then re-run `get_tokens.py`. |
| **4 / 17 / 32 / 613** | Rate limit. Wait and retry later. |
| **368** | Meta temporarily blocked the action (looks like spam). Pause posting, check Page quality in Meta Business Suite. |
| Instagram "could not process image" / `ERROR` | The image URL must be public. Did you push `images/`? Is the repo public? Open the `raw.githubusercontent.com` URL in a private window. |
| `No Pages found` in get_tokens | You didn't tick the Page in the Explorer permission dialog, or `pages_show_list` is missing. |
| `Instagram: NOT LINKED` | Convert Instagram to Business/Creator and link it to the Page, then re-run `get_tokens.py`. |
| Email not arriving | Check `SMTP_*` secrets and that you used a Gmail **app password**, not your normal password. Look in spam. |

## Safety
Never commit `.env` or paste tokens in chats or issues. If a token leaks, reset the App Secret in the Meta dashboard and re-run `get_tokens.py`.
