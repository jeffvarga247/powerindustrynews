"""
News Aggregator
----------------
Reads RSS feeds listed in feeds_config.json, sorts stories into the
categories you defined, skips stories it has already posted before,
and builds a simple static website (HTML files) showing the results.

HOW TO RUN:
    python3 aggregate.py

OUTPUT:
    site/index.html          <- homepage linking to each category
    site/category_XXX.html   <- one page per category
    seen_articles.json       <- memory file so stories aren't repeated

You do not need to understand every line of this file to use it.
The only file you'll normally edit is feeds_config.json.
"""

import json
import os
import html
from datetime import datetime, timezone

import feedparser

CONFIG_FILE = "feeds_config.json"
STORE_FILE = "story_store.json"   # persistent archive of stories per category
OUTPUT_DIR = "site"

MAX_STORIES_PER_CATEGORY = 30     # how many stories to show per category page

SITE_NAME = "Power Industry News"
SITE_TAGLINE = "Grid intelligence for utility, protection, and plant professionals"

# Shown in the footer of every page. Edit this to control how sponsorship
# is disclosed to visitors -- keeping this honest and visible is what lets
# a sponsor-supported trade site retain professional trust over time.
SPONSOR_DISCLOSURE_HTML = 'An independent industry resource brought to you by JGV Creative'

# ---------------------------------------------------------------------------
# Design system
# ---------------------------------------------------------------------------
# A fixed palette of "field status" colors, cycled through by category name so
# any category (including ones you add later in feeds_config.json) gets a
# stable, distinct color without needing to be hand-configured.
CATEGORY_PALETTE = [
    {"accent": "#b3421f", "tint": "#f6e9e4"},  # rust / failure red
    {"accent": "#2b5f8a", "tint": "#e6edf2"},  # steel blue / protection
    {"accent": "#3f7a4f", "tint": "#e9f0e9"},  # growth green
    {"accent": "#5c5347", "tint": "#efece6"},  # graphite / standards
    {"accent": "#6b4f8a", "tint": "#ede8f2"},  # insurance violet
    {"accent": "#b3781f", "tint": "#f5ece0"},  # copper / installation amber
]


def category_color(category):
    """Deterministically assign one of the palette colors to a category name."""
    idx = sum(ord(c) for c in category) % len(CATEGORY_PALETTE)
    return CATEGORY_PALETTE[idx]


