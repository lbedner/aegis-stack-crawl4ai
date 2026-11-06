# Crawling

[README](../README.md) · [Using it](usage.md) · [Crawling](crawling.md) · [Reference](reference.md)

What a crawl fetches, and the three things it can do beyond fetching pages: read the Wayback Machine, keep each page's assets, and export a site as plain files.

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
