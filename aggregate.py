"""
News Aggregator
----------------
Reads a flat list of RSS feeds from feeds_config.json, fetches every story
from every feed, and uses Claude (Haiku 4.5, via the Anthropic API) to
classify each new story into one of the categories/subcategories defined
in CATEGORY_DEFINITIONS below -- or leaves it out entirely if it doesn't
clearly fit any of them. Classifications are cached in
story_classifications.json so a story is only ever classified once, no
matter how many times the workflow runs.

feeds_config.json format -- just a flat list of feed URLs:
    { "feeds": ["https://example.com/feed1", "https://example.com/feed2"] }

The category structure itself (which top-level categories exist, which
ones are split into subcategories, and exactly what each one covers) is
defined in code below, in TOP_LEVEL_STRUCTURE and CATEGORY_DEFINITIONS --
edit those if you want to add/change/remove a category.

Requires an ANTHROPIC_API_KEY environment variable (set as a GitHub
Actions secret in production) to run classification. If it's missing,
the run continues but skips classifying any new stories (a warning is
printed) -- existing already-classified stories still render fine.

Also builds:
  - a Trade Shows page from tradeshows_config.json (manually maintained,
    since no power-industry trade show publishes a real RSS/events feed),
    split into "Attend" (everything upcoming) and "Exhibit" (only shows
    that still have enough lead time -- EXHIBIT_LEAD_DAYS -- for a vendor
    to realistically apply for a booth)
  - a Featured article + archive from markdown files dropped into
    featured_articles/
  - a static "Advertise With Us" inquiry page, plus Terms of Service and
    Privacy Policy pages
  - a site-wide search index (search-index.json) powering the search box
    on every page
  - SEO essentials: meta descriptions, canonical tags, Open Graph/Twitter
    cards, JSON-LD structured data, sitemap.xml, robots.txt
  - copies your logo/favicon/CNAME into site/ every run, since the hourly
    GitHub Actions workflow wipes docs/ and rebuilds it from site/ each time

HOW TO RUN:
    ANTHROPIC_API_KEY=sk-ant-... python3 aggregate.py

OUTPUT:
    site/index.html          <- homepage
    site/category_XXX.html   <- one page per top-level category
    site/category_trade_shows.html
    site/featured_XXX.html   <- one page per featured article
    site/featured_archive.html
    site/advertise.html
    site/terms.html
    site/privacy.html
    site/search-index.json
    site/sitemap.xml
    site/robots.txt
    site/CNAME
    site/assets/             <- copied from your repo's assets/ folder
    story_store.json               <- memory file so stories aren't repeated
    story_classifications.json     <- memory file: story id -> assigned category
"""

import json
import os
import re
import html
import shutil
import urllib.request
import urllib.error
from datetime import datetime, timezone, date

import feedparser
import markdown as md

CONFIG_FILE = "feeds_config.json"
TRADESHOWS_FILE = "tradeshows_config.json"
FEATURED_DIR = "featured_articles"
ASSETS_SRC_DIR = "assets"
STORE_FILE = "story_store.json"                       # persistent archive of stories per bucket
CLASSIFICATION_CACHE_FILE = "story_classifications.json"  # story id -> assigned category (or null)
OUTPUT_DIR = "site"

# Each category keeps a rolling window of its most recent stories. A story
# stays on its category page -- even after it scrolls out of the live RSS
# feed -- until this many NEWER stories have pushed it off the bottom.
STORIES_PER_CATEGORY = 12
MAX_STORIES_PER_CATEGORY = STORIES_PER_CATEGORY   # display cap (same window)

SITE_NAME = "Power Industry News"
SITE_TAGLINE = "Grid intelligence for utility, protection, and plant professionals"
BASE_URL = "https://powerindustry.news"   # no trailing slash

# Shown in the footer of every page. Edit this to control how sponsorship
# is disclosed to visitors -- keeping this honest and visible is what lets
# a sponsor-supported trade site retain professional trust over time.
SPONSOR_DISCLOSURE_HTML = 'An independent industry resource brought to you by JGV Creative'

TRADE_SHOWS_LABEL = "Tradeshows"

# Category artwork. These tiles carry the category NAME in the image itself,
# so pages deliberately do not repeat the label as visible text -- the name is
# still exposed to search engines and screen readers via alt text.
# Authoritative bodies referenced by the Standards category. Rendered as a
# link row at the top of that page only.
STANDARDS_LINKS = [
    ("NERC", "https://www.nerc.com/"),
    ("NERC CIP", "https://www.nerc.com/pa/Stand/Pages/CIPStandards.aspx"),
    ("FERC", "https://www.ferc.gov/"),
    ("NFPA 70E", "https://www.nfpa.org/codes-and-standards/nfpa-70e-standard-development/70e"),
    ("IEEE Standards", "https://standards.ieee.org/"),
    ("IEC", "https://www.iec.ch/"),
]

CATEGORY_ICONS = {
    "Failures": "failures.png",
    "Protections": "protection.png",
    "Installations": "installations.png",
    "Standards": "standards.png",
    "Insurance": "insurance.png",
    "Tradeshows": "trade-shows.png",
    "Featured": "featured.png",
}

# Categories were renamed to match the icon artwork; stored classifications
# using the old names are rewritten so those stories keep their category.
CATEGORY_RENAMES = {"Protection": "Protections", "Trade Shows": "Tradeshows"}

# How many days out a trade show needs to be for it to count as "still
# open to sign up as an exhibitor" in the Trade Shows page's Exhibit
# section. This is a simple proxy (not a real per-event deadline), since
# tradeshows_config.json doesn't track each event's actual exhibitor
# application deadline. Adjust this number if it feels too strict/loose.
EXHIBIT_LEAD_DAYS = 75

# --- Advertise / legal pages -------------------------------------------------
BUSINESS_NAME = "Varga Creative"
GOVERNING_STATE = "Texas"
# Kept for your reference only -- deliberately NOT rendered on any public
# page, since a plain address gets harvested by spam crawlers.
CONTACT_EMAIL = "contactSET@proton.me"

# Paste your Google Form's embed URL here once you've created it (Google
# Forms -> Send -> the "<>" embed tab -> copy the src="..." URL). Until
# then, the Advertise page shows a simple mailto fallback instead.
ADVERTISE_FORM_EMBED_URL = "https://docs.google.com/forms/d/e/1FAIpQLSd371L0E09UK17cddTSCU9iq14JdzX2YnPDztJb9zLA7k0Mkw/viewform?embedded=true"

# ---------------------------------------------------------------------------
# AI classification (Claude Haiku 4.5) -- replaces keyword filtering
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"
# GoatCounter: privacy-friendly, cookie-free visitor counting. The dashboard
# lives at https://powerindustrynews.goatcounter.com -- nothing is displayed on
# the site itself. Set to "" to disable analytics entirely.
GOATCOUNTER_URL = "https://powerindustrynews.goatcounter.com/count"

CLASSIFIER_BATCH_SIZE = 25
# Ceiling on how many NEW stories get classified in a single run. Anything
# over the limit is left unclassified and picked up next run, since results
# are cached. Keeps a large backlog from producing a multi-hour job.
MAX_NEW_CLASSIFICATIONS_PER_RUN = 300   # stories per API call -- keeps each request small and cheap

# The category structure the site actually renders. "compound" categories
# get split into subcategory sections on their own page (Installations,
# Standards); simple categories are a single page/bucket.
TOP_LEVEL_STRUCTURE = {
    "Failures": {"compound": False},
    "Protections": {"compound": False},
    "Installations": {"compound": True, "subcategories": ["Transmission and Distribution", "Generation"]},
    "Standards": {"compound": True, "subcategories": ["Safety Standards", "Grid/Regulatory Compliance", "Technical Standards"]},
    "Insurance": {"compound": False},
}

