"""The crawler's tools, as an agent finds them: reads, for anyone the
registry lets in, served over MCP."""

import app.services.crawler.tools  # noqa: F401 - registers at import
from app.core.tools import get_tool, mcp_servable


def test_the_reads_are_registered_and_servable() -> None:
    for name in ("crawler_sites", "crawler_pages", "crawler_page"):
        tool = get_tool(name)
        assert tool is not None and tool.effect == "read", name
    assert set(mcp_servable(["crawler_sites", "crawler_pages", "crawler_page"])) == {
        "crawler_sites",
        "crawler_pages",
        "crawler_page",
    }
