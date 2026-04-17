# CTL RAG Data

Structured knowledge base scraped from Cornell University's teaching and learning technology portals, ready for use in Retrieval-Augmented Generation (RAG) pipelines.

---

## Sources

| Site | Domain | Description |
|------|--------|-------------|
| [Center for Teaching Innovation](https://teaching.cornell.edu) | `teaching.cornell.edu` | Teaching resources, programs, grants, events, and pedagogy guidance for Cornell faculty and instructors |
| [Learning Technologies Resource Library](https://learn.canvas.cornell.edu) | `learn.canvas.cornell.edu` | Canvas LMS guides, video tools (Kaltura, Panopto, Zoom), collaboration and assessment tools |

---

## File Structure

```
CTL-RAG-Data/
├── data/
│   ├── teaching_cornell_edu.jsonl        # 382 pages from teaching.cornell.edu (3.4 MB)
│   ├── learn_canvas_cornell_edu.jsonl    # 216 pages from learn.canvas.cornell.edu (1.2 MB)
│   └── manifest.json                     # Source metadata and schema reference
├── scripts/
│   └── scraper.py                        # BFS web crawler / scraper
└── README.md
```

---

## Data Format

Each `.jsonl` file contains one JSON object per line. Every record represents a single scraped web page.

### Schema

```json
{
  "url": "https://teaching.cornell.edu/teaching-resources/active-collaborative-learning",
  "title": "Active & Collaborative Learning | Center for Teaching Innovation",
  "meta_description": "Strategies and resources for active and collaborative learning at Cornell.",
  "headings": [
    { "level": "h1", "text": "Active & Collaborative Learning" },
    { "level": "h2", "text": "Why Active Learning?" },
    { "level": "h3", "text": "Think-Pair-Share" }
  ],
  "full_text": "Full cleaned page text with all boilerplate removed ...",
  "chunks": [
    "First ~800-character overlapping chunk of text ...",
    "Second chunk with 100-char overlap from previous ..."
  ]
}
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `url` | `string` | Canonical URL of the scraped page |
| `title` | `string` | Page `<title>` tag content |
| `meta_description` | `string` | `<meta name="description">` content (may be empty) |
| `headings` | `array` | Ordered list of h1–h4 headings — useful for section-level metadata |
| `full_text` | `string` | Full cleaned body text with nav/footer/sidebar noise removed |
| `chunks` | `array` | ~800-char overlapping text chunks (100-char overlap) — ready to embed directly |

---

## Quickstart: Loading Data for RAG

### Python — load and iterate records

```python
import json

with open("data/teaching_cornell_edu.jsonl", "r") as f:
    records = [json.loads(line) for line in f]

# Access chunks for embedding
for record in records:
    for chunk in record["chunks"]:
        # embed chunk, store with metadata: record["url"], record["title"]
        pass
```

### With LangChain

```python
from langchain_community.document_loaders import JSONLoader

loader = JSONLoader(
    file_path="data/teaching_cornell_edu.jsonl",
    jq_schema=".chunks[]",
    content_key=None,
    json_lines=True,
    metadata_func=lambda rec, _: {
        "url": rec.get("url"),
        "title": rec.get("title"),
    }
)
docs = loader.load()
```

### With LlamaIndex

```python
import json
from llama_index.core import Document

def load_jsonl_as_documents(path):
    docs = []
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            for chunk in rec["chunks"]:
                docs.append(Document(
                    text=chunk,
                    metadata={"url": rec["url"], "title": rec["title"]}
                ))
    return docs

docs = load_jsonl_as_documents("data/teaching_cornell_edu.jsonl")
```

---

## Re-running the Scraper

### 1. Install dependencies

```bash
pip install requests beautifulsoup4 lxml
```

### 2. Run

```bash
python3 scripts/scraper.py
```

This will:
1. BFS-crawl both sites, staying within each domain
2. Overwrite the existing `.jsonl` files in `data/`
3. Rewrite `data/manifest.json`

Expected run time: **~15–25 minutes** (polite 300 ms delay per request).

### 3. Add a new site (optional)

Edit the `SITES` list at the top of `scripts/scraper.py`:

```python
SITES = [
    {
        "start_url": "https://your-new-site.cornell.edu",
        "allowed_domain": "your-new-site.cornell.edu",
        "output_file": "data/your_new_site.jsonl",
    },
    ...
]
```

---

## Scraper Documentation (`scripts/scraper.py`)

### Overview

A synchronous BFS (breadth-first search) web crawler built with `requests` and `BeautifulSoup`. It stays strictly within each target domain, respects content types, and skips binary/auth/feed URLs.

### Configuration

| Constant | Default | Description |
|----------|---------|-------------|
| `HEADERS["User-Agent"]` | Chrome 120 UA | Browser user-agent sent with every request |
| `max_chars` in `chunk_text()` | `800` | Max characters per RAG chunk |
| `overlap` in `chunk_text()` | `100` | Overlap between consecutive chunks |
| `time.sleep(0.3)` | 300 ms | Polite crawl delay between requests |
| `timeout` in `requests.get()` | 15 s | Per-request timeout |

### Functions

#### `crawl_site(start_url, allowed_domain, output_file)`
Main crawl loop. Maintains a `visited` set and a `deque` queue. For each URL:
- GETs the page (follows redirects, validates the final URL stays in domain)
- Parses with BeautifulSoup
- Calls `extract_page()` and writes the record to JSONL if content length > 100 chars
- Enqueues all new in-domain links found via `get_links()`

#### `extract_page(url, soup) → dict`
Extracts structured data from a parsed HTML page:
- **Title** — from `<title>`
- **Meta description** — from `<meta name="description">`
- **Headings** — all h1–h4 tags in document order
- **Content text** — tries a priority list of content selectors (`main`, `article`, `[role="main"]`, `.entry-content`, `#content`, etc.) before falling back to `<body>` minus nav/footer/aside

#### `chunk_text(text, max_chars=800, overlap=100) → list[str]`
Splits full page text into overlapping chunks:
1. Splits on sentence boundaries (`[.!?]` followed by whitespace)
2. Greedily accumulates sentences up to `max_chars`
3. Starts each new chunk with the last `overlap` characters of the previous chunk

#### `get_links(base_url, soup, allowed_domain) → list[str]`
Extracts all `<a href>` links from a page, filters to:
- Same domain as `allowed_domain`
- `http`/`https` schemes only
- Not matching `SKIP_PATTERNS` (PDFs, images, wp-admin, feeds, etc.)
- Fragments stripped

#### `clean_text(text) → str`
Collapses all whitespace sequences to a single space and strips.

### URL Skip Patterns

The following are automatically excluded from crawling:

```
.pdf .doc .docx .xls .xlsx .ppt .pptx .zip
.png .jpg .jpeg .gif .svg .ico .mp4 .mp3 .webm .css .js
/wp-json/  /feed/  /xmlrpc.php  /wp-admin/
mailto:    javascript:
```

---

## Notes

- The scraper is **read-only** and makes no modifications to the target sites.
- Crawl depth is unlimited — all reachable in-domain pages are visited.
- Pages with fewer than 100 characters of content are silently skipped.
- The `manifest.json` is regenerated on every run with the total page count and schema.
