#!/usr/bin/env python3
"""
Klipper Knowledge-Base Scraper — Harvests debugging knowledge from Klipper's
GitHub issues and the community forums (Discourse) into a local markdown
corpus that Graphify ingests into the knowledge graph.

Sources:
  • GitHub issues — Klipper3d/klipper, Arksine/moonraker, mainsail-crew/mainsail,
    OctoPrint/OctoPrint (configurable; set GITHUB_TOKEN to raise rate limits)
  • Discourse forums — klipper.discourse.group (official Klipper forum),
    community.octoprint.org

Each issue/topic becomes one markdown file under agent-data/knowledge-base/
with metadata headers, the original post, and the top answers — a format
Graphify extracts into entities and relationships.

Usage:
    # Scrape everything with defaults (200 items per source)
    python klipper_kb_scraper.py --source all

    # Targeted scrape for a symptom you're debugging
    python klipper_kb_scraper.py --source all --query "timer too close"
    python klipper_kb_scraper.py --source github --query "mcu shutdown" --max 50
    python klipper_kb_scraper.py --source discourse --query "tmc5160" --max 30

    # Specific repos / labels
    python klipper_kb_scraper.py --source github --repos Klipper3d/klipper --labels bug
    python klipper_kb_scraper.py --stats
"""

import argparse
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. pip install requests", file=sys.stderr)
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = REPO_ROOT / "agent-data" / "knowledge-base"

DEFAULT_REPOS = [
    "Klipper3d/klipper",
    "Arksine/moonraker",
    "mainsail-crew/mainsail",
    "OctoPrint/OctoPrint",
]

DEFAULT_FORUMS = [
    "klipper.discourse.group",
    "community.octoprint.org",
]

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
USER_AGENT = "klipper-kb-scraper/1.0"
MAX_COMMENTS_PER_ISSUE = 10
MAX_POSTS_PER_TOPIC = 12


# ── Helpers ───────────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Convert Discourse 'cooked' HTML to readable plain text (no bs4 needed)."""

    BLOCK_TAGS = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "blockquote"}

    def __init__(self):
        super().__init__()
        self.parts: list = []
        self._in_pre = False

    def handle_starttag(self, tag, attrs):
        if tag in ("pre", "code"):
            self._in_pre = tag == "pre"
            if tag == "pre":
                self.parts.append("\n```\n")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "pre":
            self._in_pre = False
            self.parts.append("\n```\n")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html or "")
        return parser.text()
    except Exception:
        return re.sub(r"<[^>]+>", "", html or "")


def slugify(title: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "untitled").lower()).strip("-")
    return slug[:max_len] or "untitled"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _get_json(session: requests.Session, url: str, params: dict = None,
              headers: dict = None, retries: int = 3):
    """GET JSON with basic rate-limit backoff."""
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, headers=headers or {}, timeout=30)
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                wait = 2 ** (attempt + 2)
                print(f"    rate-limited, waiting {wait}s "
                      f"(set GITHUB_TOKEN to raise limits)...", file=sys.stderr)
                time.sleep(wait)
                continue
            if resp.status_code == 429:
                time.sleep(2 ** (attempt + 2))
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f"    FAILED {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 ** attempt)
    return None


# ── GitHub issues ─────────────────────────────────────────────────────────────

def scrape_github(repos: list, query: str, labels: str, state: str,
                  max_items: int, output: Path) -> int:
    session = _session()
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    saved = 0
    for repo in repos:
        out_dir = output / "github" / repo.replace("/", "__")
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"→ GitHub {repo}" + (f" query='{query}'" if query else ""))

        issues: list = []
        if query:
            # Search API — targeted scrape
            q = f"repo:{repo} is:issue {query}"
            if labels:
                q += f" label:{labels}"
            page = 1
            while len(issues) < max_items:
                data = _get_json(session, "https://api.github.com/search/issues",
                                 params={"q": q, "per_page": min(100, max_items),
                                         "page": page, "sort": "reactions"},
                                 headers=headers)
                items = (data or {}).get("items", [])
                if not items:
                    break
                issues.extend(items)
                page += 1
        else:
            # List API — bulk scrape, most-commented first (richest debugging threads)
            page = 1
            while len(issues) < max_items:
                data = _get_json(session, f"https://api.github.com/repos/{repo}/issues",
                                 params={"state": state, "per_page": 100, "page": page,
                                         "sort": "comments", "direction": "desc",
                                         **({"labels": labels} if labels else {})},
                                 headers=headers)
                if not data:
                    break
                items = [i for i in data if "pull_request" not in i]
                if not items and not data:
                    break
                issues.extend(items)
                if len(data) < 100:
                    break
                page += 1

        for issue in issues[:max_items]:
            number = issue.get("number")
            path = out_dir / f"{number:06d}-{slugify(issue.get('title', ''))}.md"
            if path.exists():
                continue
            comments_md = ""
            if issue.get("comments", 0) and issue.get("comments_url"):
                comments = _get_json(session, issue["comments_url"],
                                     params={"per_page": MAX_COMMENTS_PER_ISSUE},
                                     headers=headers) or []
                for c in comments:
                    comments_md += (f"\n## Comment by {c.get('user', {}).get('login', '?')}\n\n"
                                    f"{(c.get('body') or '').strip()}\n")
            labels_str = ", ".join(l.get("name", "") for l in issue.get("labels", []))
            path.write_text(
                f"# {issue.get('title', 'untitled')}\n\n"
                f"- Source: GitHub issue {repo}#{number}\n"
                f"- URL: {issue.get('html_url')}\n"
                f"- State: {issue.get('state')}\n"
                f"- Labels: {labels_str or 'none'}\n"
                f"- Created: {issue.get('created_at')}\n\n"
                f"## Original report\n\n{(issue.get('body') or '').strip()}\n"
                f"{comments_md}",
                encoding="utf-8")
            saved += 1
            time.sleep(0.3 if GITHUB_TOKEN else 1.0)
        print(f"  saved {saved} file(s) so far")
    return saved


