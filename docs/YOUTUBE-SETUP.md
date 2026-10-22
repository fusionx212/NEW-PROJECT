# Publishing to YouTube (Little Lantern channel)

This guide connects the project to your YouTube channel so it can upload videos, set their thumbnails and schedule when they go public. You do the setup once. It takes about 20 minutes and needs no programming.

Everything runs on your own computer. Your Google login is saved in a private file on your computer, never in this project folder and never in git.

## Before you start: what YouTube will and won't reward

YouTube does not pay for "mass-produced" or "repetitive" content, meaning many near-identical videos made from one template. A channel that posted a birthday video for every name was terminated (see `docs/GIFT-SHOP.md`). So this tool is built to post **fewer, longer, varied** videos:

- About 3 or 4 videos a week, at the same evening time. Around half are nightly sky episodes; the rest are long sleep videos (an hour of nebula drift) or a story about our made-up character, Luna.
- It uploads at most 2 videos per run unless you ask for more.
- It warns you when two titles read almost the same, and when a sleep video is short.
- It refuses to upload a personalised story or keepsake that was made for a real customer. Only made-up characters go on YouTube, unless you have the family's written permission.

## Step 1: Create a Google Cloud project

1. Go to <https://console.cloud.google.com/> and sign in with the Google account that owns your YouTube channel.
2. At the top of the page, open the project picker and choose **New project**. Name it, for example, "Little Lantern uploads", and click **Create**.
3. Make sure the new project is selected in the project picker.

The project is free. Uploading through the API does not need a credit card.

## Step 2: Turn on the YouTube Data API v3

1. In the left menu, open **APIs & Services → Library**.
2. Search for **YouTube Data API v3**, open it, and click **Enable**.

## Step 3: Set up the consent screen

This is the "Allow access?" page you'll see when you log in. Google has renamed this area recently. It may be called **Google Auth Platform** (with sections called *Branding*, *Audience*, *Data access* and *Clients*) or **APIs & Services → OAuth consent screen**.

1. **App name:** "Little Lantern uploader". **Support email:** your email.
2. **Audience / user type:** choose **External**. (Internal is only offered to Google Workspace organisations.)
3. **Contact email:** your email. Agree to the policy and create.
4. **Test users:** add the Google account that owns the channel.
5. **Scopes / Data access:** you can leave this empty. The tool asks for one permission when you log in: `youtube.upload`, which lets it upload videos and set their thumbnails. It cannot delete videos or read your private data.

### Two Google rules that affect you

**1. Logins expire every 7 days while the app is in "Testing".** A new app starts in *Testing* status. In that status, Google cancels the saved login 7 days after you sign in. When that happens, the upload command will tell you to run `login` again. To stop this, go to the **Audience** (or consent screen) page and click **Publish app** to move it to *In production*, then run `login` once more. Google may show a warning page saying the app isn't verified. Because you are the only user, you can click **Advanced → Go to Little Lantern uploader** to continue. Google may ask you to complete verification later. For an app only you use, it usually doesn't.

**2. Uploads from an unaudited project are forced to "private".** Google's documentation says videos uploaded through the API from an *unverified* project created after 28 July 2020 are locked to **private**. Locked videos can't be scheduled to go public automatically. To lift the lock, fill in the YouTube API Services **audit and quota extension form**, linked from the YouTube Data API documentation. Google reviews the project against its terms of service. Until it passes:

- Videos upload as private, which is still useful: check each one in YouTube Studio and switch it to **Public** or **Scheduled** yourself. That is one click per video.
- Note in the form that this is a single-channel uploader for your own original content.

*(These rules come from Google's pages as of October 2026. Google changes them from time to time, so if something below doesn't match what you see, trust the console.)*

## Step 4: Create a Desktop OAuth client and download it

