"""The crawler's tools, as an agent finds them: reads, for anyone the
registry lets in, served over MCP."""

from typing import get_args, get_type_hints

from pydantic import BaseModel

from app.core.tools import get_tool, mcp_servable
import app.services.crawler.tools  # noqa: F401 - registers at import


def test_the_reads_are_registered_and_servable() -> None:
    for name in ("crawler_sites", "crawler_pages", "crawler_page"):
        tool = get_tool(name)
        assert tool is not None and tool.effect == "read", name
    assert set(mcp_servable(["crawler_sites", "crawler_pages", "crawler_page"])) == {
        "crawler_sites",
        "crawler_pages",
        "crawler_page",
    }


def test_each_read_hands_back_models() -> None:
    """What a tool returns types code mode's script and an MCP client: a
    model's fields, never a dict's keys."""
    for name in ("crawler_sites", "crawler_pages", "crawler_page"):
        tool = get_tool(name)
        assert tool is not None
        returned = model = get_type_hints(tool.func)["return"]
        while get_args(model):
            model = next(a for a in get_args(model) if a is not type(None))
        assert isinstance(model, type) and issubclass(model, BaseModel), (
            name,
            returned,
        )
