# Lunch Break Lifts: automated Instagram page

Fully automated content pipeline running free on GitHub Actions:

- **Every Sunday:** Claude writes 14 original fitness posts (short, punchy slides; captions open with a phrase people search for). Each is rendered as carousel
  slides, a vertical Reel video, and a Story image, then queued.
- **Twice a day (lunch ~12:15 and evening ~6:30, Denver):** the next post goes out through the official Instagram API.
  Every post goes out as a Reel (adjustable). Reels use a slow zoom on every slide and a short hook, and get a trending, clean song picked fresh each day
  (Instagram Audio API, never repeated within 3 weeks). Each post is also shared to the
  Instagram Story, Reels are copied to the Lunch Break Lifts Facebook Page, and a short
  version goes to Threads. Carousel slides get alt text.
- **Morning, and about 30 and 90 minutes after each post:** Claude replies to normal comments in the page's voice. Brand offers
  and injury/medical questions are left for you.
- **Every night (~8pm):** a summary arrives as a GitHub notification and email:
  followers, today's post stats, comments that need you, and key warnings. Sundays add a
  week in review and an optional "boost pick".
- **Free plan by DM:** anyone who comments **LIFT** gets the free 30-Day Lunch Break Challenge
  (`plan/index.html`, served by GitHub Pages) sent to their DMs, plus a public "check your DMs" reply.
  Captions invite people to comment the keyword.
- **30-Day Lunch Break Challenge:** from the start date in `config.json`, the lunch post each day
  is "Day N/30", written from `challenge.json` (edit `challenge.py`, then run it to rebuild both).
- **Workout footage:** with `PEXELS_API_KEY` set, Reels use real stock workout clips (Pexels, free
  license) behind the text, matched to the post's topic. Without it, the plain dark style.
- **Best posting times:** the posting job checks hourly and posts at the slots in `config.json`
  (`post_slots`, default 12:00 and 18:00). Once the account has 100+ followers, the Sunday job reads
  when followers are online and saves better slots to `best_times.json` automatically.
- **First comment:** right after each post, the robot comments a "Comment LIFT for the plan" invite.
- **Re-post winners:** Reels that beat the page average get re-posted after 30 days with a new hook and song (1 a week).
- **Replying to @you:** real follower questions from comments become posts that tag them.
- **Every Wednesday:** the Instagram and Threads keys are renewed automatically.

Workouts are built from real exercises in the open
[Free Exercise DB](https://github.com/yuhonas/free-exercise-db) (public domain, 870+
exercises). Each week a fresh sample, spread across muscle groups, is pulled
automatically and handed to Claude, and any post naming an exercise that isn't in the
database is thrown out. Only the facts are used (names, equipment, muscles, level);
Claude writes all instructions in its own words, and the dataset's photos aren't used
since their origin is unclear. Change `equipment` and `levels` in `config.json` to
widen or narrow what's allowed.

Your computer doesn't need to be on. Cost: a few cents a week in Claude API usage.

---

## One-time setup (about 30 minutes)

Steps needing your logins are yours. Everything after is automatic.

### 1. Instagram account (done)
@lunch_breaklifts, Creator account, display name "Lunch Break Lifts".

### 2. Meta developer app
1. Go to https://developers.facebook.com and register as a developer. Meta may ask
   you to log in with a Facebook account for this. The developer account is private
   and isn't shown on the Instagram page.
2. My Apps > **Create App**. Name it anything (e.g. "LBL Publisher"). When asked for a
   use case, choose the one for managing messages and content on **Instagram**.
3. In the app, open **Instagram > API setup with Instagram login**.
4. Under **Generate access tokens**, click **Add account**, log in as
   **lunch_breaklifts**, and approve. Then click **Generate token** next to it and copy it.
5. The app can stay in Development mode. Since you own both the app and the
   Instagram account, no app review is needed to post to it.

### 3. Check the token and get your account ID
On your computer, in this folder:
```
pip install requests
python get_token.py
```
Paste the token from step 2.4. It prints `IG_USER_ID`.

### 4. Anthropic API key
Create a key at https://console.anthropic.com and add a few dollars of credit.

### 5. GitHub repo (account: lunchbreaklifts)
1. Create a **public** repository named `lunch-break-lifts` and upload this whole folder,
   including the hidden `.github` folder. Public is required so Instagram can fetch the
   slide images; it only contains post content.
2. Create a key that lets the robot renew the Instagram key:
   GitHub > Settings > Developer settings > Personal access tokens > **Fine-grained
   tokens** > Generate new token. Repository access: only `lunch-break-lifts`.
   Permissions: **Secrets: Read and write**. Expiration: the longest offered (set a
   calendar reminder to replace it before it expires). Copy it.
