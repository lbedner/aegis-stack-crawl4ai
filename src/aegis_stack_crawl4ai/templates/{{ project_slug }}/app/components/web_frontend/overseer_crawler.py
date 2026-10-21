"""Context for the Overseer Crawler page's sections.

The crawler on the htmx Overseer: the sites in the store, one opening in
the drawer with its export and its asset fetch; a crawl of live sites or
of the Wayback Machine, followed while it runs; and every stored page,
one opening in the drawer with its markdown, HTML and assets. Reads go
through ``CrawlerService`` on the request's session, writes start the
same jobs the API does (``dispatch``). Registered by the plugin's
``overseer_pages`` wiring, only on stacks with the htmx frontend.
"""

from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from app.core.formatting import format_bytes, format_relative_time
from app.services.crawler import SERVICE_NAME, queries
from app.services.crawler.deps import get_crawler
from app.services.crawler.models import CrawledPage
from app.services.crawler.schemas import MAX_DEPTH, CrawlSummary, StoredExport
from app.services.system.jobs import get_job_runner
from app.services.system.models import ComponentStatus

from .overseer_live import fragment_events
from .overseer_nav import SectionRequest, page_url
from .rendering import drawer_state, fragment, ranked, status_cell, with_query

SECTIONS = (
    (None, {"overview": "Overview"}),
    ("Store", {"sites": "Sites", "pages": "Pages"}),
    ("Fetch", {"crawl": "Crawl"}),
)

PAGE = page_url("services", SERVICE_NAME)
PARTIALS = "/partials/overseer/crawler"
JOB = "pages/overseer/crawler/_job.html"
EVENT = "crawler-job"
INTERVAL_SECONDS = 1.0
# ponytail: the newest pages, filtered in Python; paging when a store
# outgrows one screen of them.
LIST_SIZE = 200
SITE_PARAM, PAGE_PARAM, JOB_PARAM = "site", "page", "job"


def _when(iso: str | None) -> str | None:
    return format_relative_time(iso) if iso else None


def site_url(site: str) -> str:
    """The sites list with this site open in the drawer."""
    return with_query(f"{PAGE}/sites", **{SITE_PARAM: site})


def pages_url(site: str | None = None, failed: bool = False) -> str:
    return with_query(f"{PAGE}/pages", site=site, failed="1" if failed else None)


def job_url(job_id: str) -> str:
    """The Crawl section following this job: the address holds it, so a
    reload keeps watching."""
    return with_query(f"{PAGE}/crawl", **{JOB_PARAM: job_id})


def _page_status(page: CrawledPage) -> dict[str, str]:
    code = page.status_code
    if code is None or code >= 400:
        return status_cell(str(code or "failed"), "error")
    return status_cell(str(code), "ok")


async def _overview(req: SectionRequest) -> dict[str, Any]:
    crawler = get_crawler()
    stats = await crawler.stats(req.db)
    sites = await crawler.sites(req.db)
    return {
        "figures": [
            {"label": "Pages", "value": f"{stats.pages:,}"},
            {"label": "Failed", "value": f"{stats.failed:,}"},
            {"label": "Sites", "value": len(sites)},
            {"label": "Last fetch", "value": _when(stats.last_fetched_at) or "never"},
        ],
        "sites": ranked(
            [
                {"label": s.site, "value": f"{s.pages:,}", "n": s.pages}
                for s in sorted(sites, key=lambda s: -s.pages)[:10]
            ],
            by="n",
        ),
    }


async def _sites(req: SectionRequest) -> dict[str, Any]:
    sites = await get_crawler().sites(req.db)
    shown = req.query.get(SITE_PARAM) or ""
    known = {s.site for s in sites}
    return drawer_state(
        SITE_PARAM,
        with_query(f"{PARTIALS}/sites/drawer", site=shown) if shown in known else None,
    ) | {
        "rows": [
            {
                "site": {"label": s.site, "url": site_url(s.site)},
                "pages": s.pages,
                "failed": s.failed,
                "fetched": _when(s.last_fetched_at),
            }
            for s in sites
        ]
    }


async def site_context(db: Any, site: str) -> dict[str, Any] | None:
    """The drawer's context for one site, or None when the store has none."""
    found = next((s for s in await get_crawler().sites(db) if s.site == site), None)
    if found is None:
        return None
    assets = await queries.site_assets(db, site)
    return {
        "site": found,
        "details": [
            ("Pages", f"{found.pages:,}"),
            ("Failed", f"{found.failed:,}"),
            ("Assets", f"{len(assets):,}"),
            ("Stored", format_bytes(sum(a.size for a in assets))),
            ("Last fetch", _when(found.last_fetched_at)),
        ],
        "urls": {
            "pages": pages_url(site),
            "failed": pages_url(site, failed=True),
            "export": f"{PARTIALS}/sites/export",
            "assets": f"{PARTIALS}/sites/assets",
        },
    }


