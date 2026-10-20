"""The Overseer Crawler page: the sites in the store, one in the drawer
with its export and asset fetch; every stored page, one in the drawer
with its markdown, HTML and assets; and a crawl of a live site or of the
Wayback Machine, followed as its job runs.
"""

from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_crawler
from app.components.web_frontend.routes.partials import (
    overseer_crawler as crawler_partials,
)
from app.services.crawler import SERVICE_NAME
from app.services.crawler.models import CrawledAsset, CrawledPage
from app.services.crawler.schemas import CrawlSummary
from app.services.system.jobs import get_job_runner
from app.services.system.models import ComponentStatus
from tests.web.dom import location, one, select, text
from tests.web.overseer import sign_in, status_with

PAGE = overseer_crawler.PAGE
PARTIALS = overseer_crawler.PARTIALS
CRAWLER = ComponentStatus(name=SERVICE_NAME, message="Crawler ready")


@pytest.fixture
def crawler(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with(services=[CRAWLER]))
    yield async_client_with_db


@pytest.fixture
async def stored(async_db_session: AsyncSession) -> CrawledPage:
    """Two pages of one site, one failed, and an asset of the good one."""
    good = CrawledPage(
        source_url="https://rose.test/",
        site="rose.test",
        content="# Rose of Eternity",
        html="<h1>Rose of Eternity</h1>",
        content_type="markdown",
        status_code=200,
    )
    async_db_session.add(good)
    async_db_session.add(
        CrawledPage(
            source_url="https://rose.test/gone",
            site="rose.test",
            content_type="markdown",
            status_code=404,
        )
    )
    await async_db_session.commit()
    async_db_session.add(
        CrawledAsset(
            page_id=good.id,
            site="rose.test",
            original_url="https://rose.test/logo.png",
            content_type="image/png",
            size=2048,
            storage_key="k",
            status_code=200,
        )
    )
    await async_db_session.commit()
    return good


def _get(client: TestClient, section: str = "", query: str = "") -> str:
    url = PAGE + (f"/{section}" if section else "") + (f"?{query}" if query else "")
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.text


def test_sections(crawler: TestClient) -> None:
    assert [text(a) for a in select(_get(crawler), "#overseer-subnav nav a")] == [
        "Overview",
        "Sites",
        "Pages",
        "Crawl",
    ]


def test_overview_counts_the_store(crawler: TestClient, stored: Any) -> None:
    figures = text(one(_get(crawler), "#crawler-figures"))
    assert "Pages" in figures and "2" in figures
    assert "rose.test" in text(one(_get(crawler), "#crawler-sites"))


def test_a_site_opens_with_its_export(crawler: TestClient, stored: Any) -> None:
    rows = select(_get(crawler, "sites"), "#crawler-sites-list tbody tr")
    assert [text(select(r, "td")[0]) for r in rows] == ["rose.test"]
    drawer = crawler.get(f"{PARTIALS}/sites/drawer", params={"site": "rose.test"})
    assert drawer.status_code == 200
    export = one(drawer.text, "a[download]")
    assert export.get("href") == "/api/v1/crawler/sites/rose.test/export"
    assert "Failed" in [text(a) for a in select(drawer.text, "a")]


def test_an_unknown_site_has_no_drawer(crawler: TestClient) -> None:
    response = crawler.get(f"{PARTIALS}/sites/drawer", params={"site": "nope.test"})
    assert response.status_code == 404


def test_pages_narrow_to_the_failed(crawler: TestClient, stored: Any) -> None:
    html = _get(crawler, "pages", "site=rose.test&failed=1")
    rows = select(html, "#crawler-pages tbody tr")
    assert [text(select(r, "td")[0]) for r in rows] == ["https://rose.test/gone"]


def test_a_page_opens_with_its_markdown_and_assets(
    crawler: TestClient, stored: CrawledPage
) -> None:
    drawer = crawler.get(f"{PARTIALS}/pages/{stored.id}/drawer").text
    assert "# Rose of Eternity" in text(one(drawer, "[data-tab-panel=markdown]"))
    assert "<h1>" in text(one(drawer, "[data-tab-panel=html]"))
    assert "logo.png" in text(one(drawer, "[data-tab-panel=assets]"))


def test_each_mode_shows_its_fields(crawler: TestClient) -> None:
    """Alpine's ``x-show`` only sets ``display``: on a fieldset the server
    rendered ``hidden``, it never showed. The modes bind ``hidden``."""
    fieldsets = select(_get(crawler, "crawl"), "#crawler-crawl fieldset")
    assert [f.get(":hidden") for f in fieldsets] == [
        "mode !== 'site'",
        "mode !== 'wayback'",
    ]
    assert not any(f.get("x-show") for f in fieldsets)
    assert [f.get("hidden") is not None for f in fieldsets] == [False, True]


def test_a_crawl_starts_and_the_section_follows_it(
    crawler: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: dict[str, Any] = {}

    async def start_crawl(urls: list[str], *, options: Any) -> str:
        asked.update(
            urls=urls,
            depth=options.depth,
            assets=options.assets,
            selector=options.selector,
        )
        return "job-1"

    monkeypatch.setattr(crawler_partials, "start_crawl", start_crawl)
    response = crawler.post(
        f"{PARTIALS}/crawl",
        data={
            "mode": "site",
            "seeds": "rose.test\n",
            "depth": "2",
            "assets": "1",
            "selector": " main ",
        },
    )
    assert response.status_code == 200
    assert asked == {
        "urls": ["https://rose.test/"],
        "depth": 2,
        "assets": True,
        "selector": "main",
    }
    assert location(response) == overseer_crawler.job_url("job-1")


def test_a_wayback_pull_takes_its_window_and_globs(
    crawler: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[Any] = []

    async def start_wayback(request: Any) -> str:
        asked.append(request)
        return "job-2"

    monkeypatch.setattr(crawler_partials, "start_wayback", start_wayback)
    crawler.post(
        f"{PARTIALS}/crawl",
        data={
            "mode": "wayback",
            "domain": "theroseofeternity.com",
            "from_ts": "2017-05-01",
            "exclude": "*/feed/*\n",
        },
    )
    (request,) = asked
    assert (request.domain, request.from_ts) == (
        "theroseofeternity.com",
        "20170501",
    )
    assert request.options.exclude == ["*/feed/*"]


def test_a_bad_crawl_is_refused_in_a_toast(crawler: TestClient) -> None:
    response = crawler.post(f"{PARTIALS}/crawl", data={"mode": "site", "seeds": ""})
    assert response.status_code == 200
    assert "error" in response.headers["HX-Trigger"]


async def test_a_finished_job_shows_what_it_fetched(crawler: TestClient) -> None:
    async def work(handle: Any) -> dict[str, Any]:
        return CrawlSummary(requested=1, fetched=1).model_dump() | {
            "pages": [{"url": "https://rose.test/", "status": 200, "size": 10}]
        }

    runner = get_job_runner()
    job_id = runner.start("crawler-batch:1", work)
    await runner.wait(job_id)
    html = _get(crawler, "crawl", f"job={job_id}")
    assert "https://rose.test/" in text(one(html, "#crawler-job"))
    assert one(html, "#crawler-job [data-status]").get("data-status") == "done"
    frames = [f async for f in overseer_crawler.job_events(job_id, max_frames=1)]
    assert frames and "https://rose.test/" in frames[0]
