# Reference

[README](../README.md) · [Using it](usage.md) · [Crawling](crawling.md) · [Reference](reference.md)

## Settings

Composed into your project's `Settings`, so they are ordinary env vars:

| setting | default | does |
|---|---|---|
| `CRAWLER_DEFAULT_TIMEOUT_S` | `30` | per-URL fetch timeout |
| `CRAWLER_MAX_CONCURRENCY` | `5` | in-flight requests during a batch |
| `CRAWLER_USER_AGENT` | `aegis-stack-crawl4ai/0.1` | `User-Agent` sent on every request |
| `CRAWLER_ARCHIVE_DELAY_S` | `4.0` | seconds between requests to web.archive.org |
| `CRAWLER_RETRY_LIMIT` | `3` | retries for a 429 or 503 before a page is stored as failed |

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
| `fetched_at` | timestamp (UTC) | indexed |

Re-fetching a URL writes a new row; dedup-by-hash is a query you run when you care, not a
write-path branch.

## Why `>=0.8.6`?

Crawl4AI 0.8.5 and earlier pull in a transitive `litellm` dependency that was
[compromised in a PyPI supply-chain attack](https://github.com/unclecode/crawl4ai/releases).
0.8.6 is the hotfix release that swaps in a clean fork. Always pin `>=0.8.6`.

## Layout

The plugin follows the host project's own conventions rather than inventing its
own: business logic under `app/services/`, reads in a `queries` module, the HTTP
layer with the other routers, display code with the other dashboard code. Its ways in (the
router, jobs, tools, CLI and Overseer page) and other services reach it through `service.py`,
never its queries, models or domains.

```
aegis-stack-crawl4ai/
├── pyproject.toml                        # entry point: aegis.plugins:crawl4ai
├── src/aegis_stack_crawl4ai/
│   ├── plugin.py                         # get_spec() returns the PluginSpec
│   └── templates/{{ project_slug }}/
│       ├── app/services/crawler/
│       │   ├── service.py                # AsyncWebCrawler wrapper; the facade (__all__)
│       │   ├── queries.py                # every read, so an N+1 audit is one file
│       │   ├── models.py                 # CrawledPage, CrawledAsset SQLModels
│       │   ├── schemas.py                # CrawlOptions, request / response models
│       │   ├── utils.py                  # URL helpers: fetchable, canonical, site
│       │   ├── jobs.py                   # what a crawl job does, and where it runs
│       │   ├── deps.py                   # FastAPI DI, one crawler per process
│       │   ├── settings.py               # settings mixin (leaf module)
│       │   ├── health.py                 # dashboard health check
│       │   ├── tools.py                  # the store, for an agent
│       │   └── domains/                  # the subsystems
│       │       ├── archive.py            # Wayback snapshots, paced and retried
│       │       ├── wayback.py            # a site listed from the CDX index
│       │       ├── assets.py             # a page's images, scripts, downloads
│       │       ├── results.py            # what a crawl4ai result says: status, metadata, hash
│       │       └── export.py             # a site as a folder of plain files
│       ├── app/components/backend/api/crawler/
│       │   └── router.py                 # FastAPI router
│       ├── app/components/worker/queues/
│       │   └── crawler.py                # the plugin's own queue (worker stacks)
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