1. Go to **Clients** (or **APIs & Services → Credentials → Create credentials → OAuth client ID**).
2. **Application type: Desktop app.** This matters: a "Web application" client will not work. Name it "skysoftly".
3. Click **Create**, then **Download JSON**.
4. Move the downloaded file to:

   ```
   ~/.config/skysoftly/youtube_client_secret.json
   ```

   On Mac or Linux:

   ```bash
   mkdir -p ~/.config/skysoftly
   mv ~/Downloads/client_secret_*.json ~/.config/skysoftly/youtube_client_secret.json
   chmod 600 ~/.config/skysoftly/youtube_client_secret.json
   ```

Keep this file private. Don't email it, and don't put it in the project folder.

## Step 5: Your settings

Create the settings file once:

```bash
python -m skysoftly.youtube config --init
```

Then open `~/.config/skysoftly/youtube.json` in a text editor and set:

| Setting | What it does | Default |
|---|---|---|
| `shop_url` | Your shop link, added to every description | empty |
| `timezone` | Your time zone, e.g. `Europe/London`, `America/New_York` | `Europe/London` |
| `publish_time` | The evening time videos go public | `19:00` |
| `publish_days` | Days for new videos | Mon, Wed, Fri, Sun |
| `max_uploads_per_run` | A cap so the channel never floods | `2` |
| `made_for_kids` | Default per kind of video (see below) | nightly: yes, story: yes, sleep: no |
| `fictional_characters` | Made-up story characters allowed on YouTube | `["Luna"]` |
| `client_secret` | Where the Step 4 file lives | `~/.config/skysoftly/youtube_client_secret.json` |

Nightly episodes go public at `publish_time` in **the episode's own city**, on the evening the episode describes.

## Step 6: Log in

```bash
python -m skysoftly.youtube login
```

Your browser opens on Google's sign-in page. Choose the channel's account and allow access. When the page says "Signed in", go back to the terminal. The login is saved in `~/.config/skysoftly/youtube_token.json`, which only you can read, and it renews itself automatically. If the browser doesn't open, copy the link printed in the terminal into it. The sign-in finishes on your own computer (an address starting `http://127.0.0.1:`), so it must be the same machine.

`python -m skysoftly.youtube status` shows whether you are logged in. `logout` cancels the login.

## Step 7: Add videos to the queue

```bash
# A nightly episode (render it with: python -m skysoftly nightly --city Boulder --country US --start 2026-10-25 --days 1 --video)
python -m skysoftly.youtube queue add output/nightly/boulder/2026-10-25/episode.mp4

# A long sleep video at a time you choose
python -m skysoftly.youtube queue add output/sleep/violet-drift.mp4 --publish-at 2026-11-02T19:00

# A Luna story
python -m skysoftly.youtube queue add output/stories/luna/story.mp4

python -m skysoftly.youtube queue list
```

Each `queue add` writes the title, description, tags and a 1280×720 thumbnail (saved in `output/youtube/thumbnails/`). Before uploading, you can edit `output/youtube/queue.json` to change any of them. Adding the same video twice does nothing.

Options for `queue add`:

- `--publish-at 2026-11-02T19:00`: when it goes public, in your time zone. Without it, the video takes the next free evening slot.
- `--kids` / `--no-kids`: override the made-for-kids setting.
- `--privacy unlisted` or `--privacy public`: upload without a schedule.
- `--thumb-at 120`: take the thumbnail picture from 2 minutes in.

To give one video a hand-written title, description or tags, put a file next to it with the same name ending in `.youtube.json`, for example `violet-drift.youtube.json`, containing `{"title": "...", "body": "...", "tags": [...]}`.

## Step 8: Upload

```bash
python -m skysoftly.youtube upload --dry-run --next   # shows exactly what would be sent; nothing is uploaded
python -m skysoftly.youtube upload --next             # uploads the earliest queued video
python -m skysoftly.youtube upload --all-due          # uploads everything going public in the next 3 days
```

