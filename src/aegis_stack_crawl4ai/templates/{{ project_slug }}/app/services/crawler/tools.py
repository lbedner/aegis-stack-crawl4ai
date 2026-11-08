"""The crawler's tools, for an agent (``app.core.tools``): what the store
holds, and a page's markdown. Reads, for anyone the registry lets in."""

from app.core.db import get_async_session
from app.core.tools import register_tool
from app.services.crawler.schemas import (
    CrawledPageListing,
    CrawledPageSummary,
    CrawlerSite,
)
from app.services.crawler.service import CrawlerService, page


async def crawler_sites() -> list[CrawlerSite]:
    """The sites in the store, with their page and failure counts and
    when each was last fetched."""
    async with get_async_session() as session:
        return await CrawlerService().sites(session)


async def crawler_pages(
    site: str | None = None, failed_only: bool = False, limit: int = 50
) -> list[CrawledPageListing]:
    """Stored pages, newest first: URL, status, type, size, when fetched.
    ``site`` narrows to one site, ``failed_only`` to the fetches that
    failed. Read a page's text with ``crawler_page``."""
    async with get_async_session() as session:
        pages = await CrawlerService().list_pages(
            session, limit=min(max(limit, 1), 500), failed_only=failed_only, site=site
        )
        return [CrawledPageListing.model_validate(p) for p in pages]


async def crawler_page(page_id: int) -> CrawledPageSummary | None:
    """One stored page: its markdown and what is known about it; None
    for no such page."""
    async with get_async_session() as session:
        found = await page(session, page_id)
        return None if found is None else CrawledPageSummary.model_validate(found)


register_tool("crawler_sites", crawler_sites, effect="read")
register_tool("crawler_pages", crawler_pages, effect="read")
register_tool("crawler_page", crawler_page, effect="read")