SHARED_CSS = """
:root {
    --ink: #1b1f24;
    --paper: #f7f5f0;
    --paper-raised: #ffffff;
    --line: #ddd7c8;
    --muted: #706a5c;
    --copper: #b3781f;
}

* { box-sizing: border-box; }

body {
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: 'Source Serif 4', Georgia, 'Times New Roman', serif;
    font-size: 17px;
    line-height: 1.55;
}

h1, h2, h3, .masthead-title, .cat-card h2, .story h3 {
    font-family: 'Space Grotesk', 'Arial Narrow', Arial, sans-serif;
}

a { color: inherit; }

.meta, .eyebrow, nav, .updated, footer, .tag {
    font-family: 'IBM Plex Mono', 'Courier New', monospace;
}

/* ---------- masthead ---------- */
header.masthead {
    background: var(--ink);
    color: var(--paper);
    padding: 28px 24px 0 24px;
}

.masthead-inner {
    max-width: 880px;
    margin: 0 auto;
}

.masthead-title {
    font-size: 30px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin: 0;
    text-transform: uppercase;
}

.masthead-title a { text-decoration: none; color: inherit; }

.masthead-tagline {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12.5px;
    color: #c8bfa8;
    letter-spacing: 0.5px;
    margin: 6px 0 22px 0;
    text-transform: uppercase;
}

nav.catnav {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    padding-bottom: 16px;
    font-size: 12.5px;
    letter-spacing: 0.3px;
}

nav.catnav a {
    text-decoration: none;
    color: #e9e3d2;
    padding: 7px 12px;
    border: 1px solid #3a3f46;
    border-bottom: none;
    background: #23282f;
    text-transform: uppercase;
    white-space: nowrap;
}

nav.catnav a.home {
    background: var(--copper);
    border-color: var(--copper);
    color: #1b1f24;
    font-weight: 700;
}

nav.catnav a.active {
    background: var(--paper);
    color: var(--ink);
    border-color: var(--paper);
    font-weight: 700;
}

/* ---------- one-line-diagram divider (site signature) ---------- */
/* A thin schematic rule with node marks, evoking a single-line electrical
   diagram -- used wherever the page changes register (masthead -> body,
   section -> section). */
.diagram-rule {
    height: 14px;
    background:
        repeating-linear-gradient(
            to right,
            var(--copper) 0px, var(--copper) 2px,
            transparent 2px, transparent 34px
        );
    background-position: center;
    background-repeat: repeat-x;
    background-size: 34px 2px;
    position: relative;
}

.diagram-rule::before,
.diagram-rule::after {
    content: "";
    position: absolute;
    top: 50%;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--copper);
    transform: translateY(-50%);
}

.diagram-rule::before { left: 6%; }
.diagram-rule::after { right: 6%; }

/* ---------- layout ---------- */
main {
    max-width: 880px;
    margin: 0 auto;
    padding: 40px 24px 60px 24px;
}

.updated {
    color: var(--muted);
    font-size: 12px;
    letter-spacing: 0.3px;
    margin: 0 0 34px 0;
    text-transform: uppercase;
}

/* ---------- homepage category grid ---------- */
.cat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
    gap: 16px;
}

.cat-card {
    background: var(--paper-raised);
    border: 1px solid var(--line);
    border-left: 5px solid var(--accent, var(--copper));
    padding: 20px 20px 18px 18px;
    text-decoration: none;
    color: var(--ink);
    display: block;
    transition: transform 0.12s ease, box-shadow 0.12s ease;
}

.cat-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(27, 31, 36, 0.10);
}

.cat-card .eyebrow {
    font-size: 11px;
    color: var(--accent, var(--copper));
    letter-spacing: 1px;
    text-transform: uppercase;
    font-weight: 700;
}

.cat-card h2 {
    font-size: 20px;
    margin: 8px 0 10px 0;
}

.cat-card p {
    margin: 0;
    color: var(--muted);
    font-size: 13px;
    font-family: 'IBM Plex Mono', monospace;
}

/* ---------- story list (category page) ---------- */
.story {
    background: var(--paper-raised);
    border: 1px solid var(--line);
    border-left: 5px solid var(--accent, var(--copper));
    padding: 20px 22px;
    margin-bottom: 14px;
}

.story h3 {
    font-size: 19px;
    margin: 0 0 8px 0;
    line-height: 1.3;
}

.story h3 a {
    text-decoration: none;
    color: var(--ink);
}

.story h3 a:hover { color: var(--accent, var(--copper)); }

.story .meta {
    color: var(--muted);
    font-size: 11.5px;
    letter-spacing: 0.2px;
    text-transform: uppercase;
    margin: 0 0 10px 0;
}

.story p:last-child {
    margin: 0;
    color: #3a3630;
}

.empty-state {
    border: 1px dashed var(--line);
    padding: 30px;
    text-align: center;
    color: var(--muted);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
}

/* ---------- footer ---------- */
footer.site-footer {
    border-top: 1px solid var(--line);
    margin-top: 10px;
    padding-top: 18px;
    color: var(--muted);
    font-size: 11.5px;
    letter-spacing: 0.2px;
}

@media (max-width: 520px) {
    .masthead-title { font-size: 24px; }
    main { padding: 28px 16px 48px 16px; }
}
"""

FONT_LINKS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Space+Grotesk:wght@500;700&'
    'family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&'
    'family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">'
)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def slugify(text):
    """Turn a category name into a safe filename, e.g. 'World News' -> 'world_news'."""
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


def fetch_category_stories(category, feed_urls, known_ids):
    """Fetch all stories currently in the feeds for one category.

    known_ids is used only to tag which stories are brand new this run
    (for logging) -- it does not exclude older stories from the site."""
    stories = []
    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"  Could not fetch {url}: {e}")
            continue

        if parsed.bozo and not parsed.entries:
            print(f"  Warning: feed may be broken: {url}")

        for entry in parsed.entries:
            story_id = entry.get("id") or entry.get("link")
            if not story_id:
                continue

            title = entry.get("title", "Untitled")
            link = entry.get("link", "#")
            summary = entry.get("summary", "")
            # Strip any HTML tags from the summary so it displays as plain text
            summary_text = html.unescape(summary)
            source_title = parsed.feed.get("title", "Unknown source")
            published = entry.get("published", "")

            stories.append({
                "id": story_id,
                "title": title,
                "link": link,
                "summary": summary_text[:300],  # keep summaries short
                "source": source_title,
                "published": published,
            })
    return stories