3. Repo > Settings > Secrets and variables > Actions > **New repository secret**. Add:
   - `ANTHROPIC_API_KEY`: from step 4
   - `IG_USER_ID`: from step 3
   - `IG_ACCESS_TOKEN`: from step 2.4
   - `GH_SECRETS_TOKEN`: from step 5.2
4. Repo > Settings > Actions > General > Workflow permissions > **Read and write**.

### 6. Extra keys (music, Facebook, Threads)
- `FB_PAGE_TOKEN`: a **never-expiring user key** from the Meta Access Token Debugger
  (Extend Access Token), with pages_show_list, pages_read_engagement, pages_manage_posts,
  instagram_basic, instagram_content_publish, business_management. The robot gets the
  Page key from it on each run. Don't copy keys out of the Graph API Explorer; it swaps
  in a short key that expires in an hour.
- `THREADS_TOKEN`: from the app's Threads use case > Settings > User Token Generator
  (lunch_breaklifts must be a Threads Tester).
- Any of these can be left out; that feature is just skipped.

### 7. Start it
Actions tab: run **Weekly content**, then **Daily post** to publish the first one.
From then on it runs itself.

If a renewal is ever missed and the key expires, generate a new token (step 2.4) and
replace the `IG_ACCESS_TOKEN` secret.

**Check keys:** Actions > Check keys > Run workflow tests every key (and that the
Facebook key never expires) without posting anything.

---

## Controls (edit `config.json` on GitHub)

| Setting | What it does |
|---|---|
| `"auto_approve": true` | Posts go straight into the queue. Set `false` to review: new posts land as `draft` in `posts.csv`; change to `approved` to queue them. |
| `"publishing_enabled": false` | Pauses all posting instantly. |
| `"posts_per_batch"` | Posts generated each Sunday (14 = two a day). |
| `"posts_per_day": 2` | Max posts per day (the evening slot skips itself if set to 1). |
| `"reel_cycle": 1` | Every post is a Reel. Set `3` for 2 Reels then 1 carousel, `2` to alternate. |
| `"reel_music"`, `"facebook_reels"`, `"threads"`, `"stories"` | Set any to `false` to turn that feature off. |
| `"lead_magnet"` | Keyword, plan link, and on/off for the comment-for-the-plan DMs. |
| `"challenge"` | Start date (a Monday) and on/off for the Day N/30 series. |
| `"auto_reply_comments": false` | Stops comment replies (the nightly summary still comes). |

`posts.csv` is the full record: every post, its status, and when it went live.
To pull a queued post, change its status to `skip` (anything other than `rendered`).

Note: GitHub pauses scheduled workflows in repos with no activity for 60 days. The bot's
own commits count as activity, so this normally isn't an issue.

---

## Keeping it legal and above board

- **Original content only.** Claude writes original posts. Don't add other creators'
  content, photos or videos.
- **Sponsored posts are posted by you, by hand.** The bot never posts ads. When a brand
  pays you (money or free product), post it yourself in the Instagram app with the
  **Paid partnership** label on and `#ad` near the start of the caption. The FTC
  requires clear disclosure.
- **Only promote things you'd stand behind.** Skip supplements with health claims,
  "get rich" offers, and anything you can't verify.
- **No bots for engagement.** Automated following, liking or commenting breaks
  Instagram's terms. Posting through the official API, as this does, is allowed.
- **Check your employer's outside-work policy.** Many public employers require you to
  report or get approval for a side business. Do it on your own time and equipment.

## Taxes

Not tax advice; confirm with a tax professional. General points:

- Sponsorship income is self-employment income, reported on Schedule C with
  self-employment tax, whether or not a brand sends you a 1099.
- Free products received in exchange for posts generally count as income at fair
  market value.
- Business expenses (Claude API, any paid tools, a share of your phone) can usually be
  deducted. Keep receipts.
- With steady income you may owe quarterly estimated taxes (federal and Colorado).
- Record every payment and expense in `income_log.csv` as it happens. It's excluded
  from the public repo by `.gitignore`, so keep it on your computer.
  A separate bank account for the page makes this much easier.

## Running locally (optional)

```
python generate_ideas.py
python render_slides.py
python publish.py --dry-run
```
`publish.py` without `--dry-run` also works locally if you set `IG_USER_ID`,
`IG_ACCESS_TOKEN`, and `image_base_url` in `config.json` (e.g.
`https://raw.githubusercontent.com/<you>/lunch-break-lifts/main`).