# The exact definition of each leaf category (top-level name for simple
# categories, "Parent::Subcategory" for subcategories of a compound one).
# This is what gets sent to Claude for classification -- be as specific
# as you want here, including what to explicitly exclude.
CATEGORY_DEFINITIONS = {
    "Failures": (
        "Equipment or system failures in the electrical power industry: "
        "transformer failures, breaker failures, cable faults, blackouts, "
        "major grid outages, relay misoperations, and root-cause/post-mortem "
        "analyses of such failures. Only include a story if it is actually "
        "ABOUT a failure event -- do not include stories that merely mention "
        "the word 'failure' in passing (e.g. a company avoiding failure, or "
        "an unrelated 'failure to meet earnings')."
    ),
    "Protections": (
        "Equipment-level protection technology for power systems: "
        "transformer fire prevention systems, fast/rapid depressurization "
        "systems, explosion prevention systems, protective relay "
        "coordination, and protection scheme design/upgrades. Do NOT "
        "include broader grid-level protection, grid security, or "
        "cybersecurity stories -- those do not belong here even if they use "
        "the word 'protection'."
    ),
    "Installations::Transmission and Distribution": (
        "Sales-lead-relevant news for equipment vendors about new or "
        "retrofit transmission and distribution equipment installations: "
        "new substations being built or upgraded, transformers, "
        "switchgear, circuit breakers, transmission lines, distribution "
        "grid upgrades. This is about specific T&D equipment installation "
        "projects, not whole new generation facilities."
    ),
    "Installations::Generation": (
        "Sales-lead-relevant news for vendors about new power generation "
        "facilities being built: wind farms, solar farms, gas plants, "
        "nuclear plants, hydro plants, battery storage facilities -- from "
        "groundbreaking through commissioning. This is about new "
        "generation facilities, not transmission/distribution equipment."
    ),
    "Standards::Safety Standards": (
        "News about electrical safety codes and worker safety standards, "
        "such as NFPA 70E and arc flash safety requirements."
    ),
    "Standards::Grid/Regulatory Compliance": (
        "News about mandatory regulatory compliance requirements for "
        "utilities and the grid, such as NERC CIP, FERC rulings, and "
        "reliability standard mandates."
    ),
    "Standards::Technical Standards": (
        "News about engineering technical standard revisions and updates, "
        "such as IEEE and IEC standard changes."
    ),
    "Insurance": (
        "News specifically about the insurability of power generation "
        "companies and their infrastructure -- insurers declining to "
        "cover, restricting coverage, non-renewing policies, or otherwise "
        "pulling back from insuring power generation assets. This is NOT "
        "general insurance industry news -- it must be specifically about "
        "power generation companies/infrastructure struggling to get or "
        "keep insurance coverage."
    ),
}

# ---------------------------------------------------------------------------
# Design system
# ---------------------------------------------------------------------------
CATEGORY_PALETTE = [
    {"accent": "#ff6f4d", "tint": "#2a1a15"},  # failures -- ember orange
    {"accent": "#4da3e0", "tint": "#14212b"},  # protection -- steel blue
    {"accent": "#5cb872", "tint": "#152318"},  # installations -- green
    {"accent": "#9aa5b1", "tint": "#1c2027"},  # standards -- graphite
    {"accent": "#a58ae0", "tint": "#201a2b"},  # insurance -- violet
    {"accent": "#3d9bff", "tint": "#12202e"},  # primary blue
    {"accent": "#e0b155", "tint": "#2a2317"},  # featured -- warm gold, editorial
]



# Explicit color per category. This used to be a hash of the category name,
# which drifted every time a category was renamed and produced collisions
# (two tiles the same color). Pinning it keeps the intended meaning: warm
# for hazard, cool for engineering, neutral for reference.
CATEGORY_COLOR_MAP = {
    "Failures":      CATEGORY_PALETTE[0],  # ember orange -- hazard
    "Protections":   CATEGORY_PALETTE[1],  # steel blue
    "Installations": CATEGORY_PALETTE[2],  # green -- build/growth
    "Standards":     CATEGORY_PALETTE[3],  # graphite -- reference
    "Insurance":     CATEGORY_PALETTE[4],  # violet
    "Tradeshows":    CATEGORY_PALETTE[5],  # primary blue
    "Featured":      CATEGORY_PALETTE[6],  # warm gold -- editorial, not a feed
}


def category_color(category):
    """Palette color for a category. Falls back to a stable hash for any
    category added later in feeds_config.json that isn't mapped above."""
    mapped = CATEGORY_COLOR_MAP.get(category)
    if mapped:
        return mapped
    idx = sum(ord(c) for c in category) % len(CATEGORY_PALETTE)
    return CATEGORY_PALETTE[idx]


# Hand-written, keyword-relevant descriptions for the top-level categories
# this site ships with. Any category you add later in feeds_config.json
# that isn't listed here just gets a sensible generic description instead
# of breaking.
CATEGORY_DESCRIPTIONS = {
    "Failures": "Transformer failures, relay misoperations, and equipment "
                 "outage reports for electrical power industry safety "
                 "engineers and reliability teams.",
    "Protection": "Transformer fire prevention, fast and rapid "
                  "depressurization systems, explosion prevention, and "
                  "protective relaying news for power system protection "
                  "engineers -- not broader grid-level protection.",
    "Installations": "Sales leads for vendors: new and retrofit "
                      "transmission and distribution equipment installs, "
                      "plus new generation facilities being built, around "
                      "the world.",
    "Standards": "Safety codes, regulatory compliance, and technical "
                 "engineering standards relevant to electrical power "
                 "system safety, protection, and reliability.",
    "Insurance": "Insurability of power generation companies and their "
                 "infrastructure -- coverage denials, non-renewals, and "
                 "insurers pulling back from power industry risk.",
    "Trade Shows": "Upcoming power industry conferences and trade shows. "
                   "Attend to see what's coming up, or check Exhibit for "
                   "shows that still have enough lead time to apply for a "
                   "vendor booth.",
}

# Short one-line descriptions shown under each subcategory heading on a
# compound category's page (Installations, Standards).
SUBCATEGORY_DESCRIPTIONS = {
    "Transmission and Distribution": "New substations, transmission lines, "
        "transformers, switchgear, and distribution equipment -- new "
        "builds and retrofits.",
    "Generation": "New wind, solar, gas, nuclear, hydro, and battery "
        "storage facilities under construction.",
    "Safety Standards": "NFPA 70E, arc flash, and worker safety code "
        "updates.",
    "Grid/Regulatory Compliance": "NERC CIP, FERC rulings, and mandatory "
        "utility compliance requirements.",
    "Technical Standards": "IEEE, IEC, and other engineering "
        "specification updates and revisions.",
}


def get_category_description(category):
    return CATEGORY_DESCRIPTIONS.get(
        category,
        f"{category} news and analysis for electrical power industry "
        f"safety engineers."
    )


