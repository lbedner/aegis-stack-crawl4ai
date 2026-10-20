"""Actions for the Overseer Crawler page: a site's drawer and its asset
fetch, a page's drawer, a crawl of live sites or of the Wayback Machine,
and the job each starts, streamed.

Mounted by the plugin's ``RouterWiring`` rather than ``routes/pages.py``,
so the router carries the Overseer gate itself; every job starts through
``dispatch``, as the API's do.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_crawler
from app.components.web_frontend.overseer_access import overseer_gate
from app.components.web_frontend.overseer_live import event_stream
from app.components.web_frontend.rendering import dialog, go_to, toast_response
from app.core.db import get_async_db
from app.services.crawler.jobs import start_assets, start_crawl, start_wayback
from app.services.crawler.schemas import (
    BatchCrawlRequest,
    CrawlOptions,
    WaybackRequest,
)

router = APIRouter(
    prefix=overseer_crawler.PARTIALS,
    dependencies=[Depends(overseer_gate)],
    include_in_schema=False,
)

Text = Annotated[str, Form()]


def _lines(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _problem(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}"


@router.get("/sites/drawer", response_class=HTMLResponse)
async def site_drawer(
    request: Request, site: str, db: AsyncSession = Depends(get_async_db)
) -> Response:
    """One site in the drawer: its counts, export and asset fetch."""
    context = await overseer_crawler.site_context(db, site)
    if context is None:
        raise HTTPException(status_code=404, detail="Nothing stored for that site.")
    return dialog(request, "pages/overseer/crawler/_site_drawer.html", **context)


@router.post("/sites/assets")
async def site_assets(site: Text) -> Response:
    """Fetch every asset the site's pages name and the store lacks."""
    job_id = await start_assets(site)
    return go_to(
        overseer_crawler.job_url(job_id),
        f"Fetching {site}'s assets",
        target="#overseer-main",
    )


@router.get("/pages/{page_id}/drawer", response_class=HTMLResponse)
async def page_drawer(
    request: Request, page_id: int, db: AsyncSession = Depends(get_async_db)
) -> Response:
    """One stored page in the drawer: its markdown, HTML and assets."""
    context = await overseer_crawler.page_context(db, page_id)
    if context is None:
        raise HTTPException(status_code=404, detail="That page is gone.")
    return dialog(request, "pages/overseer/crawler/_page_drawer.html", **context)


@router.post("/crawl")
async def crawl(
    mode: Text = "site",
    seeds: Text = "",
    domain: Text = "",
    from_ts: Text = "",
    to_ts: Text = "",
    include: Text = "",
    exclude: Text = "",
    depth: Text = "0",
    max_pages: Text = "25",
    selector: Text = "",
    stay_on_domain: Text = "",
    assets: Text = "",
) -> Response:
    """Start a crawl of live sites (``site``) or of the archive
    (``wayback``), then follow its job in the Crawl section."""
    try:
        if mode == "wayback":
            job_id = await start_wayback(
                WaybackRequest(
                    domain=domain.strip(),
                    from_ts=from_ts.strip() or None,
                    to_ts=to_ts.strip() or None,
                    options=CrawlOptions(
                        include=_lines(include),
                        exclude=_lines(exclude),
                        assets=bool(assets),
                    ),
                )
            )
        else:
            request = BatchCrawlRequest.model_validate(
                {
                    "urls": _lines(seeds),
                    "options": {
                        "depth": depth or 0,
                        "max_pages": max_pages or 25,
                        "stay_on_domain": bool(stay_on_domain),
                        "selector": selector.strip() or None,
                        "assets": bool(assets),
                    },
                }
            )
            job_id = await start_crawl(
                [str(url) for url in request.urls], options=request.options
            )
    except ValidationError as exc:
        return toast_response(_problem(exc), "error")
    return go_to(
        overseer_crawler.job_url(job_id), "Crawl started", target="#overseer-main"
    )


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> Response:
    """The job, re-sent whenever it changes."""
    return event_stream(overseer_crawler.job_events(job_id))
