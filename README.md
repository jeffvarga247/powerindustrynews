# Electrical Power Industry Intelligence Site — Setup Guide

This folder contains a small program that automatically pulls news stories
from RSS feeds, sorts them into your six editorial categories (Failures,
Protection, Growth, Standards, Insurance, Installation and Upgrades), and
builds a simple website for you. No coding knowledge required to run it —
just follow the steps below.

## What's in this folder

- `aggregate.py` — the program itself (you won't need to edit this)
- `feeds_config.json` — **the file you'll edit most.** This is where you
  list which news sources go in which category. Pre-filled with real,
  verified electrical-power-industry sources to start you off (see notes
  below on what's confirmed vs. what you should add).
- `check_feeds.py` — run this any time you add or change a feed URL, to
  confirm it's alive before relying on it.
- `site/` — created automatically the first time you run it. This is your
  actual website (open `site/index.html` in a browser to view it).
- `story_store.json` — created automatically. This is the program's memory
  of stories it has already found, so your site keeps growing instead of
  losing old stories.

## Important notes on this specific build

**On the categories themselves:** unlike generic news topics ("Tech",
"Sports"), your six categories (Failures, Protection, Growth, Standards,
Insurance, Installation/Upgrades) don't map cleanly onto single RSS feeds
— there's no feed literally called "Transformer Failures." Right now,
several categories share the same source feeds (Utility Dive, POWER
Magazine, IEEE Spectrum Energy) and the program just files every story
from those feeds into each category you've assigned them to. That means
you'll see some overlap, and stories won't always match the category
perfectly. Two ways to improve this over time:
1. Find and add more specific feeds per category (see below)
2. Add AI-based classification (send each headline to Claude and ask it
   to pick the best category) instead of relying on source-based sorting
   — I can build that next if you want.

**On the "Insurance" category:** I could not find a reliable, focused RSS
feed for "is this facility insurable" content — that's a niche that trade
press mostly doesn't cover as a dedicated feed. This is honestly a strong
sign that Insurance should be original editorial content (interviews,
Sentry-authored analysis) rather than aggregated news. It's left empty in
`feeds_config.json` for now; running `check_feeds.py` will remind you.

**On feed reliability generally:** I verified `powermag.com/feed`,
`utilitydive.com/feeds/news/`, and `renewableenergyworld.com/feed` are
live and returning stories as of this writing. The IEEE Spectrum energy
feed follows a confirmed URL pattern used by their other topic feeds but
I couldn't verify it returns entries directly — run `check_feeds.py`
first thing to confirm, and swap it out if it's empty.

---

## Step 1: Install Python

If you don't already have Python installed:
1. Go to https://www.python.org/downloads/
2. Download and install the latest version for your operating system.
3. On Windows, make sure to check the box that says "Add Python to PATH"
   during installation.

To check it worked, open:
- **Windows:** Command Prompt (search "cmd" in the Start menu)
- **Mac:** Terminal (search "Terminal" in Spotlight)

and type:
```
python3 --version
```
You should see something like `Python 3.11.4`. (On Windows it may just be `python --version`.)

## Step 2: Install the one required library

In the same Command Prompt / Terminal window, run:
```
pip install feedparser
```
(On some systems it's `pip3 install feedparser`.)

## Step 3: Put this folder somewhere easy to find

Save this whole `news-aggregator` folder somewhere like your Desktop.

## Step 4: Choose your news sources

Open `feeds_config.json` in any text editor (Notepad, TextEdit, VS Code, etc).
It looks like this:

```json
{
  "Technology": [
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml"
  ],
  "Business": [
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"
  ]
}
```

Each key (like `"Technology"`) becomes a category/page on your site.
Each item under it is an RSS feed URL for that category.

**How to find RSS feed URLs for a site you like:** search
`"[site name] RSS feed"` — most major news outlets publish one, often
listed at the bottom of their homepage or at a URL like `sitename.com/rss`.

You can add as many categories and feeds as you want. Just keep the same
`{ "Category": ["url1", "url2"] }` format, with commas between entries.

## Step 4.5: Check your feeds before relying on them

Before running the full site build, run:
```
python3 check_feeds.py
```
This tells you which feeds are alive and returning stories (`OK`), which
are broken or empty (`EMPTY`/`FAILED`), and which categories still need
a source added. Fix anything flagged before moving on.

## Step 5: Run it

In Command Prompt / Terminal, navigate to the folder and run the script:

```
cd path/to/news-aggregator
python3 aggregate.py
```

You'll see it print progress as it fetches each category. When it's done,
open `site/index.html` in your web browser (just double-click the file)
to see your site.

## Step 6: Run it again later to get fresh stories

Every time you run `python3 aggregate.py`, it re-checks the feeds, adds
any new stories, and updates the site — while keeping older stories too.
Nothing gets deleted; the oldest stories are just trimmed off once a
category has more than 200 saved.

## Step 7 (optional): Make it run automatically on a schedule

Right now you have to run the command yourself. To make it fully hands-off:

### On Mac/Linux (using cron)
1. In Terminal, run: `crontab -e`
2. Add a line like this (runs every hour), replacing the path with your actual folder path:
   ```
   0 * * * * cd /full/path/to/news-aggregator && /usr/bin/python3 aggregate.py
   ```
3. Save and exit. It will now run every hour, even if you're not watching.

### On Windows (using Task Scheduler)
1. Search "Task Scheduler" in the Start menu and open it.
2. Click "Create Basic Task," name it "News Aggregator," and choose how
   often to run it (e.g., hourly).
3. For the action, choose "Start a program," and point it to `python.exe`,
   with the argument set to the full path of `aggregate.py`.

### Fully automated + hosted online (no computer needs to stay on)
This local setup only updates the site while your computer runs it. To have
a real live website that updates itself in the cloud:
1. Put this folder in a GitHub repository.
2. Use **GitHub Actions** (a free scheduler GitHub provides) to run
   `aggregate.py` on a timer (e.g., every hour) and commit the updated
   `site/` folder back to the repo.
3. Turn on **GitHub Pages** for that repo, pointed at the `site/` folder.

That combination gives you a real URL (like `yourname.github.io/news`)
that updates itself with zero ongoing effort from you. If you'd like, I can
write the GitHub Actions configuration file for this next — just ask.

---

## Troubleshooting

- **"command not found: python3"** — Python isn't installed or isn't on
  your PATH. Reinstall it and make sure to check "Add to PATH" (Windows).
- **A category shows "No new stories yet"** — either the feed URL is
  wrong/broken, or that source hasn't published anything new. Try opening
  the feed URL directly in a browser to check it loads.
- **You want to change how many stories show per category** — open
  `aggregate.py` and change the number next to `MAX_STORIES_PER_CATEGORY`
  near the top of the file.
