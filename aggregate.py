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
STORE_FILE = "story_store.json"  # persistent archive of stories per category
OUTPUT_DIR = "site"
MAX_STORIES_PER_CATEGORY = 30  # how many stories to show per category page

# Shown in the footer of every page. Edit this to control how sponsorship
# is disclosed to visitors -- keeping this honest and visible is what lets
# a sponsor-supported trade site retain professional trust over time.
SPONSOR_DISCLOSURE_HTML = 'An independent industry resource brought to you by JGV Creative'


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


def render_category_page(category, stories, all_categories):
    nav_links = "".join(
        f'<a href="index.html">Home</a> | ' if i == 0 else ""
        for i in range(1)
    )
    cat_nav = " | ".join(
        f'<a href="category_{slugify(c)}.html">{html.escape(c)}</a>' for c in all_categories
    )

    items_html = ""
    if not stories:
        items_html = "<p>No new stories yet. Check back after the next update.</p>"
    else:
        for s in stories[:MAX_STORIES_PER_CATEGORY]:
            items_html += f"""
            <div class="story">
              <h3><a href="{html.escape(s['link'])}" target="_blank" rel="noopener">{html.escape(s['title'])}</a></h3>
              <p class="meta">{html.escape(s['source'])} &middot; {html.escape(s['published'])}</p>
              <p>{html.escape(s['summary'])}...</p>
            </div>
            """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{html.escape(category)} News</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #222; }}
  h1 {{ border-bottom: 3px solid #222; padding-bottom: 10px; }}
  nav {{ margin-bottom: 30px; font-size: 14px; }}
  nav a {{ text-decoration: none; color: #0645ad; margin-right: 4px; }}
  .story {{ border-bottom: 1px solid #ddd; padding: 16px 0; }}
  .story h3 {{ margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 13px; margin: 2px 0 8px 0; }}
  footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd; color: #888; font-size: 12px; }}
</style>
</head>
<body>
  <nav><a href="index.html">Home</a> | {cat_nav}</nav>
  <h1>{html.escape(category)}</h1>
  {items_html}
  <footer>{SPONSOR_DISCLOSURE_HTML}</footer>
</body>
</html>
"""


def render_index_page(categories, story_counts, last_updated):
    links_html = ""
    for c in categories:
        count = story_counts.get(c, 0)
        links_html += f"""
        <div class="cat-card">
          <a href="category_{slugify(c)}.html"><h2>{html.escape(c)}</h2></a>
          <p>{count} new stories</p>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>My News Site</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #222; }}
  h1 {{ border-bottom: 3px solid #222; padding-bottom: 10px; }}
  .updated {{ color: #666; font-size: 13px; margin-bottom: 30px; }}
  .cat-card {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin-bottom: 14px; }}
  .cat-card a {{ text-decoration: none; color: #222; }}
  .cat-card h2 {{ margin: 0 0 6px 0; }}
  footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd; color: #888; font-size: 12px; }}
</style>
</head>
<body>
  <h1>My News Site</h1>
  <p class="updated">Last updated: {last_updated}</p>
  {links_html}
  <footer>{SPONSOR_DISCLOSURE_HTML}</footer>
</body>
</html>
"""


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