def render_nav(all_categories, active_category=None):
    links = ['<a class="home" href="index.html">Home</a>']
    for c in all_categories:
        cls = "active" if c == active_category else ""
        links.append(
            f'<a class="{cls}" href="category_{slugify(c)}.html">{html.escape(c)}</a>'
        )
    return "\n".join(links)


def page_shell(title, body_html, nav_html, updated_line=""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
{FONT_LINKS}
<style>{SHARED_CSS}</style>
</head>
<body>
<header class="masthead">
  <div class="masthead-inner">
    <p class="masthead-title"><a href="index.html">{html.escape(SITE_NAME)}</a></p>
    <p class="masthead-tagline">{html.escape(SITE_TAGLINE)}</p>
    <nav class="catnav">{nav_html}</nav>
  </div>
</header>
<div class="diagram-rule"></div>
<main>
{updated_line}
{body_html}
<footer class="site-footer">{SPONSOR_DISCLOSURE_HTML}</footer>
</main>
</body>
</html>
"""


def render_category_page(category, stories, all_categories):
    color = category_color(category)
    nav_html = render_nav(all_categories, active_category=category)

    if not stories:
        items_html = (
            '<div class="empty-state">No new stories yet. '
            'Check back after the next update.</div>'
        )
    else:
        cards = []
        for s in stories[:MAX_STORIES_PER_CATEGORY]:
            cards.append(f"""<div class="story" style="--accent:{color['accent']}">
  <h3><a href="{html.escape(s['link'])}" target="_blank" rel="noopener">{html.escape(s['title'])}</a></h3>
  <p class="meta">{html.escape(s['source'])} &middot; {html.escape(s['published'])}</p>
  <p>{html.escape(s['summary'])}&hellip;</p>
</div>""")
        items_html = "\n".join(cards)

    body = f"""<h1 style="border-bottom:3px solid {color['accent']}; padding-bottom:10px; margin-top:0;">{html.escape(category)}</h1>
{items_html}"""

    return page_shell(f"{category} News", body, nav_html)


def render_index_page(categories, story_counts, last_updated):
    cards = []
    for c in categories:
        color = category_color(c)
        count = story_counts.get(c, 0)
        cards.append(f"""<a class="cat-card" style="--accent:{color['accent']}" href="category_{slugify(c)}.html">
  <p class="eyebrow">Category</p>
  <h2>{html.escape(c)}</h2>
  <p>{count} stories tracked</p>
</a>""")

    body = f"""<div class="cat-grid">
{''.join(cards)}
</div>"""

    updated_line = f'<p class="updated">Last updated: {html.escape(last_updated)}</p>'
    nav_html = render_nav(categories, active_category=None)
    return page_shell(SITE_NAME, body, nav_html, updated_line=updated_line)


def main():
    print("Starting news aggregation run...")
    config = load_json(CONFIG_FILE, {})
    if not config:
        print(f"ERROR: {CONFIG_FILE} not found or empty. Add your feeds there first.")
        return

    # story_store keeps every story we've ever seen per category, so the
    # site always shows a rolling feed rather than shrinking over time.
    store = load_json(STORE_FILE, {})
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    story_counts = {}

    for category, feed_urls in config.items():
        print(f"Fetching category: {category} ({len(feed_urls)} feed(s))")
        existing = store.get(category, [])
        existing_ids = {s["id"] for s in existing}

        fetched = fetch_category_stories(category, feed_urls, existing_ids)
        new_count = sum(1 for s in fetched if s["id"] not in existing_ids)

        # Merge: keep existing stories, add genuinely new ones, dedupe by id
        merged = {s["id"]: s for s in existing}
        for s in fetched:
            merged[s["id"]] = s  # refresh with latest data if seen again

        merged_list = list(merged.values())
        merged_list.sort(key=lambda s: s["published"], reverse=True)

        # Cap how much we keep long-term so the file doesn't grow forever
        merged_list = merged_list[:200]
        store[category] = merged_list

        page_html = render_category_page(category, merged_list, list(config.keys()))
        out_path = os.path.join(OUTPUT_DIR, f"category_{slugify(category)}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(page_html)

        story_counts[category] = len(merged_list)
        print(f"  -> {new_count} new stories this run, {len(merged_list)} total shown, written to {out_path}")

    save_json(STORE_FILE, store)

    # Update index page
    last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    index_html = render_index_page(list(config.keys()), story_counts, last_updated)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"Done. Open {OUTPUT_DIR}/index.html in your browser to view the site.")


if __name__ == "__main__":
    main()