SHARED_CSS = """
:root {
    --ink: #eaf2fb;          /* primary text */
    --paper: #10263f;        /* page background -- deep blue, same hue as the tiles */
    --paper-raised: #16334f; /* cards / raised surfaces */
    --line: #27496e;         /* hairlines and borders */
    --muted: #9fb6ce;        /* secondary text */
    --body-dim: #cfdeee;     /* body copy inside cards */
    --copper: #6fb6ff;       /* primary accent -- lighter blue, readable on navy */
    --accent-solid: #148bf5; /* the tile blue, for solid fills */
    --masthead: #0c1e33;     /* header band, deeper than the page */
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

h1, h2, h3, .cat-card h2, .story h3 {
    font-family: 'Space Grotesk', 'Arial Narrow', Arial, sans-serif;
}

a { color: inherit; }

.meta, .eyebrow, nav, .updated, footer, .tag, input#site-search {
    font-family: 'IBM Plex Mono', 'Courier New', monospace;
}

/* ---------- masthead ---------- */
header.masthead {
    background: var(--masthead);
    color: var(--ink);
    border-bottom: 1px solid var(--line);
    padding: 22px 24px 0 24px;
}

.masthead-inner {
    max-width: 960px;
    margin: 0 auto;
}

.masthead-logo-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 14px;
    margin-bottom: 6px;
}

.masthead-logo-row a.brand {
    display: flex;
    align-items: center;
    text-decoration: none;
}

.masthead-logo-row img.brand-logo {
    height: 88px;          /* doubled */
    width: auto;
    display: block;
}

.masthead-logo-row .search-wrap { margin-left: 12px; }

/* Pushes the button + search to the right of the logo. On narrow screens the
   row wraps instead of shrinking the controls. */
.masthead-logo-row .advertise-btn { margin-left: auto; }

.advertise-btn {
    display: inline-block;
    padding: 9px 16px;
    background: var(--accent-solid);
    color: #06121f;
    font-family: 'Space Grotesk', Arial, sans-serif;
    font-size: 13.5px;
    font-weight: 700;
    letter-spacing: 0.02em;
    text-decoration: none;
    border-radius: 3px;
    white-space: nowrap;
    transition: filter 0.12s ease;
}

.advertise-btn:hover { filter: brightness(1.12); }

/* ---------- reference link row (Standards page) ---------- */
.ref-links {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin: 0 0 22px 0;
}

.ref-links-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
}

.ref-links a {
    display: inline-block;
    padding: 5px 11px;
    border: 1px solid var(--line);
    border-radius: 3px;
    background: var(--paper-raised);
    color: var(--copper);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    text-decoration: none;
    transition: border-color 0.12s ease;
}

.ref-links a:hover { border-color: var(--copper); }

@media (max-width: 700px) {
    .masthead-logo-row { flex-wrap: wrap; row-gap: 10px; }
    .masthead-logo-row .advertise-btn { margin-left: 0; }
    .masthead-logo-row .search-wrap { margin-left: 0; }
}

.masthead-tagline {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--muted);
    letter-spacing: 0.5px;
    margin: 2px 0 12px 0;
    text-transform: uppercase;
}

.masthead-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    padding-bottom: 16px;
}

nav.catnav {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    font-size: 12px;
    letter-spacing: 0.3px;
}

nav.catnav a {
    text-decoration: none;
    color: #dbe8f6;
    padding: 7px 11px;
    border: 1px solid #2d5480;
    border-bottom: none;
    background: #163558;
    text-transform: uppercase;
    white-space: nowrap;
}

nav.catnav a.home {
    background: var(--accent-solid);
    border-color: var(--accent-solid);
    color: #06121f;
    font-weight: 700;
}

nav.catnav a.active {
    background: transparent;
    color: var(--copper);
    border-color: var(--copper);
    font-weight: 700;
}

/* ---------- search box ---------- */
.search-wrap {
    position: relative;
}

input#site-search {
    background: #23282f;
    border: 1px solid #3a3f46;
    color: #f0ece0;
    padding: 8px 12px;
    font-size: 13px;
    width: 220px;
    outline: none;
}

input#site-search::placeholder { color: #7c848d; }
input#site-search:focus { border-color: var(--copper); }

#search-results {
    display: none;
    position: absolute;
    top: 100%;
    right: 0;
    margin-top: 4px;
    width: 340px;
    max-height: 380px;
    overflow-y: auto;
    background: var(--paper-raised);
    border: 1px solid var(--line);
    box-shadow: 0 10px 24px rgba(0,0,0,0.25);
    z-index: 50;
}

#search-results.open { display: block; }

#search-results a {
    display: block;
    padding: 10px 14px;
    text-decoration: none;
    color: var(--ink);
    border-bottom: 1px solid var(--line);
    font-family: 'Source Serif 4', Georgia, serif;
}

#search-results a:last-child { border-bottom: none; }
#search-results a:hover { background: var(--paper); }

#search-results .sr-title { font-weight: 600; font-size: 14.5px; }
#search-results .sr-meta {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10.5px;
    color: var(--muted);
    text-transform: uppercase;
    margin-top: 2px;
}

#search-results .sr-empty {
    padding: 14px;
    color: var(--muted);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
}

/* ---------- one-line-diagram divider (site signature) ---------- */
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

/* ---------- advertisement banner ---------- */
.ad-banner {
    max-width: 880px;
    margin: 18px auto 0 auto;
    padding: 40px 20px;
    text-align: center;
    border: 1px dashed var(--line);
    background: var(--paper-raised);
    color: var(--muted);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: flex;
    align-items: center;
    justify-content: center;
}

/* ---------- layout ---------- */
main {
    max-width: 880px;
    margin: 0 auto;
    padding: 24px 24px 60px 24px;
}

.updated {
    color: var(--muted);
    font-size: 12px;
    letter-spacing: 0.3px;
    margin: 16px 0 28px 0;
    text-transform: uppercase;
}

.category-intro {
    color: var(--body-dim);
    margin: 6px 0 26px 0;
    max-width: 80ch;   /* fills more of the column, still inside a readable line length */
}

/* ---------- spotlight / callout cards (homepage) ---------- */
.feature-row {
    display: grid;
    grid-template-columns: 1fr;
    gap: 16px;
    margin-bottom: 30px;
}

@media (min-width: 720px) {
    .feature-row.has-both { grid-template-columns: 1.3fr 1fr; }
}

.spotlight-card, .callout-card {
    background: var(--paper-raised);
    border: 1px solid var(--line);
    padding: 22px 24px;
}

.spotlight-card { border-left: 5px solid var(--copper); }
.callout-card { border: 1px dashed var(--copper); }

.spotlight-card .eyebrow, .callout-card .eyebrow {
    font-size: 11px;
    color: var(--copper);
    letter-spacing: 1.5px;
    text-transform: uppercase;
    font-weight: 700;
}

.spotlight-card h2, .callout-card h2 {
    font-size: 21px;
    margin: 8px 0 8px 0;
}

.spotlight-card p, .callout-card p {
    margin: 0 0 6px 0;
    color: var(--body-dim);
    font-size: 15px;
}

.callout-card .event-meta {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12.5px;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 8px;
}

.spotlight-card a.readmore, .callout-card a.readmore {
    display: inline-block;
    margin-top: 8px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    color: var(--copper);
    text-decoration: none;
    border-bottom: 1px solid var(--copper);
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
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
}

.cat-card {
    text-align: center;
    padding: 18px 14px 14px 14px;
}

.cat-icon { width: 96px; height: 96px; display: block; margin: 0 auto 10px auto; }
.cat-icon-head { width: 88px; height: 88px; display: block; margin: 0 0 14px 0; }

.cat-heading {
    border-bottom: 3px solid var(--accent, var(--copper));
    padding-bottom: 12px;
    margin: 0 0 18px 0;
}

/* Visually hidden, still read by screen readers and indexed by search. */
.sr-only {
    position: absolute;
    width: 1px; height: 1px;
    padding: 0; margin: -1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
    border: 0;
}

/* ---------- next event strip (compact, full width) ---------- */
.next-event {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    max-width: 880px;
    margin: 0 auto 20px auto;
    padding: 10px 16px;
    background: var(--paper-raised);
    border: 1px solid var(--line);
    border-left: 4px solid var(--accent-solid);
    text-decoration: none;
    color: var(--ink);
    transition: border-color 0.12s ease;
}

.next-event:hover { border-color: var(--copper); }

.next-event-tag {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10.5px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--accent-solid);
    white-space: nowrap;
}

.next-event-name {
    font-family: 'Space Grotesk', Arial, sans-serif;
    font-size: 15px;
    font-weight: 600;
}

.next-event-meta {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11.5px;
    color: var(--muted);
}

.next-event-arrow { margin-left: auto; color: var(--copper); }

@media (max-width: 520px) {
    .next-event-arrow { display: none; }
}

.cat-card p {
    margin: 0;
    color: var(--muted);
    font-size: 13px;
    font-family: 'IBM Plex Mono', monospace;
}

/* ---------- story / event list ---------- */
.story, .event-card {
    background: var(--paper-raised);
    border: 1px solid var(--line);
    border-left: 5px solid var(--accent, var(--copper));
    padding: 20px 22px;
    margin-bottom: 14px;
}

.story h3, .event-card h3 {
    font-size: 19px;
    margin: 0 0 8px 0;
    line-height: 1.3;
}

.story h3 a, .event-card h3 a {
    text-decoration: none;
    color: var(--ink);
}

.story h3 a:hover, .event-card h3 a:hover { color: var(--accent, var(--copper)); }
.lang-tag {
  display: inline-block;
  margin-left: 0.5rem;
  padding: 0.1rem 0.4rem;
  border: 1px solid var(--accent, var(--copper));
  border-radius: 3px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--accent, var(--copper));
  vertical-align: middle;
}

.story .meta, .event-card .meta {
    color: var(--muted);
    font-size: 11.5px;
    letter-spacing: 0.2px;
    text-transform: uppercase;
    margin: 0 0 10px 0;
}

.story p:last-child, .event-card p:last-child {
    margin: 0;
    color: var(--body-dim);
}

.story, .event-card, .story *, .event-card * {
    overflow-wrap: break-word;
    word-break: break-word;
}

.empty-state {
    border: 1px dashed var(--line);
    padding: 30px;
    text-align: center;
    color: var(--muted);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
}

/* ---------- subcategory sections (Installations, Standards, Trade Shows) --- */
.subcategory-block {
    margin-bottom: 40px;
}

.subcategory-block h2 {
    font-size: 22px;
    margin: 0 0 8px 0;
}

/* ---------- featured article page ---------- */
.article-body {
    font-size: 18px;
    line-height: 1.7;
    max-width: 68ch;
}

.article-body h2 { font-size: 24px; margin-top: 34px; }
.article-body h3 { font-size: 20px; margin-top: 26px; }
.article-body p { margin: 0 0 18px 0; }
.article-body a { color: var(--copper); }
.article-body blockquote {
    border-left: 3px solid var(--copper);
    margin: 20px 0;
    padding: 4px 0 4px 18px;
    color: var(--muted);
    font-style: italic;
}
.article-body img { max-width: 100%; height: auto; }

.archive-list a {
    display: block;
    text-decoration: none;
    color: var(--ink);
    padding: 16px 0;
    border-bottom: 1px solid var(--line);
}

.archive-list a:hover h3 { color: var(--copper); }
.archive-list h3 { margin: 0 0 6px 0; font-size: 18px; }
.archive-list .meta {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
}

/* ---------- advertise page ---------- */
.advertise-form {
    margin-top: 10px;
}

.advertise-form iframe {
    border: 1px solid var(--line);
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

.footer-links {
    margin: 6px 0 0 0;
}

.footer-links a {
    color: var(--muted);
    text-decoration: underline;
}

@media (max-width: 520px) {
    main { padding: 20px 16px 48px 16px; }
    input#site-search { width: 150px; }
    #search-results { width: 280px; }
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

SEARCH_SCRIPT = """
<script>
(function() {
  var input = document.getElementById('site-search');
  var results = document.getElementById('search-results');
  if (!input || !results) return;
  var indexData = null;

  function loadIndex(cb) {
    if (indexData) { cb(indexData); return; }
    fetch('search-index.json').then(function(r){ return r.json(); }).then(function(data){
      indexData = data;
      cb(data);
    }).catch(function(){ indexData = []; cb([]); });
  }

  function render(matches) {
    if (matches.length === 0) {
      results.innerHTML = '<div class="sr-empty">No matches yet -- keep typing.</div>';
      return;
    }
    var html = '';
    matches.slice(0, 12).forEach(function(m) {
      html += '<a href="' + m.url + '">' +
              '<div class="sr-title">' + m.title + '</div>' +
              '<div class="sr-meta">' + m.category + ' &middot; ' + m.source + '</div>' +
              '</a>';
    });
    results.innerHTML = html;
  }

  input.addEventListener('input', function() {
    var q = input.value.trim().toLowerCase();
    if (q.length < 2) { results.classList.remove('open'); return; }
    loadIndex(function(data) {
      var matches = data.filter(function(item) {
        return (item.title + ' ' + item.summary + ' ' + item.category)
          .toLowerCase().indexOf(q) !== -1;
      });
      render(matches);
      results.classList.add('open');
    });
  });

  document.addEventListener('click', function(e) {
    if (!results.contains(e.target) && e.target !== input) {
      results.classList.remove('open');
    }
  });
})();
</script>
"""


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def slugify(text):
    """Turn a category/title/filename into a safe filename fragment."""
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


# ---------------------------------------------------------------------------
# feeds_config.json loading (flat feed list) + AI classification
# ---------------------------------------------------------------------------
def load_feed_urls(raw_config):
    """feeds_config.json is just {"feeds": [url, url, ...]}. Also accepts
    the old per-category dict/list format for backwards compatibility by
    flattening every feed URL out of it, deduplicated."""
    urls = set()
    if isinstance(raw_config, dict) and "feeds" in raw_config and isinstance(raw_config["feeds"], list):
        urls.update(raw_config["feeds"])
    else:
        # legacy nested formats -- just pull every feed URL out of them
        for val in raw_config.values():
            if isinstance(val, list):
                urls.update(val)
            elif isinstance(val, dict):
                urls.update(val.get("feeds", []))
                for sub in val.get("subcategories", {}).values():
                    urls.update(sub.get("feeds", []))
    return sorted(urls)


def _call_anthropic(prompt):
    body = json.dumps({
        "model": CLASSIFIER_MODEL,
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    )


def _parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text)


def migrate_classification_cache(cache):
    changed = 0
    for sid, entry in cache.items():
        old = cache_category(entry)
        if old in CATEGORY_RENAMES:
            new = CATEGORY_RENAMES[old]
            if isinstance(entry, dict):
                entry["category"] = new
            else:
                cache[sid] = new
            changed += 1
    if changed:
        print(f"  Migrated {changed} classification(s) to renamed categories")
    return cache


def cache_category(entry):
    """The classification cache holds either a bare leaf_key/None (the old
    format) or a dict with category + translation fields (the new format).
    This returns just the category either way."""
    if isinstance(entry, dict):
        return entry.get("category")
    return entry


def classify_stories_with_ai(stories, category_definitions):
    """Ask Claude Haiku to assign each story to the single best-fit leaf
    category (or None), AND -- for stories not written in English -- to
    return an English translation of the title and summary plus the source
    language code. Returns {story_id: {"category":..., "lang":...,
    "title_en":..., "summary_en":...}}. Batched to keep each request cheap;
    a failed batch is skipped and retried on the next run."""
    if not stories:
        return {}
    if not ANTHROPIC_API_KEY:
        print("  Warning: ANTHROPIC_API_KEY is not set -- skipping AI "
              "classification. No new stories will be categorized until "
              "this is configured.")
        return {}

    categories_block = "\n".join(
        f'- "{key}": {desc}' for key, desc in category_definitions.items()
    )

    results = {}
    batches = [stories[i:i + CLASSIFIER_BATCH_SIZE] for i in range(0, len(stories), CLASSIFIER_BATCH_SIZE)]
    for batch_num, batch in enumerate(batches, 1):
        valid_ids = {s["id"] for s in batch}
        story_lines = "\n\n".join(
            f'ID: {s["id"]}\nTITLE: {s["title"]}\nSUMMARY: {s["summary"][:200]}'
            for s in batch
        )
        prompt = f"""You are sorting power-industry news stories into a fixed set of categories for a trade news website read by utility engineers and equipment vendors. Here are the categories and exactly what each one covers:

