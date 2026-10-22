# Running it on your own computer (VS Code)

Secrets stay on your computer in `~/.config/skysoftly/` and never go in this repo
(`.gitignore` also blocks them).

## 1. Get the code and tools

```bash
git clone https://github.com/fusionx212/Littlelantern.git
cd Littlelantern
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
bash tools/fetch_models.sh          # the free Kokoro voice model, about 340 MB
```

You also need `ffmpeg` (macOS: `brew install ffmpeg`, Ubuntu: `sudo apt install ffmpeg`,
Windows: `winget install ffmpeg`).

Check it works: `python -m pytest -q`

## 2. Etsy

Create `~/.config/skysoftly/etsy.json` (paste your own values from the Etsy developer page):

```json
{
  "keystring": "YOUR_KEYSTRING",
  "shared_secret": "YOUR_SHARED_SECRET",
  "redirect_uri": "http://localhost:3003/callback"
}
```

Then lock it down and sign in once:

```bash
chmod 600 ~/.config/skysoftly/etsy.json
python -m skysoftly.etsy login      # opens Etsy in your browser; click Allow
python -m skysoftly.etsy whoami     # shows your shop id
python -m skysoftly.etsy watch      # checks for new orders and builds each pack
```

In the Etsy app settings, the callback URL must be exactly `http://localhost:3003/callback`.
Full details: `docs/ETSY-SETUP.md`.

## 3. YouTube (Little Lantern)

Put the OAuth client file from Google Cloud at `~/.config/skysoftly/youtube_client_secret.json`, then:

```bash
chmod 600 ~/.config/skysoftly/youtube_client_secret.json
python -m skysoftly.youtube config   # writes a starter config
python -m skysoftly.youtube login    # opens Google in your browser
python -m skysoftly.youtube status   # confirms the login (never prints secrets)
python -m skysoftly.youtube plan --weeks 2 --city London
```

Full details: `docs/YOUTUBE-SETUP.md`. YouTube only ever gets fictional heroes. The uploader
refuses anything from customer order folders.

## 4. Switch on the autopilot (runs by itself)

```bash
python -m skysoftly.autopilot config     # then set your city, country and timezone in ~/.config/skysoftly/autopilot.json
python -m skysoftly.autopilot once       # try one round now and watch what it does
python -m skysoftly.autopilot install    # from now on it runs every 10 minutes, even after a restart
python -m skysoftly.autopilot status     # what happened recently
```

Every 10 minutes it checks Etsy for new orders and builds each gift pack. Once a day, in the quiet hours,
it plans the next two weeks of Little Lantern, renders what's missing for the coming week, queues it and
uploads what's due (private, publishing itself at the scheduled time). The log is in `output/autopilot.log`.

It uses Task Scheduler on Windows, launchd on a Mac and cron on Linux. The computer has to be on and awake
for it to run, so set it not to sleep (or leave it plugged in with sleep off). To stop it:
`python -m skysoftly.autopilot uninstall`.
