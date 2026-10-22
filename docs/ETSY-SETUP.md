# Etsy orders, almost on autopilot

This guide sets up a small program that watches your Etsy shop. When someone buys a story pack, it reads their answers, builds the pack, and tells you it's ready. You do one short step per order.

You only do steps 1 to 4 once.

## 1. Create an Etsy developer app

1. Sign in to Etsy with your shop account.
2. Go to **etsy.com/developers/your-apps**.
3. Click **Create a new app**. Give it a name, such as "Skysoftly orders". Say it is for your own shop.
4. Wait for Etsy to approve it. This can take a few days.
5. Open the app. Write down two things:
   - the **Keystring** (it looks like a long jumble of letters and numbers)
   - the **Shared secret**

Treat the shared secret like a password. Never email it, post it, or put it in this project's files.

## 2. Add the redirect address

Etsy sends you back to your own computer after you sign in. It needs to know the address.

1. In your app's settings, find **Callback URLs** (also called redirect URIs).
2. Add exactly this, with no slash at the end:

   ```
   http://localhost:3003/callback
   ```

3. Save.

The address must match exactly. If you use a different one, set it in step 3 as well.

## 3. Save your keys on this computer

Make a settings file that only you can read. In a terminal:

```
mkdir -p ~/.config/skysoftly
nano ~/.config/skysoftly/etsy.json
```

Paste this in, with your own values:

```json
{
  "keystring": "your keystring here",
  "shared_secret": "your shared secret here",
  "redirect_uri": "http://localhost:3003/callback"
}
```

Save, then lock the file:

```
chmod 600 ~/.config/skysoftly/etsy.json
```

You can use environment variables instead: `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET`, `ETSY_REDIRECT_URI` and `ETSY_SHOP_ID`. They win over the file.

## 4. Sign in once

```
python -m skysoftly.etsy login
```

1. Your browser opens on Etsy.
2. Check it asks only to **see your shop's orders** and **see your shop**. Click **Allow**.
3. The browser shows "Signed in to Etsy". Go back to the terminal.

The terminal shows your shop id. Add it to your settings file to save a step on every check:

```json
  "shop_id": 12345678
```

The sign-in is saved in `~/.config/skysoftly/etsy_token.json`. Only you can read it. It renews itself every hour while the watcher runs. If the watcher is off for more than about 90 days, run `login` again.

**On a computer without a browser?** Run `python -m skysoftly.etsy login --paste`. Open the link it prints on any device. After you click Allow, the page won't load. That's expected. Copy the whole address from the address bar and paste it into the terminal.

## 5. Try it without Etsy first

This uses made-up orders, so nothing touches your shop:

```
python -m skysoftly.etsy fetch --dry-run tests/fixtures/etsy_receipts.json --no-audio
```

Look in `output/orders-dry-run/`. You should see three ready orders and two in `needs-review`.

## 6. Start the watcher

```
python -m skysoftly.etsy watch
```

It checks Etsy every 5 minutes. Leave the terminal open. Press Ctrl+C to stop.

Useful options:

| Option | What it does |
|---|---|
| `--video` | Also make the nebula video. Slow: about an hour per order. |
| `--every 10` | Check every 10 minutes instead of 5. |
| `--once` | Check once, then stop. `fetch` does the same. |
| `--since 30` | Look back 30 days instead of 14. |

The first time, it picks up every paid order from the last 14 days that isn't marked complete yet. If you have already sent some of those by hand, mark them complete on Etsy first.

## 7. Get an email when a pack is ready (optional)

Set these before you start the watcher. Any email account that allows SMTP works.

```
export SMTP_HOST=smtp.example.com
export SMTP_PORT=587
export SMTP_USER=you@example.com
export SMTP_PASSWORD='an app password'
export SMTP_TO=you@example.com
```

For Gmail, make an "app password" in your Google account and use that, not your normal password.

## What the folders mean

Everything lands in `output/orders/`.

| Folder or file | What it is |
|---|---|
| `output/orders/<order number>/` | A finished order. |
| `.../READY.txt` | What to upload, and your checklist. Start here. |
| `.../order.json` | The buyer's answers and how they were read. |
| `.../pack/` | The gift files. |
| `output/orders/needs-review/<order number>/` | An order the program wouldn't guess at. |
| `.../REASON.txt` | Why it stopped, the buyer's words, and a ready-made command to fix and build it. |
| `output/orders/processed.json` | The orders already handled, so nothing is built twice. |

These folders hold buyers' names and messages. Don't share them, and don't add them to git.

## The one manual step per order

Open `READY.txt` and work down the checklist:

1. Listen to the first minute of `story.mp3`. Is the name said right?
2. Flick through `storybook.pdf`. Is the name spelled right?
3. In Etsy, go to **Shop Manager > Orders**, open the order, and upload the files listed.
4. If there's a video, put `story.mp4` in Google Drive or Dropbox and paste the share link in the order message.
5. Mark the order complete.

About a minute per order.

## When an order lands in needs-review

This happens when an answer is missing, unclear, or could mean two things. Examples: no pronoun, "4 or 5" for the age, a town that exists in two countries, or 03/04/2023 from a US buyer.

1. Open `REASON.txt`.
2. If you need to, message the buyer on Etsy.
3. Fix the command at the bottom of `REASON.txt` and run it.
4. Do the manual step above.

To make the watcher try an order again from the start:

```
python -m skysoftly.etsy forget <order number>
```

## Check how an answer will be read

Paste a buyer's text to see what the program makes of it:

```
python -m skysoftly.etsy parse "1) Isla 2) she 3) 5 4) bunny 5) purple 6) 2 May 2021, Leeds UK 7) Grandma 8) Happy birthday!"
```

## Tips for clean orders

- Keep the numbered list in the personalisation box. Numbered answers are read most reliably.
- Etsy also lets a listing ask several separate personalisation questions. The program reads those too.
- Dates like 02/05/2021 are read the UK way: 2 May 2021.
- Small towns may not be in the offline town list. The order then goes to review. Use the nearest big town.

## If something goes wrong

| Message | What to do |
|---|---|
| "keystring and shared secret are missing" | Check step 3. |
| "Not signed in to Etsy" or "sign in again" | Run `python -m skysoftly.etsy login`. |
| "Etsy answered 429" | Etsy wants you to slow down. The watcher waits and tries again by itself. |
| The browser says the redirect URI is wrong | The address in step 2 must match exactly, including `http`, the port and `/callback`. |
| "Address already in use" during login | Something else is using port 3003. Close it, or use `--paste`. |