{categories_block}

These stories come from broad news searches, so MOST of them will be irrelevant and must be assigned "None". Be strict and skeptical:
- The story must be about a real event or development in the ELECTRICAL POWER industry (utilities, the grid, substations, power plants, power equipment).
- Assign "None" to: consumer/retail energy tips, stock and earnings coverage, opinion columns, listicles, press-release marketing fluff, car fires or house fires that merely happen near power lines, weather stories that only mention outages in passing, and anything where the category topic is a passing mention rather than the subject.
- A brief local news report about a real substation or transformer incident IS relevant -- small outlets are a valid source. Judge by the event, not the size of the publication.
- A root-cause analysis or post-mortem of a failure IS a real event, even if published months later by an engineer rather than a reporter. Depth and delay do not disqualify it.
- ONE EXCEPTION to the "must be a real event" rule: this site's core subject is transformer fires and explosions, substation fires, and switchgear failures and arc-flash events. Any story on those specific subjects is relevant EVEN IF no incident occurred -- including prevention, fire suppression, rapid depressurization, explosion mitigation, and protective equipment for them. Route actual incidents to "Failures" and prevention/mitigation content to "Protections". This exception does NOT extend to general engineering guidance on other topics: an article on transformer asset management economics or a tutorial on load calculations is still "None".
- If you are unsure, choose "None".

Stories:
{story_lines}

For each story also report its language. If the title/summary are NOT in English, translate them into clear English. If they ARE already in English, set "lang" to "en" and leave the translation fields as empty strings.

