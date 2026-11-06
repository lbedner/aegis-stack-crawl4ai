# Using the crawler

[README](../README.md) · [Using it](usage.md) · [Crawling](crawling.md) · [Reference](reference.md)

The same store, four ways in: the HTTP API, the `crawl` CLI, Python inside the app, and tools an agent calls.

## API

Under `/api/v1/crawler`:

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

## CLI

`<project> crawl stats | fetch | site | wayback | assets | export | list | show | retry-failed`.

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

## Agent tools

For an agent, through the app's tool registry (MCP and chat): `crawler_sites`, `crawler_pages` and `crawler_page`, the store as an agent reads it.

## Progress and workers

A crawl runs as a framework job, so progress streams over
`/api/v1/jobs/{job_id}/events` and the dashboard follows it without knowing anything about
the crawler. With the `worker` component the crawl runs there, on the plugin's own `crawler`
queue (arq, TaskIQ or Dramatiq, whichever the stack uses), so a webserver restart leaves it
running; without one it is a background task in the webserver. Either way pages stream
through one at a time: each is stored and counted as it lands, and the job never holds the
site in memory.

## Bulk fetch example: NWVault recovery

The motivating use case for the plugin: walk a local mirror of a deceased site, extract the
identifiers each page references, fetch the corresponding archived snapshot from
web.archive.org, and store both the body and the local-file pointer for later reconciliation.
The result runs as [NWVault Revival](http://167.99.48.44/), a searchable archive of the
original Neverwinter Vault.

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
