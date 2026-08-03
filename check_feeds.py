"""
Feed Checker
------------
Run this any time you add/change a feed URL in feeds_config.json to
confirm it's alive and actually returns stories, before you rely on it
in the main site. This does NOT touch story_store.json or site/ --
it's just a dry-run diagnostic.

HOW TO RUN:
    python3 check_feeds.py
"""

import json
import feedparser

CONFIG_FILE = "feeds_config.json"


def main():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    print(f"Checking feeds in {CONFIG_FILE}...\n")
    any_problems = False

    for category, feed_urls in config.items():
        print(f"[{category}]")
        if not feed_urls:
            print("  (no feeds configured yet for this category)")
            any_problems = True
            continue

        for url in feed_urls:
            try:
                parsed = feedparser.parse(url)
            except Exception as e:
                print(f"  FAILED  {url}  ({e})")
                any_problems = True
                continue

            entry_count = len(parsed.entries)
            feed_title = parsed.feed.get("title", "Unknown title")

            if entry_count == 0:
                print(f"  EMPTY   {url}  -- '{feed_title}' returned 0 stories. Feed may be broken or URL wrong.")
                any_problems = True
            else:
                latest = parsed.entries[0].get("title", "")
                print(f"  OK      {url}  -- '{feed_title}' ({entry_count} stories)")
                print(f"           latest: {latest[:80]}")

        print()

    if any_problems:
        print("Some feeds need attention (see FAILED/EMPTY lines above, and any categories with no feeds).")
    else:
        print("All feeds look healthy.")


if __name__ == "__main__":
    main()