Respond with ONLY a JSON array, no other text before or after it. The "id" value MUST be copied character-for-character from that story's "ID:" line above (it is a URL, not a number) -- do not invent, number, or shorten it:
[{{"id": "<exact ID from above>", "category": "<one of the category keys above, or None>", "lang": "<ISO 639-1 code, e.g. en, de, ja, es, pt, fr>", "title_en": "<English title, or empty string if already English>", "summary_en": "<English summary, or empty string if already English>"}}]
"""
        try:
            text = _call_anthropic(prompt)
            parsed = _parse_json_response(text)
            skipped_invalid = 0
            for item in parsed:
                sid = item.get("id")
                if sid not in valid_ids:
                    skipped_invalid += 1
                    continue
                cat = item.get("category")
                cat = cat if cat and cat != "None" and cat in category_definitions else None
                lang = (item.get("lang") or "en").strip().lower()[:5]
                results[sid] = {
                    "category": cat,
                    "lang": lang,
                    "title_en": (item.get("title_en") or "").strip(),
                    "summary_en": (item.get("summary_en") or "").strip(),
                }
            if skipped_invalid:
                print(f"  Warning: batch {batch_num}/{len(batches)} returned {skipped_invalid} "
                      f"id(s) that didn't match any story sent -- those stories were skipped "
                      f"and will be retried next run.")
            print(f"  Classified batch {batch_num}/{len(batches)} ({len(batch) - skipped_invalid}/{len(batch)} stories matched)")
        except Exception as e:
            print(f"  Warning: AI classification failed for batch {batch_num}/{len(batches)}: {e}")
            continue

    return results


HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text):
    """Remove HTML tags (e.g. <figure><img src="...">) from RSS summaries
    and collapse whitespace, so raw markup/long image URLs never show up
    as literal unbroken text on the story cards."""
    no_tags = HTML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", no_tags).strip()


def fetch_stories_from_feeds(feed_urls):
    """Fetch all stories currently in a list of RSS feed URLs."""
    stories = []
    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"  Could not fetch {url}: {e}")
            continue

        if parsed.bozo and not parsed.entries:
            print(f"  Warning: feed may be broken: {url}")

        is_google_news = "news.google.com" in url

        for entry in parsed.entries:
            story_id = entry.get("id") or entry.get("link")
            if not story_id:
                continue

            title = strip_html(entry.get("title", "Untitled"))
            link = entry.get("link", "#")
            summary = entry.get("summary", "")
            summary_text = strip_html(html.unescape(summary))
            source_title = parsed.feed.get("title", "Unknown source")
            published = entry.get("published", "")

            if is_google_news:
                # Google News wraps the real publisher in <source> and appends
                # " - Publisher" to every headline; recover the real publisher
                # name and strip the redundant suffix off the title.
                publisher = ""
                src = entry.get("source")
                if isinstance(src, dict):
                    publisher = src.get("title", "") or ""
                if not publisher:
                    publisher = entry.get("source_title", "") or ""
                if publisher:
                    source_title = publisher
                    if title.endswith(" - " + publisher):
                        title = title[: -(len(publisher) + 3)].strip()
                else:
                    source_title = "Google News"
                    if " - " in title:
                        title = title.rsplit(" - ", 1)[0].strip()
                # Google News summaries are just link markup -- drop them
                # rather than showing scraped junk on the card.
                if len(summary_text) < 40 or summary_text.startswith(title[:30]):
                    summary_text = ""

            stories.append({
                "id": story_id,
                "title": title,
                "link": link,
                "summary": summary_text[:300],
                "source": source_title,
                "published": published,
            })
    return stories


# ---------------------------------------------------------------------------
# Trade shows (manually maintained -- no power-industry trade show publishes
# a real feed, see tradeshows_config.json)
# ---------------------------------------------------------------------------
def load_tradeshows():
    events = load_json(TRADESHOWS_FILE, [])
    def sort_key(e):
        return e.get("start_date") or "9999-99-99"
    return sorted(events, key=sort_key)


def next_upcoming_tradeshow(events):
    today = date.today().isoformat()
    upcoming = [e for e in events if e.get("end_date", "") >= today]
    if upcoming:
        return sorted(upcoming, key=lambda e: e.get("start_date") or "9999-99-99")[0]
    return None


def format_event_dates(event):
    start = event.get("start_date", "")
    end = event.get("end_date", "")
    if not start:
        return "Date TBD"
    if end and end != start:
        return f"{start} to {end}"
    return start


def days_until(date_str):
    try:
        d = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None
    return (d - date.today()).days


def split_tradeshows(events):
    """Split events into Attend (everything still upcoming) and Exhibit
    (only events far enough out that a vendor could still realistically
    sign up for a booth -- see EXHIBIT_LEAD_DAYS)."""
    today_iso = date.today().isoformat()
    attend = [e for e in events if not e.get("end_date") or e.get("end_date", "") >= today_iso]
    exhibit = []
    for e in events:
        days = days_until(e.get("start_date", ""))
        if days is not None and days >= EXHIBIT_LEAD_DAYS:
            exhibit.append(e)
    return attend, exhibit


# ---------------------------------------------------------------------------
# Featured articles (markdown files dropped into featured_articles/)
# ---------------------------------------------------------------------------
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_featured_articles():
    articles = []
    if not os.path.isdir(FEATURED_DIR):
        return articles

    for fname in sorted(os.listdir(FEATURED_DIR)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(FEATURED_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()

        meta = {}
        body_md = raw
        m = FRONTMATTER_RE.match(raw)
        if m:
            fm_block, body_md = m.groups()
            for line in fm_block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()

        slug = slugify(os.path.splitext(fname)[0])
        title = meta.get("title", os.path.splitext(fname)[0].replace("_", " ").title())
        summary = meta.get("summary", "")
        article_date = meta.get("date", "")
        if not article_date:
            mtime = os.path.getmtime(path)
            article_date = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")

        body_html = md.markdown(body_md.strip(), extensions=["extra"])

        articles.append({
            "slug": slug,
            "title": title,
            "summary": summary,
            "date": article_date,
            "body_html": body_html,
            "url": f"featured_{slug}.html",
        })

    articles.sort(key=lambda a: a["date"], reverse=True)
    return articles


# ---------------------------------------------------------------------------
# Shared page shell: nav, SEO head tags, footer
# ---------------------------------------------------------------------------
def category_icon_img(name, cls="cat-icon"):
    """The tile art carries the category name, so alt text repeats it for
    search engines and screen readers rather than being purely decorative."""
    fname = CATEGORY_ICONS.get(name)
    if not fname:
        return f'<span class="cat-icon-fallback">{html.escape(name)}</span>'
    return (f'<img class="{cls}" src="assets/{fname}" '
            f'alt="{html.escape(name)}" width="96" height="96" loading="lazy">')


def standards_link_row(parent):
    """Quick links to the bodies whose standards this category tracks."""
    if parent != "Standards":
        return ""
    chips = "\n".join(
        f'  <a href="{url}" target="_blank" rel="noopener">{html.escape(name)}</a>'
        for name, url in STANDARDS_LINKS
    )
    return f'<div class="ref-links">\n  <span class="ref-links-label">Reference:</span>\n{chips}\n</div>'


def category_page_heading(category):
    return (f'<div class="cat-heading">{category_icon_img(category, "cat-icon-head")}'
            f'<h1 class="sr-only">{html.escape(category)}</h1></div>')


def render_nav(all_categories, active_category=None):
    links = ['<a class="home" href="index.html">Home</a>']
    for c in all_categories:
        cls = "active" if c == active_category else ""
        fname = "category_trade_shows.html" if c == TRADE_SHOWS_LABEL else f"category_{slugify(c)}.html"
        links.append(f'<a class="{cls}" href="{fname}">{html.escape(c)}</a>')
    links.append('<a href="advertise.html">Advertise With Us</a>')
    links.append('<a href="featured_archive.html">Featured</a>')
    return "\n".join(links)


def seo_head(title, description, canonical_path, og_type="website", og_image=None,
             structured_data=None):
    canonical_url = f"{BASE_URL}/{canonical_path}" if canonical_path else f"{BASE_URL}/"
    image_url = og_image or f"{BASE_URL}/assets/og-image.png"
    tags = [
        f'<link rel="canonical" href="{canonical_url}">',
        f'<meta name="description" content="{html.escape(description)}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:site_name" content="{html.escape(SITE_NAME)}">',
        f'<meta property="og:title" content="{html.escape(title)}">',
        f'<meta property="og:description" content="{html.escape(description)}">',
        f'<meta property="og:url" content="{canonical_url}">',
        f'<meta property="og:image" content="{image_url}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{html.escape(title)}">',
        f'<meta name="twitter:description" content="{html.escape(description)}">',
        f'<meta name="twitter:image" content="{image_url}">',
        '<link rel="icon" href="assets/favicon.ico">',
        '<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">',
    ]
    if structured_data:
        tags.append(
            '<script type="application/ld+json">'
            + json.dumps(structured_data)
            + '</script>'
        )
    return "\n".join(tags)


def analytics_script():
    """GoatCounter tag. Async, so it never blocks page render."""
    if not GOATCOUNTER_URL:
        return ""
    return (f'<script data-goatcounter="{html.escape(GOATCOUNTER_URL)}"\n'
            f'        async src="//gc.zgo.at/count.js"></script>')


def page_shell(title, description, canonical_path, body_html, nav_html,
               updated_line="", og_type="website", og_image=None,
               structured_data=None, show_advertise_button=False):
    full_title = title if SITE_NAME in title else f"{title} | {SITE_NAME}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(full_title)}</title>
{FONT_LINKS}
{seo_head(full_title, description, canonical_path, og_type, og_image, structured_data)}
<style>{SHARED_CSS}</style>
</head>
<body>
<header class="masthead">
  <div class="masthead-inner">
    <div class="masthead-logo-row">
      <a class="brand" href="index.html">
        <img class="brand-logo" src="assets/logo-lockup.png" alt="{html.escape(SITE_NAME)} logo">
      </a>
      {'<a class="advertise-btn" href="advertise.html">Advertise With Us</a>' if show_advertise_button else ""}
      <div class="search-wrap">
        <input type="search" id="site-search" placeholder="Search stories, events, articles...">
        <div id="search-results"></div>
      </div>
    </div>
    <p class="masthead-tagline">{html.escape(SITE_TAGLINE)}</p>
    {f'<div class="masthead-row"><nav class="catnav">{nav_html}</nav></div>' if nav_html else ""}
  </div>
</header>
<div class="diagram-rule"></div>
<div class="ad-banner">Your advertisement could be here</div>
<main>
{updated_line}
{body_html}
<footer class="site-footer">
  <p>{SPONSOR_DISCLOSURE_HTML}</p>
  <p class="footer-links"><a href="terms.html">Terms</a> &middot; <a href="privacy.html">Privacy Policy</a></p>
</footer>
</main>
{SEARCH_SCRIPT}
{analytics_script()}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Simple category (news) pages -- e.g. Failures, Protection, Insurance
# ---------------------------------------------------------------------------
def render_story_cards(stories, color):
    if not stories:
        return ('<div class="empty-state">No new stories yet. '
                'Check back after the next update.</div>')
    cards = []
    for s in stories[:MAX_STORIES_PER_CATEGORY]:
        clean_title = strip_html(s['title'])
        clean_summary = strip_html(s['summary'])
        lang = (s.get('lang') or '').strip()
        lang_tag = (f'<span class="lang-tag" title="Original article is in this language">'
                    f'{html.escape(lang.upper())}</span>') if lang and lang != 'en' else ''
        summary_html = f"<p>{html.escape(clean_summary)}&hellip;</p>" if clean_summary else ""
        cards.append(f"""<div class="story" style="--accent:{color['accent']}">
  <h3><a href="{html.escape(s['link'])}" target="_blank" rel="noopener">{html.escape(clean_title)}</a>{lang_tag}</h3>
  <p class="meta">{html.escape(s['source'])} &middot; {html.escape(s['published'])}</p>
  {summary_html}
</div>""")
    return "\n".join(cards)


def render_category_page(category, stories, all_categories):
    color = category_color(category)
    nav_html = render_nav(all_categories, active_category=category)
    description = get_category_description(category)
    items_html = render_story_cards(stories, color)

    structured_data = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"{category} News",
        "description": description,
        "url": f"{BASE_URL}/category_{slugify(category)}.html",
        "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": BASE_URL},
    }

    body = f"""{category_page_heading(category)}
