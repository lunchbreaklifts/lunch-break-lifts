# Lunch Break Lifts: automated Instagram page

Fully automated content pipeline running free on GitHub Actions:

- **Every Sunday:** Claude writes 7 original fitness carousel posts, and the slides are
  rendered and queued.
- **Every day at lunchtime:** the next post in the queue is published to Instagram
  through the official Instagram API (Instagram Login; no Facebook Page needed).
- **Every Wednesday:** the Instagram key is renewed automatically so it never expires.

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

### 6. Start it
Actions tab: run **Weekly content**, then **Daily post** to publish the first one.
From then on it runs itself.

If a renewal is ever missed and the key expires, generate a new token (step 2.4) and
replace the `IG_ACCESS_TOKEN` secret.

---

## Controls (edit `config.json` on GitHub)

| Setting | What it does |
|---|---|
| `"auto_approve": true` | Posts go straight into the queue. Set `false` to review: new posts land as `draft` in `posts.csv`; change to `approved` to queue them. |
| `"publishing_enabled": false` | Pauses all posting instantly. |
| `"posts_per_batch"` | Posts generated each Sunday (7 = one a day). |

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