async def _pages(req: SectionRequest) -> dict[str, Any]:
    site = req.query.get("site") or None
    failed = req.query.get("failed") == "1"
    pages = await get_crawler().list_pages(
        req.db, limit=LIST_SIZE, failed_only=failed, site=site
    )
    raw = req.query.get(PAGE_PARAM) or ""
    shown = await req.db.get(CrawledPage, int(raw)) if raw.isdigit() else None
    return drawer_state(
        PAGE_PARAM, f"{PARTIALS}/pages/{shown.id}/drawer" if shown else None
    ) | {
        "rows": [
            {
                "url": {
                    "label": p.source_url,
                    "url": with_query(
                        f"{PAGE}/pages",
                        site=site,
                        failed="1" if failed else None,
                        **{PAGE_PARAM: str(p.id)},
                    ),
                },
                "status": _page_status(p),
                "type": p.content_type,
                "fetched": format_relative_time(p.fetched_at),
            }
            for p in pages
        ],
        "site": site,
        "failed": failed,
        "site_options": [
            {"id": s.site, "name": s.site} for s in await get_crawler().sites(req.db)
        ],
        "path": req.path,
    }


async def page_context(db: Any, page_id: int) -> dict[str, Any] | None:
    """The drawer's context for one stored page, or None when it is gone."""
    page = await db.get(CrawledPage, page_id)
    if page is None or page.id is None:
        return None
    return {
        "page": page,
        "status": _page_status(page),
        "details": [
            ("Site", page.site),
            ("Type", page.content_type),
            ("Size", format_bytes(len(page.content or ""))),
            ("Source", page.source_kind),
            ("Fetched", format_relative_time(page.fetched_at)),
            ("Hash", page.content_hash),
        ],
        "assets": [
            {
                "url": a.original_url,
                "type": a.content_type,
                "size": format_bytes(a.size) if a.storage_key else None,
                "status": status_cell(
                    str(a.status_code or "missing"),
                    "ok" if a.storage_key else "error",
                ),
            }
            for a in await queries.page_assets(db, page.id)
        ],
    }


async def job_context(job_id: str) -> dict[str, Any] | None:
    """A crawl job as the Crawl section shows it: running with its label,
    failed with why, or done with its ``CrawlSummary``, or with the
    ``StoredExport`` an export job left."""
    job = await get_job_runner().lookup(job_id)
    if job is None:
        return None
    result = job.result if job.status == "done" and job.result else None
    # The job's name says its kind (``start_export``), not its payload.
    packed = job.name.startswith("crawler-export:")
    kept = StoredExport.model_validate(result) if result and packed else None
    summary = CrawlSummary.model_validate(result) if result and not packed else None
    return {
        "status": job.status,
        "label": job.label,
        "error": job.error,
        "summary": summary,
        "export": [
            ("Site", kept.site),
            ("Pages", f"{kept.pages:,}"),
            ("Assets", f"{kept.assets:,}"),
            ("Size", format_bytes(kept.size)),
            ("Key", kept.key),
        ]
        if kept
        else None,
        "export_url": kept.url if kept else None,
        "rows": [
            {
                "url": p.url,
                "status": status_cell(
                    str(p.status or "failed"),
                    "error" if p.status is None or p.status >= 400 else "ok",
                ),
                "type": p.content_type,
                "size": format_bytes(p.size),
            }
            for p in (summary.pages if summary else [])
        ],
    }


async def render_job(job_id: str) -> str:
    return fragment(JOB, job=await job_context(job_id))


def job_events(job_id: str, max_frames: int | None = None) -> AsyncIterator[str]:
    """A crawl job over SSE, sent again only when it changes."""
    return fragment_events(
        EVENT, partial(render_job, job_id), INTERVAL_SECONDS, max_frames
    )


async def _crawl(req: SectionRequest) -> dict[str, Any]:
    job_id = req.query.get(JOB_PARAM) or ""
    return {
        "mode": req.query.get("mode") or "site",
        "max_depth": MAX_DEPTH,
        "job": await job_context(job_id) if job_id else None,
        "events": f"{PARTIALS}/jobs/{job_id}/events" if job_id else None,
        "event": EVENT,
    }


BUILDERS = {"overview": _overview, "sites": _sites, "pages": _pages, "crawl": _crawl}


async def section_context(
    section: str, crawler: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    return {"partials": PARTIALS} | await BUILDERS[section](req)