<p class="category-intro">{html.escape(description)}</p>
{items_html}"""

    return page_shell(
        f"{category} News", description, f"category_{slugify(category)}.html",
        body, nav_html, og_type="website", structured_data=structured_data,
    )


# ---------------------------------------------------------------------------
# Compound category pages -- Installations, Standards (broken into
# subcategory sections on a single page)
# ---------------------------------------------------------------------------
def render_compound_category_page(parent, sub_stories, all_categories):
    nav_html = render_nav(all_categories, active_category=parent)
    description = get_category_description(parent)
    top_color = category_color(parent)

    sections = []
    for sub_name, stories in sub_stories.items():
        color = category_color(sub_name)
        sub_desc = SUBCATEGORY_DESCRIPTIONS.get(sub_name, "")
        items_html = render_story_cards(stories, color)
        intro_html = f'<p class="category-intro">{html.escape(sub_desc)}</p>' if sub_desc else ""
        sections.append(f"""<section class="subcategory-block">
  <h2 style="border-bottom:2px solid {color['accent']}; padding-bottom:8px;">{html.escape(sub_name)}</h2>
  {intro_html}
  {items_html}
</section>""")

    structured_data = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"{parent} News",
        "description": description,
        "url": f"{BASE_URL}/category_{slugify(parent)}.html",
        "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": BASE_URL},
    }

    body = f"""{category_page_heading(parent)}
{standards_link_row(parent)}
<p class="category-intro">{html.escape(description)}</p>
{''.join(sections)}"""

    return page_shell(
        f"{parent} News", description, f"category_{slugify(parent)}.html",
        body, nav_html, structured_data=structured_data,
    )


# ---------------------------------------------------------------------------
# Trade shows page (Attend / Exhibit)
# ---------------------------------------------------------------------------
def render_event_cards(events, color):
    if not events:
        return '<div class="empty-state">No events listed right now.</div>'
    cards = []
    for e in events:
        cards.append(f"""<div class="event-card" style="--accent:{color['accent']}">
  <h3><a href="{html.escape(e.get('link','#'))}" target="_blank" rel="noopener">{html.escape(e.get('name','Untitled Event'))}</a></h3>
  <p class="meta">{html.escape(format_event_dates(e))} &middot; {html.escape(e.get('location','Location TBD'))}</p>
</div>""")
    return "\n".join(cards)


def render_tradeshows_page(events, all_categories):
    color = category_color(TRADE_SHOWS_LABEL)
    nav_html = render_nav(all_categories, active_category=TRADE_SHOWS_LABEL)
    description = get_category_description(TRADE_SHOWS_LABEL)
    attend, exhibit = split_tradeshows(events)

    structured_data = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Trade Shows",
        "description": description,
        "url": f"{BASE_URL}/category_trade_shows.html",
    }

    body = f"""{category_page_heading(TRADE_SHOWS_LABEL)}
<p class="category-intro">{html.escape(description)}</p>
<section class="subcategory-block">
  <h2 style="border-bottom:2px solid {color['accent']}; padding-bottom:8px;">Attend</h2>
  <p class="category-intro">Upcoming power industry trade shows and conferences.</p>
  {render_event_cards(attend, color)}
</section>
<section class="subcategory-block">
  <h2 style="border-bottom:2px solid {color['accent']}; padding-bottom:8px;">Exhibit</h2>
  <p class="category-intro">Shows that still have enough lead time to apply for a vendor booth.</p>
  {render_event_cards(exhibit, color)}
</section>"""

    return page_shell(
        "Trade Shows", description, "category_trade_shows.html",
        body, nav_html, structured_data=structured_data,
    )


# ---------------------------------------------------------------------------
# Featured article pages
# ---------------------------------------------------------------------------
def render_featured_article_page(article, all_categories):
    nav_html = render_nav(all_categories, active_category=None)
    description = article["summary"] or f"{article['title']} -- {SITE_NAME}"

    structured_data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article["title"],
        "datePublished": article["date"],
        "author": {"@type": "Organization", "name": SITE_NAME},
        "publisher": {"@type": "Organization", "name": SITE_NAME},
        "url": f"{BASE_URL}/{article['url']}",
    }

    body = f"""<article>
  <p class="meta" style="font-family:'IBM Plex Mono',monospace; text-transform:uppercase; color:var(--muted); font-size:12px;">Featured &middot; {html.escape(article['date'])}</p>
  <h1 style="margin-top:6px;">{html.escape(article['title'])}</h1>
  <div class="article-body">{article['body_html']}</div>
</article>"""

    return page_shell(
        article["title"], description, article["url"],
        body, nav_html, og_type="article", structured_data=structured_data,
    )


def render_featured_archive_page(articles, all_categories):
    nav_html = render_nav(all_categories, active_category=None)
    description = "Original editorial articles and analysis from Power Industry News."

    if not articles:
        items_html = '<div class="empty-state">No featured articles yet.</div>'
    else:
        rows = []
        for a in articles:
            rows.append(f"""<a href="{a['url']}">
  <h3>{html.escape(a['title'])}</h3>
  <p class="meta">{html.escape(a['date'])}</p>
</a>""")
        items_html = f'<div class="archive-list">{"".join(rows)}</div>'

    body = f"""{category_page_heading("Featured")}
<p class="category-intro">{html.escape(description)}</p>
{items_html}"""

    return page_shell(
        "Featured Articles", description, "featured_archive.html",
        body, nav_html,
    )


# ---------------------------------------------------------------------------
# Advertise / Terms / Privacy pages
# ---------------------------------------------------------------------------
def render_advertise_page(all_categories):
    nav_html = render_nav(all_categories, active_category=None)
    description = ("Advertise with Power Industry News -- reach electrical "
                    "power industry engineers, utility decision-makers, and "
                    "safety teams.")

    if ADVERTISE_FORM_EMBED_URL:
        form_html = (f'<iframe src="{html.escape(ADVERTISE_FORM_EMBED_URL)}" '
                     f'width="100%" height="1100" frameborder="0">Loading '
                     f'form&hellip;</iframe>')
    else:
        # Deliberately no mailto: link here -- a plain address on a public
        # page gets harvested by spam crawlers within days. Until the Google
        # Form URL is set in ADVERTISE_FORM_EMBED_URL, show a neutral notice.
        form_html = (
            '<div class="empty-state">The advertising inquiry form is being '
            'set up and will be available here shortly. Please check back '
            'soon.</div>'
        )

    body = f"""<h1 style="border-bottom:3px solid var(--copper); padding-bottom:10px; margin-top:0;">Advertise With Us</h1>
<p class="category-intro">Reach electrical power industry engineers, utility decision-makers, and safety teams. Send us your name, email address, and phone number, and we&rsquo;ll follow up with rates and available placements.</p>
<div class="advertise-form">{form_html}</div>"""

    return page_shell("Advertise With Us", description, "advertise.html", body, nav_html)


def render_terms_page(all_categories):
    nav_html = render_nav(all_categories, active_category=None)
    description = f"Terms of use for {SITE_NAME}, operated by {BUSINESS_NAME}."
    updated = datetime.now(timezone.utc).strftime("%B %Y")

    body = f"""<h1 style="border-bottom:3px solid var(--copper); padding-bottom:10px; margin-top:0;">Terms of Service</h1>
<p class="category-intro">Last updated: {updated}</p>
<div class="article-body">
<h2>About This Site</h2>
<p>{html.escape(SITE_NAME)} is an independent news aggregator operated by {html.escape(BUSINESS_NAME)} ("we," "us"). We collect and link to publicly available news stories, industry standards updates, and event listings relevant to the electrical power industry. We do not author most of the linked content, and a link to a third-party story is not an endorsement of that source or its accuracy.</p>
<h2>Use of the Site</h2>
<p>You're welcome to browse, search, and share links from this site. Please don't scrape, republish, or redistribute the site's content or design in bulk without our permission.</p>
<h2>Third-Party Content and Links</h2>
<p>Story links, trade show listings, and other references on this site lead to third-party websites we don't control. We aren't responsible for the content, accuracy, or practices of those external sites.</p>
<h2>Advertising</h2>
<p>We may display sponsored placements or advertisements on this site. Interest in advertising can be submitted through our <a href="advertise.html">Advertise With Us</a> page. Advertising placements don't imply our endorsement of any advertiser's products or services.</p>
<h2>No Warranty</h2>
<p>This site and its content are provided "as is," without warranties of any kind. We make no guarantee that the information here is complete, current, or error-free.</p>
<h2>Limitation of Liability</h2>
<p>To the fullest extent permitted by law, {html.escape(BUSINESS_NAME)} is not liable for any damages arising from your use of this site or reliance on any information found here.</p>
<h2>Changes to These Terms</h2>
<p>We may update these terms from time to time. Continued use of the site after changes means you accept the updated terms.</p>
<h2>Governing Law</h2>
<p>These terms are governed by the laws of the State of {html.escape(GOVERNING_STATE)}, without regard to conflict-of-law principles.</p>
<h2>Contact</h2>
<p>Questions about these terms? Use the <a href="advertise.html">contact form</a>.</p>
</div>"""

    return page_shell("Terms of Service", description, "terms.html", body, nav_html)


def render_privacy_page(all_categories):
    nav_html = render_nav(all_categories, active_category=None)
    description = f"Privacy policy for {SITE_NAME}, operated by {BUSINESS_NAME}."
    updated = datetime.now(timezone.utc).strftime("%B %Y")

    body = f"""<h1 style="border-bottom:3px solid var(--copper); padding-bottom:10px; margin-top:0;">Privacy Policy</h1>
