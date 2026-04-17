#!/usr/bin/env python3
"""
Cornell Teaching & Canvas scraper for RAG knowledge base.
Crawls teaching.cornell.edu and learn.canvas.cornell.edu,
saves structured JSONL files per domain.
"""

import json
import re
import time
from collections import deque
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

SITES = [
    {
        "start_url": "https://teaching.cornell.edu",
        "allowed_domain": "teaching.cornell.edu",
        "output_file": "data/teaching_cornell_edu.jsonl",
    },
    {
        "start_url": "https://learn.canvas.cornell.edu",
        "allowed_domain": "learn.canvas.cornell.edu",
        "output_file": "data/learn_canvas_cornell_edu.jsonl",
    },
]

# Patterns to skip (binary, auth, feed, etc.)
SKIP_PATTERNS = re.compile(
    r"\.(pdf|docx?|xlsx?|pptx?|zip|png|jpe?g|gif|svg|ico|mp4|mp3|webm|css|js|xml|json)$"
    r"|/wp-json/"
    r"|/feed/"
    r"|/xmlrpc\.php"
    r"|/wp-admin/"
    r"|mailto:"
    r"|javascript:",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    """Collapse whitespace and strip."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_page(url: str, soup: BeautifulSoup) -> dict:
    """Extract structured data from a BeautifulSoup page."""
    # Title
    title_tag = soup.find("title")
    title = clean_text(title_tag.get_text()) if title_tag else ""

    # Meta description
    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        meta_desc = clean_text(meta["content"])

    # Headings hierarchy
    headings = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = clean_text(tag.get_text())
        if text:
            headings.append({"level": tag.name, "text": text})

    # Main content — try common content containers
    content_text = ""
    for selector in [
        "main",
        "article",
        '[role="main"]',
        ".main-content",
        ".field--type-text-with-summary",
        ".entry-content",
        "#content",
        ".content",
        ".post-content",
        ".site-content",
    ]:
        node = soup.select_one(selector)
        if node:
            # Remove nav, footer, sidebar noise within content
            for noise in node.find_all(
                ["nav", "footer", "aside", "script", "style", "noscript"]
            ):
                noise.decompose()
            content_text = clean_text(node.get_text(separator=" "))
            break

    # Fallback: body minus boilerplate
    if not content_text:
        body = soup.find("body")
        if body:
            for noise in body.find_all(
                ["nav", "footer", "aside", "script", "style", "noscript", "header"]
            ):
                noise.decompose()
            content_text = clean_text(body.get_text(separator=" "))

    # Chunk into paragraphs for RAG (split on sentence boundaries ~500 chars)
    chunks = chunk_text(content_text)

    return {
        "url": url,
        "title": title,
        "meta_description": meta_desc,
        "headings": headings,
        "full_text": content_text,
        "chunks": chunks,
    }


def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks suitable for embedding."""
    if not text:
        return []
    # Split on paragraph/sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= max_chars:
            current = (current + " " + sent).strip()
        else:
            if current:
                chunks.append(current)
            # Start next chunk with overlap
            overlap_text = current[-overlap:] if len(current) > overlap else current
            current = (overlap_text + " " + sent).strip()
    if current:
        chunks.append(current)
    return chunks


def get_links(base_url: str, soup: BeautifulSoup, allowed_domain: str) -> list[str]:
    """Extract in-domain links from a page."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if SKIP_PATTERNS.search(href):
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc != allowed_domain:
            continue
        # Drop fragments
        clean = parsed._replace(fragment="").geturl()
        links.append(clean)
    return links


def crawl_site(start_url: str, allowed_domain: str, output_file: str):
    """BFS crawl of a site, writing each page as a JSONL record."""
    import os

    os.makedirs("data", exist_ok=True)

    visited = set()
    queue = deque([start_url])
    visited.add(start_url)
    count = 0
    errors = 0

    print(f"\n{'='*60}")
    print(f"Crawling: {start_url}")
    print(f"Output:   {output_file}")
    print(f"{'='*60}")

    with open(output_file, "w", encoding="utf-8") as out:
        while queue:
            url = queue.popleft()
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
                # Follow redirects but stay in domain
                final_url = resp.url
                if urlparse(final_url).netloc != allowed_domain:
                    continue
                if resp.status_code != 200:
                    print(f"  [SKIP {resp.status_code}] {url}")
                    continue
                if "text/html" not in resp.headers.get("Content-Type", ""):
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                record = extract_page(final_url, soup)

                # Only save pages with meaningful content
                if len(record["full_text"]) > 100:
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1
                    print(f"  [{count:4d}] {final_url[:90]}")

                # Enqueue new links
                for link in get_links(final_url, soup, allowed_domain):
                    if link not in visited:
                        visited.add(link)
                        queue.append(link)

                time.sleep(0.3)  # polite crawl delay

            except Exception as e:
                errors += 1
                print(f"  [ERROR] {url} — {e}")
                continue

    print(f"\nDone: {count} pages saved, {errors} errors → {output_file}")
    return count


def main():
    total = 0
    for site in SITES:
        n = crawl_site(
            start_url=site["start_url"],
            allowed_domain=site["allowed_domain"],
            output_file=site["output_file"],
        )
        total += n

    # Write a combined manifest
    manifest = {
        "sources": [
            {
                "domain": site["allowed_domain"],
                "start_url": site["start_url"],
                "output_file": site["output_file"],
            }
            for site in SITES
        ],
        "total_pages": total,
        "format": "jsonl",
        "schema": {
            "url": "Source URL",
            "title": "Page title",
            "meta_description": "Meta description",
            "headings": "List of {level, text} heading objects",
            "full_text": "Full cleaned page text",
            "chunks": "List of ~800-char overlapping text chunks for embedding",
        },
    }
    with open("data/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest written to data/manifest.json")
    print(f"Total pages scraped: {total}")


if __name__ == "__main__":
    main()