# ── Discourse forums ──────────────────────────────────────────────────────────

def scrape_discourse(forums: list, query: str, max_items: int, output: Path) -> int:
    session = _session()
    saved = 0
    for forum in forums:
        base = f"https://{forum}"
        out_dir = output / "discourse" / forum
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"→ Discourse {forum}" + (f" query='{query}'" if query else ""))

        topic_ids: list = []
        if query:
            data = _get_json(session, f"{base}/search.json",
                             params={"q": query}) or {}
            topic_ids = [t.get("id") for t in data.get("topics", [])][:max_items]
        else:
            page = 0
            while len(topic_ids) < max_items:
                data = _get_json(session, f"{base}/top.json",
                                 params={"period": "all", "page": page}) or {}
                topics = data.get("topic_list", {}).get("topics", [])
                if not topics:
                    break
                topic_ids.extend(t.get("id") for t in topics)
                page += 1

        for tid in topic_ids[:max_items]:
            if tid is None:
                continue
            existing = list(out_dir.glob(f"{tid:08d}-*.md"))
            if existing:
                continue
            topic = _get_json(session, f"{base}/t/{tid}.json")
            if not topic:
                continue
            title = topic.get("title", "untitled")
            posts = topic.get("post_stream", {}).get("posts", [])[:MAX_POSTS_PER_TOPIC]
            body_md = ""
            for i, post in enumerate(posts):
                who = post.get("display_username") or post.get("username", "?")
                role = "Original post" if i == 0 else f"Reply by {who}"
                accepted = " ✓ ACCEPTED ANSWER" if post.get("accepted_answer") else ""
                body_md += f"\n## {role}{accepted}\n\n{html_to_text(post.get('cooked', ''))}\n"
            path = out_dir / f"{tid:08d}-{slugify(title)}.md"
            path.write_text(
                f"# {title}\n\n"
                f"- Source: Discourse topic {forum}/t/{tid}\n"
                f"- URL: {base}/t/{tid}\n"
                f"- Category: {topic.get('category_id')}\n"
                f"- Created: {topic.get('created_at')}\n"
                f"{body_md}",
                encoding="utf-8")
            saved += 1
            time.sleep(0.5)
        print(f"  saved {saved} file(s) so far")
    return saved


# ── Stats ─────────────────────────────────────────────────────────────────────

def print_stats(output: Path) -> None:
    if not output.exists():
        print(f"No corpus yet at {output} — run a scrape first.")
        return
    total = 0
    for sub in sorted(output.rglob("*")):
        if sub.is_dir():
            count = len(list(sub.glob("*.md")))
            if count:
                print(f"  {sub.relative_to(output)}: {count} document(s)")
                total += count
    print(f"\nTotal: {total} document(s) in {output}")
    print("Next: python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --build")


def main():
    parser = argparse.ArgumentParser(description="Scrape Klipper GitHub issues + forums into a Graphify corpus")
    parser.add_argument("--source", default="all", choices=["all", "github", "discourse"])
    parser.add_argument("--query", default="", help="Targeted search query (recommended)")
    parser.add_argument("--repos", default=",".join(DEFAULT_REPOS),
                        help="Comma-separated owner/repo list")
    parser.add_argument("--forums", default=",".join(DEFAULT_FORUMS),
                        help="Comma-separated Discourse hosts")
    parser.add_argument("--labels", default="", help="GitHub label filter")
    parser.add_argument("--state", default="all", choices=["all", "open", "closed"])
    parser.add_argument("--max", type=int, default=200, help="Max items per repo/forum")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Corpus output directory")
    parser.add_argument("--stats", action="store_true", help="Show corpus statistics and exit")
    args = parser.parse_args()

    output = Path(args.output)
    if args.stats:
        print_stats(output)
        return

    output.mkdir(parents=True, exist_ok=True)
    total = 0
    if args.source in ("all", "github"):
        repos = [r.strip() for r in args.repos.split(",") if r.strip()]
        total += scrape_github(repos, args.query, args.labels, args.state,
                               args.max, output)
    if args.source in ("all", "discourse"):
        forums = [f.strip() for f in args.forums.split(",") if f.strip()]
        total += scrape_discourse(forums, args.query, args.max, output)

    print(f"\n✓ Scrape complete — {total} new document(s) in {output}")
    if total:
        print("Rebuild the graph so new knowledge is queryable:")
        print("  python .github/skills/klipper-knowledge-graph/scripts/graphify_kb.py --build")


if __name__ == "__main__":
    main()
