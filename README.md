# aegis-stack-crawl4ai

Web crawling and scraping for [Aegis Stack](https://github.com/lbedner/aegis-stack) projects.
Wraps [crawl4ai](https://github.com/unclecode/crawl4ai) (Apache 2.0) and persists results
into a generic, query-friendly `crawled_page` table.

This is the reference third-party plugin: it exercises the plugin system end to end and
rides on per-plugin schema isolation. On Postgres the plugin's tables live in their own
`crawler` schema, apart from the rest of the stack; SQLite has no schemas, so there the
table lands unqualified in the single database file.

## Install

Inside an Aegis Stack project:

```bash
pip install aegis-stack-crawl4ai
aegis add crawl4ai
```

That will:

- Add `crawl4ai>=0.8.6` and `alembic>=1.13` to your project's `pyproject.toml`
- Render the service (`app/services/crawler/`), its router
  (`app/components/backend/api/crawler/`), the dashboard card and modal, the
  htmx Overseer's Crawler page (on stacks with `htmx`), and a `crawl` CLI
- Generate an Alembic migration creating `crawler.crawled_page`
- Mount the routes below under `/api/v1/crawler`
- Add a `Crawler` row to the dashboard health table, with its own card and modal

The install is HTTP-only: pages are fetched as the server sends them, with no browser.
Client-rendered content is out of scope.

## Why `>=0.8.6`?

Crawl4AI 0.8.5 and earlier pull in a transitive `litellm` dependency that was
[compromised in a PyPI supply-chain attack](https://github.com/unclecode/crawl4ai/releases).
0.8.6 is the hotfix release that swaps in a clean fork. Always pin `>=0.8.6`.

## What you get

**Dashboard and Overseer.** The same things on both frontends: a Crawler card and modal
on the Flet dashboard, and a Crawler page on the htmx Overseer (Overview, Sites, Pages,
Crawl), at the rail entry the generic status page would otherwise take.

- *Overview* is the counts.
- *Sites* are the sites you have crawled. A site narrows its pages to the failed, packs
  its export into the object store, and fetches the assets its pages name; both are jobs
  the Crawl section follows.
- *Pages* open on their markdown, their raw HTML and their assets.
- *Crawl* starts a crawl of live sites (seeds, depth, max pages, a CSS selector) or of
  one site from the Wayback Machine (domain, from/to, include/exclude globs), either with
  assets, and follows the job while it runs.

**API.** Six routes under `/api/v1/crawler`:

| route | does |
|---|---|
| `POST /crawl` | fetch one URL, store it, return the row |
| `POST /crawl-batch` | start a background crawl, return `202` + a `job_id` |
| `POST /wayback` | fetch every archived page of a site, same `202` + `job_id` |
| `GET /sites` | crawled sites, with page and failure counts |
| `POST /sites/{site}/assets` | fetch the site's missing assets, same `202` + `job_id` |
| `GET /sites/{site}/export` | the site as a zip: pages, assets, `manifest.json` (built in the request; small sites) |
| `POST /sites/{site}/export` | pages and `manifest.json` kept in the object store, same `202` + `job_id`; the job's result is the `StoredExport` |
| `GET /pages` | recent pages, newest first; `?site=` narrows, `?failed_only=` filters |
| `GET /pages/{id}` | one stored page, markdown and the HTML it came from |
| `GET /pages/{id}/assets` | the files that page references, and where their bytes are |
| `GET /stats` | counts, distinct URLs, content-type split, last fetch |

**CLI.** `<project> crawl stats | fetch | site | wayback | assets | export | list | show | retry-failed`.

**Progress.** A crawl runs as a framework job, so progress streams over
`/api/v1/jobs/{job_id}/events` and the dashboard follows it without knowing anything about
the crawler. With the `worker` component the crawl runs there, on the plugin's own `crawler`
queue (arq, TaskIQ or Dramatiq, whichever the stack uses), so a webserver restart leaves it
running; without one it is a background task in the webserver. Either way pages stream
through one at a time: each is stored and counted as it lands, and the job never holds the
site in memory.

## Archive snapshots

A `web.archive.org/web/<timestamp>/<url>` URL is fetched in its raw `id_` form (the
original bytes, no toolbar, no rewritten links) and stored under the original URL, with
`snapshot_ts` and `archive_url` in `doc_metadata` and `source_kind = "wayback"`. The
archived site shows up as itself in the sites view. Requests to archive.org go one at a
time, `CRAWLER_ARCHIVE_DELAY_S` apart (default 4s), and a 429 or 503 is waited out and
retried up to `CRAWLER_RETRY_LIMIT` times rather than stored as a failed page.

A whole archived site is listed from the CDX index rather than crawled link by link,
which would wander into the archive's own chrome:

```bash
<project> crawl wayback example.com --to 20191102 --exclude "*backup.php*"
```

One request lists every successful HTML capture (subdomains included); the latest
capture of each page inside the `--from`/`--to` window is fetched, and pages the store
already holds are skipped unless `--fresh`.

## Assets

With `--assets` (or `options.assets`), each stored page's same-site images, stylesheets,
scripts and downloads are fetched too, once per site however many pages reference them,
and kept in the project's object store (`app.core.storage`) under their content key, so
one GIF on three hundred pages is one object. An archived page's assets come through the
archive. A `crawled_asset` row records each one, including failures, which `show` lists.
A definite miss (a 404) is not asked for again; a throttle or an outage is.

`<project> crawl assets example.com` fetches whatever the site's stored pages name and
do not have yet: pages crawled before `--assets`, pages an archive pull skipped as already
stored, assets whose fetch was throttled.

## Export

```bash
<project> crawl export example.com ./example.com
```

The site as a folder: each page's HTML and markdown at its URL path (`journal/may_2005.htm`
and `journal/may_2005.md`, `index.html` for a directory), each asset at its own path, and
a `manifest.json` naming every page and asset with its URL, snapshot timestamp, hash and
content type, plus a `missing` list for any object the store no longer holds and a
`superseded` list for pages the live site and the archive both gave (the live copy is the
one exported). The latest successful fetch of each page is the one exported. Re-running
overwrites, so the folder is the archive and the stack is disposable.

Without a directory, `crawl export example.com` packs the pages and the manifest into the
object store as a job on the crawler queue (the assets are already there, under the keys
the manifest names) and prints the key. The Overseer's Export button is the same job.

## Crawl options

Defaults reproduce a single-page fetch. `crawl4ai`'s `CrawlerRunConfig` takes about a
hundred parameters; these are the handful that change what you actually get back, and the
API, the CLI and the dashboard share them.

| option | default | does |
|---|---|---|
| `depth` | `0` | how many links deep to follow (hard ceiling of 3) |
| `max_pages` | `25` | ceiling on pages per seed URL when `depth > 0` |
| `stay_on_domain` | `true` | follow links only within the seed's site |
| `selector` | none | CSS selector: keep only this part of each page |
| `min_words` | `0` | drop blocks shorter than this many words (nav, chrome) |
| `fresh` | `false` | bypass the network cache and row-level dedup |
| `assets` | `false` | also fetch each page's images, stylesheets, scripts and downloads |
| `include` | none | globs; keep only matching pages (the seed always lands) |
| `exclude` | none | globs; drop matching pages |

```bash
<project> crawl site example.com --depth 1 --max-pages 50 --selector "main article"
```

## Settings

Composed into your project's `Settings`, so they are ordinary env vars:

| setting | default | does |
|---|---|---|
| `CRAWLER_DEFAULT_TIMEOUT_S` | `30` | per-URL fetch timeout |
| `CRAWLER_MAX_CONCURRENCY` | `5` | in-flight requests during a batch |
| `CRAWLER_USER_AGENT` | `aegis-stack-crawl4ai/0.1` | `User-Agent` sent on every request |

## The `crawled_page` table

Generic by design: URL, content, content hash, JSONB metadata, status code, source kind.
Future ingestion plugins (RSS, PDF, sitemap) can share the schema or follow the same shape.

| column | type | notes |
|----------------|-----------------|-------------------------------------------------------------|
| `id` | int PK | autoincrement |
| `source_url` | text | indexed |
| `site` | varchar(255) | registrable host, `www.` stripped; indexed, and what the sites view groups by |
| `content` | text | nullable (failures still produce a row) |
| `content_hash` | varchar(64) | sha256, indexed (use for dedup queries) |
| `content_type` | varchar(32) | `markdown` / `html` / `json` / `binary` |
| `doc_metadata` | jsonb | caller-supplied tags, e.g. `{"ign_id": 5208, "cluster": 9}` |
| `status_code` | int | HTTP status; `>= 400` is your retry queue |
| `source_kind` | varchar(32) | producer label (`crawl4ai`, `rss`, `pdf_ingest`, ...) |
| `fetched_at` | timestamptz | indexed |

Re-fetching a URL writes a new row; dedup-by-hash is a query you run when you care, not a
write-path branch.

## Use from Python

```python
from app.core.db import AsyncSessionLocal
from app.services.crawler.deps import get_crawler
from app.services.crawler.schemas import CrawlOptions

crawler = get_crawler()  # process-wide instance; the API and health check share it

async with AsyncSessionLocal() as session:
    doc = await crawler.fetch(
        session,
        url="https://example.com",
        doc_metadata={"campaign": "march"},
    )
    print(doc.id, doc.status_code, len(doc.content or ""))

    # Follow links, one level, staying on the site.
    pages = await crawler.crawl(
        session,
        url="https://example.com",
        options=CrawlOptions(depth=1, max_pages=50),
    )
```

A short-lived script that owns its crawler should build its own and close it:

```python
from app.services.crawler.service import CrawlerService

crawler = CrawlerService()
try:
    ...
finally:
    await crawler.aclose()
```

## Use from the API

```bash
curl -X POST http://localhost:8000/api/v1/crawler/crawl \
  -H 'Content-Type: application/json' \
  -d '{"url": "example.com", "doc_metadata": {"campaign": "march"}}'

curl -X POST http://localhost:8000/api/v1/crawler/crawl-batch \
  -H 'Content-Type: application/json' \
  -d '{"urls": ["example.com"], "options": {"depth": 1, "max_pages": 50}}'

curl http://localhost:8000/api/v1/crawler/sites
curl "http://localhost:8000/api/v1/crawler/pages?site=example.com&limit=10"
```

A bare domain is fine anywhere a URL is taken: `example.com` becomes `https://example.com`
on the way into the request model.

## Bulk fetch example: NWVault recovery

The motivating use case for the plugin: walk a local mirror of a deceased site, extract the
identifiers each page references, fetch the corresponding archived snapshot from
web.archive.org, and store both the body and the local-file pointer for later reconciliation.

```python
import asyncio
from pathlib import Path
from app.core.db import AsyncSessionLocal
from app.services.crawler.service import CrawlerService

NWVAULT_LOCAL = Path("/path/to/nwvault-legacy")


def parse_ign_link(html_path: Path) -> tuple[int, int] | None:
    """Pull the IGN cluster + id out of a local html page. Returns None if the
    page doesn't reference an archived ratings link."""
    # ... your parser ...
    return None


async def main() -> None:
    crawler = CrawlerService()
    try:
        urls: list[str] = []
        meta: dict[str, dict] = {}
        for html in NWVAULT_LOCAL.rglob("*.html"):
            parsed = parse_ign_link(html)
            if not parsed:
                continue
            cluster, ign_id = parsed
            url = (
                "https://web.archive.org/web/2006/"
                f"http://nwvault.ign.com/View.php?view=Ratings.Viewer"
                f"&cluster={cluster}&id={ign_id}"
            )
            urls.append(url)
            meta[url] = {
                "local_file": str(html.relative_to(NWVAULT_LOCAL)),
                "ign_id": ign_id,
                "cluster": cluster,
                "source": "ign_archive",
            }

        await crawler.batch_fetch(
            AsyncSessionLocal,
            urls=urls,
            doc_metadata_for=meta,
        )
    finally:
        await crawler.aclose()


asyncio.run(main())
```

Then query by your domain identifiers:

```sql
SELECT content
FROM crawler.crawled_page
WHERE doc_metadata->>'ign_id' = '5208'
ORDER BY fetched_at DESC
LIMIT 1;
```

Failed fetches don't tank the batch; the retry queue is just:

```sql
SELECT source_url
FROM crawler.crawled_page
WHERE status_code IS NULL OR status_code >= 400;
```

or `<project> crawl retry-failed`.

## Layout

The plugin follows the host project's own conventions rather than inventing its
own: business logic under `app/services/`, reads in a `queries` module, the HTTP
layer with the other routers, display code with the other dashboard code.

```
aegis-stack-crawl4ai/
├── pyproject.toml                        # entry point: aegis.plugins:crawl4ai
├── src/aegis_stack_crawl4ai/
│   ├── plugin.py                         # get_spec() returns the PluginSpec
│   └── templates/{{ project_slug }}/
│       ├── app/services/crawler/
│       │   ├── service.py                # AsyncWebCrawler wrapper
│       │   ├── queries.py                # every read, so an N+1 audit is one file
│       │   ├── models.py                 # CrawledPage, CrawledAsset SQLModels
│       │   ├── schemas.py                # CrawlOptions, request / response models
│       │   ├── utils.py                  # URL helpers: fetchable, canonical, site
│       │   ├── jobs.py                   # what a crawl job does, and where it runs
│       │   ├── deps.py                   # FastAPI DI, one crawler per process
│       │   ├── settings.py               # settings mixin (leaf module)
│       │   ├── health.py                 # dashboard health check
│       │   └── domains/                  # the subsystems
│       │       ├── archive.py            # Wayback snapshots, paced and retried
│       │       ├── wayback.py            # a site listed from the CDX index
│       │       ├── assets.py             # a page's images, scripts, downloads
│       │       └── export.py             # a site as a folder of plain files
│       ├── app/components/backend/api/crawler/
│       │   └── router.py                 # FastAPI router
│       ├── app/components/frontend/dashboard/
│       │   ├── crawler_ui.py             # names, routes and cells the surfaces share
│       │   ├── cards/crawler_card.py
│       │   └── modals/crawler_*.py       # modal, pages tab, crawl tab
│       ├── app/components/web_frontend/  # htmx stacks only
│       │   ├── overseer_crawler.py       # the Overseer page's sections
│       │   ├── routes/partials/overseer_crawler.py  # its drawers and actions
│       │   └── templates/pages/overseer/crawler/
│       ├── app/cli/crawl.py              # crawl commands
│       └── tests/                        # shipped into the project and run there
└── tests/
    └── test_plugin.py                    # spec contract tests
```

## Develop

```bash
make install     # uv sync
make test        # pytest
make check       # lint + test
make fix         # ruff format + autofix
```

`tests/test_plugin.py` checks the spec contract here. The tests under
`templates/{{ project_slug }}/tests/` ship into the generated project and run
against the real service there, including a layout test that holds the plugin to
the host project's structure.

## License

Apache 2.0, same as upstream crawl4ai.