<p class="category-intro">Last updated: {updated}</p>
<div class="article-body">
<h2>What We Collect</h2>
<p>{html.escape(SITE_NAME)} doesn't use accounts and doesn't ask you for any personal information just to read the site. Our web host (GitHub Pages) may log basic technical request data (like IP address and browser type) as part of standard hosting operations, which we don't have direct access to.</p>
<h2>Visitor Statistics</h2>
<p>We use <a href="https://www.goatcounter.com" target="_blank" rel="noopener">GoatCounter</a>, a privacy-focused analytics tool, to count how many people visit the site and which pages they read. GoatCounter does not use cookies, does not track you across other websites, and does not collect or store personal information that identifies you individually. We use these aggregate numbers only to understand readership and to describe our audience to prospective advertisers. You can read GoatCounter's <a href="https://www.goatcounter.com/help/privacy" target="_blank" rel="noopener">privacy policy</a> for details on what it records.</p>
<h2>Advertise With Us Form</h2>
<p>If you submit an inquiry through our <a href="advertise.html">Advertise With Us</a> page, that form is hosted by Google Forms, and your name, email address, and phone number are submitted directly to Google and to us. That submission is subject to <a href="https://policies.google.com/privacy" target="_blank" rel="noopener">Google's Privacy Policy</a>. We use the information you submit only to follow up about advertising opportunities.</p>
<h2>Third-Party Links</h2>
<p>This site links to third-party news sources, trade show pages, and other external websites. Those sites have their own privacy practices, which we don't control.</p>
<h2>Changes to This Policy</h2>
<p>We may update this policy from time to time. Changes will be posted on this page.</p>
<h2>Contact</h2>
<p>Questions about this policy? Use the <a href="advertise.html">contact form</a>.</p>
</div>"""

    return page_shell("Privacy Policy", description, "privacy.html", body, nav_html)


# ---------------------------------------------------------------------------
# Homepage
# ---------------------------------------------------------------------------
def render_index_page(top_level_names, story_counts, last_updated, tradeshows, featured_articles):
    all_categories = top_level_names + [TRADE_SHOWS_LABEL]

    # --- Featured spotlight + Next Upcoming Trade Show callout ---
    feature_blocks = []
    if featured_articles:
        latest = featured_articles[0]
        feature_blocks.append(f"""<div class="spotlight-card">
  <p class="eyebrow">Featured</p>
  <h2>{html.escape(latest['title'])}</h2>
  <p>{html.escape(latest['summary'] or '')}</p>
  <a class="readmore" href="{latest['url']}">Read the full article &rarr;</a>
</div>""")

    next_event = next_upcoming_tradeshow(tradeshows)
    next_event_html = ""
    if next_event:
        next_event_html = f"""<a class="next-event" href="{html.escape(next_event.get('link','#'))}" target="_blank" rel="noopener">
  <span class="next-event-tag">Next Event</span>
  <span class="next-event-name">{html.escape(next_event.get('name','Untitled Event'))}</span>
  <span class="next-event-meta">{html.escape(format_event_dates(next_event))} &middot; {html.escape(next_event.get('location','Location TBD'))}</span>
  <span class="next-event-arrow">&rarr;</span>
</a>"""

    row_class = "feature-row has-both" if len(feature_blocks) == 2 else "feature-row"
    feature_row_html = f'<div class="{row_class}">{"".join(feature_blocks)}</div>' if feature_blocks else ""

    # --- category grid, including Trade Shows ---
    cards = []
    for c in top_level_names:
        color = category_color(c)
        count = story_counts.get(c, 0)
        cards.append(f"""<a class="cat-card" style="--accent:{color['accent']}" href="category_{slugify(c)}.html">
  {category_icon_img(c)}
  <span class="sr-only">{html.escape(c)}</span>
  <p>{count} stories tracked</p>
</a>""")

    ts_color = category_color(TRADE_SHOWS_LABEL)
    cards.append(f"""<a class="cat-card" style="--accent:{ts_color['accent']}" href="category_trade_shows.html">
  {category_icon_img(TRADE_SHOWS_LABEL)}
  <span class="sr-only">{html.escape(TRADE_SHOWS_LABEL)}</span>
  <p>{len(tradeshows)} events listed</p>
</a>""")

    # Featured tile. The spotlight card above promotes the newest article by
    # name; this tile is the way into the whole archive, which otherwise was
    # only reachable from the interior-page nav.
    feat_color = category_color("Featured")
    article_word = "article" if len(featured_articles) == 1 else "articles"
    cards.append(f"""<a class="cat-card" style="--accent:{feat_color['accent']}" href="featured_archive.html">
  {category_icon_img("Featured")}
  <span class="sr-only">Featured</span>
  <p>{len(featured_articles)} {article_word}</p>