- If the connection drops halfway through a large file, run the same command again. It picks up where it stopped instead of starting over.
- A video that's already uploaded is never uploaded again.
- If YouTube refuses the thumbnail (custom thumbnails need a **verified channel**: verify with your phone number at <https://www.youtube.com/verify>), the video is still uploaded, and the next run tries only the thumbnail again.

## Planning a few weeks ahead

```bash
python -m skysoftly.youtube plan --weeks 4 --city Boulder            # 4 a week
python -m skysoftly.youtube plan --weeks 4 --city Boulder --per-week 3
```

This uploads nothing. It writes `output/youtube/plan.md`, a calendar that alternates nightly episodes and long videos. For each slot it shows what's ready to queue and what still needs rendering (with the command to render it), and it warns about titles that are too alike.

## Daily limits (quota)

Google gives each project a daily allowance of "quota units", by default 10,000 a day, reset at midnight Pacific time. Uploads have their own allowance under Google's newer rules. As of late 2026 that is roughly 100 uploads a day, but the exact numbers have changed several times. Check **APIs & Services → YouTube Data API v3 → Quotas** in the console. A thumbnail costs about 50 units. At 3 or 4 videos a week you won't come close. YouTube can also limit how many videos a channel uploads in a day, whatever the quota.

## Telling viewers the voice is synthetic

The narrator is a computer-generated voice, so the tool does two things for every video:

1. **The description says so**, in a line near the end: "the narration is a synthetic (computer-generated) voice". This line is never cut, even if a description is long.
2. **It ticks YouTube's "altered or synthetic content" box** (the API field `containsSyntheticMedia`). YouTube then shows an "Altered or synthetic content" label on the video.

YouTube's rule strictly covers *realistic* content that viewers could mistake for real people or events. A calm narrator voice over a clearly animated sky may not strictly need the label, but disclosure is the honest default, and it matches what Etsy requires of the shop. You can turn it off with `"contains_synthetic_media": false` in the settings, but the description line stays.

## "Made for kids": what it changes

US law (COPPA) requires you to tell YouTube whether each video is **made for kids**, meaning children are its main audience. The tool sends this for every upload (`selfDeclaredMadeForKids`).

| Video | Default | Why |
|---|---|---|
| Luna bedtime stories | **Made for kids** | Clearly aimed at children |
| Nightly sky episodes | **Made for kids** | The script speaks to a child ("breathe out like you're cooling a cup of cocoa") |
| Long nebula sleep videos | **Not made for kids** | Aimed at adults falling asleep or studying |

When a video is marked made for kids, YouTube:

- shows only non-personalised ads, so earnings per view are usually much lower;
- turns off comments, the mini-player, notifications to subscribers (the bell), "save to playlist" and stories;
- turns off **end screens and cards**, so you can't link to the shop from inside the video. The shop link in the description still works, but YouTube may hide clickable links in kids' video descriptions; check after the first upload.

Getting this wrong is serious. If YouTube decides a video is for kids, it can override your setting, and the FTC can fine channels that mark children's content as "not for kids". If unsure, answer honestly about who the video is for, not about which answer earns more. Use `--kids` or `--no-kids` to change a single video.

## Privacy and safety

- Never upload a customer's personalised story or keepsake without their written permission. The tool blocks videos from `output/keepsakes/`, and stories whose hero isn't on the `fictional_characters` list. `--confirm-fictional` overrides this; use it only when it's true.
- Your login, the client file and in-progress upload links are kept in `~/.config/skysoftly/` with private permissions. Never copy them into the project or share them.
- `output/youtube/queue.json` holds only titles, descriptions, dates and video ids. You may still prefer not to commit it.

## If something goes wrong

| Message | What to do |
|---|---|
| `invalid_grant` / "login has expired" | Run `login` again. If it happens weekly, publish the app (Step 3). |
| "Create a 'Desktop app' OAuth client" | You downloaded a Web client. Make a Desktop one (Step 4). |
| `quotaExceeded` | Wait until after midnight Pacific time. |
| `uploadLimitExceeded` | The channel's own daily limit; try tomorrow. |
| Uploads appear as private and won't schedule | The project hasn't passed Google's audit yet (Step 3, rule 2). Publish them by hand in YouTube Studio. |
| Thumbnail not set | Verify the channel by phone, then run `upload --next` again. |