</a>""")

    body = f"""{next_event_html}
{feature_row_html}
<div class="cat-grid">
{''.join(cards)}
</div>"""

    updated_line = f'<p class="updated">Last updated: {html.escape(last_updated)}</p>'
    # The homepage shows the category tiles below, so a nav bar would only
    # repeat them. Interior pages still render it -- it is their only way out.
    nav_html = ""

    structured_data = {
        "@context": "https://schema.org",
        "@type": "NewsMediaOrganization",
        "name": SITE_NAME,
        "url": BASE_URL,
        "description": SITE_TAGLINE,
        "logo": f"{BASE_URL}/assets/apple-touch-icon.png",
    }

    return page_shell(
        SITE_NAME, SITE_TAGLINE, "", body, nav_html,
        updated_line=updated_line, structured_data=structured_data,
        show_advertise_button=True,   # homepage only -- interior pages have it in the nav
    )


# ---------------------------------------------------------------------------
# Search index, sitemap, robots.txt, assets/CNAME persistence
# ---------------------------------------------------------------------------
def leaf_label(leaf_key):
    """Turn an internal store key ('Installations::Generation') into a
    readable label ('Installations — Generation') for search results."""
    return leaf_key.replace("::", " \u2014 ")


def build_search_index(store, classification_cache, tradeshows, featured_articles):
    index = []
    for sid, s in store.items():
        leaf_key = cache_category(classification_cache.get(sid)) or ""
        label = leaf_label(leaf_key)
        index.append({
            "title": strip_html(s["title"]),
            "url": s["link"],
            "category": label,
            "source": s.get("source", ""),
            "summary": strip_html(s.get("summary", ""))[:160],
        })
    for e in tradeshows:
        index.append({
            "title": e.get("name", "Untitled Event"),
            "url": e.get("link", "#"),
            "category": TRADE_SHOWS_LABEL,
            "source": "Trade Show",
            "summary": e.get("location", ""),
        })
    for a in featured_articles:
        index.append({
            "title": a["title"],
            "url": a["url"],
            "category": "Featured",
            "source": SITE_NAME,
            "summary": a.get("summary", ""),
        })
    with open(os.path.join(OUTPUT_DIR, "search-index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)


def build_sitemap(page_paths):
    urls = "".join(
        f"<url><loc>{BASE_URL}/{p}</loc></url>\n" for p in page_paths
    )
    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}</urlset>
"""
    with open(os.path.join(OUTPUT_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sitemap)


def build_robots():
    content = f"""User-agent: *
Allow: /

Sitemap: {BASE_URL}/sitemap.xml
"""
    with open(os.path.join(OUTPUT_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(content)


def copy_assets_and_cname():
    """Copy the logo/favicon assets and write the CNAME file into site/ on
    every build. Both would otherwise get wiped by the hourly workflow,
    which does `rm -rf docs && cp -r site docs`."""
    if os.path.isdir(ASSETS_SRC_DIR):
        dest = os.path.join(OUTPUT_DIR, "assets")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(ASSETS_SRC_DIR, dest)
    else:
        print(f"  Warning: {ASSETS_SRC_DIR}/ not found -- logo/favicon links will 404 "
              f"until you add it.")

    domain = BASE_URL.replace("https://", "").replace("http://", "").rstrip("/")
    with open(os.path.join(OUTPUT_DIR, "CNAME"), "w", encoding="utf-8") as f:
        f.write(domain + "\n")


def _load_known_stories(path):
    """Load the persistent story pool as a flat {story_id: story_dict} map.
    Also transparently migrates the old per-bucket-list format (used before
    this fix) into the flat format, so no historical data is lost."""
    raw = load_json(path, {})
    if not raw:
        return {}
    first_value = next(iter(raw.values()))
    if isinstance(first_value, list):
        # legacy format: {leaf_key: [story, story, ...]} -- flatten it
        flat = {}
        for stories in raw.values():
            for s in stories:
                flat[s["id"]] = s
        return flat
    return raw  # already flat


ALERT_WINDOW_MIN_DAYS = 120   # start pitching this far out
ALERT_WINDOW_MAX_DAYS = 180   # ...and stop once the event is nearer than this


def write_tradeshow_alert(tradeshows):
    """Write alert.md listing events entering the sponsorship-outreach window.
    The GitHub Action turns this into an issue, which GitHub emails to you.
    Writes nothing when no event qualifies, so no empty issues get opened."""
    due = []
    for e in tradeshows:
        d = days_until(e.get("start_date", ""))
        if d is not None and ALERT_WINDOW_MIN_DAYS <= d <= ALERT_WINDOW_MAX_DAYS:
            due.append((d, e))
    if not due:
        if os.path.exists("alert.md"):
            os.remove("alert.md")
        print("  No trade shows in the sponsor-outreach window")
        return False

    due.sort()
    lines = ["These events are entering the window where sponsor and exhibitor "
             "packages are usually still open.", ""]
    for d, e in due:
        lines.append(f"### {e.get('name', 'Untitled Event')}")
        lines.append(f"- **Starts in:** {d} days ({format_event_dates(e)})")
        lines.append(f"- **Location:** {e.get('location', 'TBD')}")
        lines.append(f"- **Event page:** {e.get('link', 'n/a')}")
        contact = e.get("sponsorship_contact")
        lines.append(f"- **Sponsorship contact:** {contact if contact else 'not on file yet'}")
        lines.append("")
    with open("alert.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  {len(due)} trade show(s) entering the sponsor window -> alert.md")
    return True


def main():
    print("Starting news aggregation run...")
    raw_config = load_json(CONFIG_FILE, {})
    feed_urls = load_feed_urls(raw_config)
    if not feed_urls:
        print(f"ERROR: no feed URLs found in {CONFIG_FILE}. Add your feeds there first.")
        return

    previously_known = _load_known_stories(STORE_FILE)                 # story id -> story dict
    classification_cache = migrate_classification_cache(load_json(CLASSIFICATION_CACHE_FILE, {}))    # story id -> leaf_key or None
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    top_level_names = list(TOP_LEVEL_STRUCTURE.keys())
    page_paths = ["index.html"]

    # --- fetch every feed once, dedupe by story id ---
    print(f"Fetching {len(feed_urls)} feed(s)...")
    fetched_stories = fetch_stories_from_feeds(feed_urls)
    fetched_by_id = {s["id"]: s for s in fetched_stories}
    print(f"  {len(fetched_by_id)} stories currently live in the feeds")

    # --- classify only stories we've truly never seen before ---
    new_stories = [s for sid, s in fetched_by_id.items() if sid not in classification_cache]
    if len(new_stories) > MAX_NEW_CLASSIFICATIONS_PER_RUN:
        print(f"  {len(new_stories)} unclassified stories found -- capping this run at "
              f"{MAX_NEW_CLASSIFICATIONS_PER_RUN}; the rest carry over to the next run.")
        new_stories = new_stories[:MAX_NEW_CLASSIFICATIONS_PER_RUN]
    print(f"Classifying {len(new_stories)} new story(ies) with AI...")
    new_classifications = classify_stories_with_ai(new_stories, CATEGORY_DEFINITIONS)
    classification_cache.update(new_classifications)
    save_json(CLASSIFICATION_CACHE_FILE, classification_cache)

    # Fresh feed data wins over older cached copies of the same story (keeps
    # titles/summaries current); previously-known stories fill in anything
    # that has since scrolled off the live RSS feed but is still classified.
    all_known = dict(previously_known)
    all_known.update(fetched_by_id)

    # --- rebuild every category completely from the CURRENT classification
    # cache -- this is what makes a reclassification (or a bug fix) actually
    # take effect, instead of old bucket assignments lingering forever ---
    buckets = {}
    for sid, story in all_known.items():
        entry = classification_cache.get(sid)
        leaf_key = cache_category(entry)
        if not leaf_key:
            continue
        # Foreign-language stories display with Claude's English translation
        # and a language tag; the link still points at the original article.
        if isinstance(entry, dict) and entry.get("lang", "en") != "en":
            story = dict(story)
            story["lang"] = entry.get("lang", "")
            if entry.get("title_en"):
                story["title"] = entry["title_en"]
            if entry.get("summary_en"):
                story["summary"] = entry["summary_en"]
        buckets.setdefault(leaf_key, []).append(story)

    story_counts = {}
    kept_story_ids = set()
    for name, info in TOP_LEVEL_STRUCTURE.items():
        if info["compound"]:
            sub_stories_for_page = {}
            total_count = 0
            for sub_name in info["subcategories"]:
                leaf_key = f"{name}::{sub_name}"
                merged_list = buckets.get(leaf_key, [])
                merged_list.sort(key=lambda s: s["published"], reverse=True)
                merged_list = merged_list[:STORIES_PER_CATEGORY]
                kept_story_ids.update(s["id"] for s in merged_list)
                sub_stories_for_page[sub_name] = merged_list
                total_count += len(merged_list)
                print(f"  {name} -> {sub_name}: {len(merged_list)} stories")

            page_html = render_compound_category_page(name, sub_stories_for_page, top_level_names)
            fname = f"category_{slugify(name)}.html"
            with open(os.path.join(OUTPUT_DIR, fname), "w", encoding="utf-8") as f:
                f.write(page_html)
            page_paths.append(fname)
            story_counts[name] = total_count

        else:
            leaf_key = name
            merged_list = buckets.get(leaf_key, [])
            merged_list.sort(key=lambda s: s["published"], reverse=True)
            merged_list = merged_list[:STORIES_PER_CATEGORY]
            kept_story_ids.update(s["id"] for s in merged_list)

            page_html = render_category_page(name, merged_list, top_level_names)
            fname = f"category_{slugify(name)}.html"
            with open(os.path.join(OUTPUT_DIR, fname), "w", encoding="utf-8") as f:
                f.write(page_html)
            page_paths.append(fname)
            story_counts[name] = len(merged_list)
            print(f"  {name}: {len(merged_list)} stories")

    # Persist only the full story data we're actually still displaying
    # somewhere, so this file doesn't grow forever. The classification
    # cache itself is kept in full (it's tiny) so a story is never
    # reclassified twice even after it ages out of every category.
    store = {sid: all_known[sid] for sid in kept_story_ids}

    save_json(STORE_FILE, store)

    # --- trade shows ---
    print("Building Trade Shows page...")
    tradeshows = load_tradeshows()
    write_tradeshow_alert(tradeshows)
    ts_html = render_tradeshows_page(tradeshows, top_level_names)
    with open(os.path.join(OUTPUT_DIR, "category_trade_shows.html"), "w", encoding="utf-8") as f:
        f.write(ts_html)
    page_paths.append("category_trade_shows.html")

    # --- featured articles ---
    print("Building Featured articles...")
    featured_articles = parse_featured_articles()
    for article in featured_articles:
        article_html = render_featured_article_page(article, top_level_names)
        with open(os.path.join(OUTPUT_DIR, article["url"]), "w", encoding="utf-8") as f:
            f.write(article_html)
        page_paths.append(article["url"])

    archive_html = render_featured_archive_page(featured_articles, top_level_names)
    with open(os.path.join(OUTPUT_DIR, "featured_archive.html"), "w", encoding="utf-8") as f:
        f.write(archive_html)
    page_paths.append("featured_archive.html")

    # --- advertise / terms / privacy ---
    print("Building Advertise, Terms, and Privacy pages...")
    advertise_html = render_advertise_page(top_level_names)
    with open(os.path.join(OUTPUT_DIR, "advertise.html"), "w", encoding="utf-8") as f:
        f.write(advertise_html)
    page_paths.append("advertise.html")

    terms_html = render_terms_page(top_level_names)
    with open(os.path.join(OUTPUT_DIR, "terms.html"), "w", encoding="utf-8") as f:
        f.write(terms_html)
    page_paths.append("terms.html")

    privacy_html = render_privacy_page(top_level_names)
    with open(os.path.join(OUTPUT_DIR, "privacy.html"), "w", encoding="utf-8") as f:
        f.write(privacy_html)
    page_paths.append("privacy.html")

    # --- homepage ---
    last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    index_html = render_index_page(top_level_names, story_counts, last_updated, tradeshows, featured_articles)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    # --- search index, sitemap, robots, assets/CNAME ---
    print("Building search index, sitemap, robots.txt...")
    build_search_index(store, classification_cache, tradeshows, featured_articles)
    build_sitemap(page_paths)
    build_robots()
    copy_assets_and_cname()

    print(f"Done. Open {OUTPUT_DIR}/index.html in your browser to view the site.")


if __name__ == "__main__":
    main()
