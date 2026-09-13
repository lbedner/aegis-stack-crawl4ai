"""Pin the contract of ``get_spec()`` so refactors can't silently
change the plugin's identity, dependencies, or wiring.

Anything that changes the install behaviour of ``aegis add crawl4ai``
should be reflected here as a deliberate test update.
"""

from __future__ import annotations

import re
from pathlib import Path

from aegis.core.migration_spec import MigrationSpec
from aegis.core.plugins.spec import PluginKind, PluginSpec

from aegis_stack_crawl4ai.plugin import get_spec

MODEL = (
    Path(__file__).resolve().parents[1]
    / "src/aegis_stack_crawl4ai/templates/{{ project_slug }}"
    / "app/services/crawler/models.py.jinja"
).read_text()


def _model_field_declarations() -> dict[str, str]:
    """Each field on the crawled_page model, with its full declaration.

    The revision is derived from this model, so the table's shape is
    pinned here rather than in the spec. Read as text: the module is a
    jinja template (the Postgres schema is gated on the engine), so it
    does not import as-is.
    """
    fields: dict[str, str] = {}
    current: str | None = None
    for line in MODEL.splitlines():
        match = re.match(r"    (\w+): ", line)
        if match:
            current = match.group(1)
            fields[current] = line
        elif current and line.startswith("        "):
            fields[current] += "\n" + line
        elif line.strip() and not line.startswith("    "):
            current = None
    return fields


def _model_fields() -> set[str]:
    return set(_model_field_declarations())


def _model_indexed_fields() -> set[str]:
    return {
        name
        for name, declaration in _model_field_declarations().items()
        if "index=True" in declaration
    }


class TestIdentity:
    def test_returns_pluginspec(self) -> None:
        assert isinstance(get_spec(), PluginSpec)

    def test_name_and_kind(self) -> None:
        spec = get_spec()
        assert spec.name == "crawl4ai"
        assert spec.kind == PluginKind.SERVICE

    def test_unverified_third_party(self) -> None:
        """Third-party plugins must declare ``verified=False`` so the CLI
        flags them appropriately in ``aegis plugins list``."""
        assert get_spec().verified is False

    def test_aegis_version_pinned(self) -> None:
        """Pin to a CLI version that has the schema-isolation foundation."""
        spec = get_spec()
        assert spec.aegis_version
        assert ">=" in spec.aegis_version


class TestSchemaIsolation:
    """The plugin's tables live in their own Postgres schema."""

    def test_migration_declares_crawler_schema(self) -> None:
        spec = get_spec()
        assert spec.migrations
        migration = next(m for m in spec.migrations if isinstance(m, MigrationSpec))
        assert migration.schema == "crawler"
        # The revision's contents come from the model; the spec names the
        # object whose existence proves the revision ran.
        assert migration.stamp_signature == ("table", "crawler.crawled_page")
        assert '__tablename__ = "crawled_page"' in MODEL


class TestDependencies:
    def test_requires_database(self) -> None:
        """Auto-installs the database component if the project lacks it."""
        assert "database" in get_spec().required_components

    def test_pyproject_dep_pins_security_hotfix(self) -> None:
        """v0.8.6 is the supply-chain hotfix — earlier 0.8.x pulls the
        compromised ``litellm`` transitive dep."""
        spec = get_spec()
        crawl4ai_dep = next(d for d in spec.pyproject_deps if d.startswith("crawl4ai"))
        # PEP 440 lower-bound parse — ">=0.8.6" or stricter.
        assert ">=0.8.6" in crawl4ai_dep or "==0.8.6" in crawl4ai_dep


class TestMigrations:
    """The table's shape lives in the model - that is what the generated
    project's revision is derived from - so these read the model."""

    def test_documents_columns_match_design(self) -> None:
        """Pin the pages-table shape — generic enough that future
        ingestion plugins (RSS, PDF, sitemap) can share the schema or
        copy the shape. See the plan file for the design discussion."""
        column_names = _model_fields()
        # Required columns the table contract has to maintain.
        for required in (
            "id",
            "source_url",
            "content",
            "content_hash",
            "content_type",
            "doc_metadata",
            "status_code",
            "source_kind",
            "fetched_at",
        ):
            assert required in column_names, (
                f"crawled_page table missing required column {required!r}"
            )

    def test_documents_indexes(self) -> None:
        """Three indexes for the three common query shapes:
        last-fetch-by-url, dedup-by-hash, time-window."""
        indexed = _model_indexed_fields()
        assert "source_url" in indexed
        assert "content_hash" in indexed
        assert "fetched_at" in indexed


class TestWiring:
    def test_router_mounted_at_versioned_prefix(self) -> None:
        spec = get_spec()
        router = spec.wiring.routers[0]
        # With the other routers under the backend component, not in
        # the service package: the service is business logic.
        assert router.module == "app.components.backend.api.crawler.router"
        assert router.symbol == "router"
        assert router.prefix == "/api/v1/crawler"

    def test_settings_mixin_registered(self) -> None:
        spec = get_spec()
        mixin = next(
            m for m in spec.wiring.settings_mixins if m.symbol == "CrawlerSettingsMixin"
        )
        # Mixin lives in its own leaf module so importing it from
        # ``app/core/config.py`` doesn't drag the runtime stack in
        # (would otherwise trigger a circular import).
        assert mixin.module == "app.services.crawler.settings"

    def test_health_check_registered(self) -> None:
        spec = get_spec()
        assert any(h.symbol == "crawler_health" for h in spec.wiring.health_checks)

    def test_dashboard_card_registered(self) -> None:
        spec = get_spec()
        card = next(c for c in spec.wiring.dashboard_cards if c.symbol == "CrawlerCard")
        # ``modal_id`` doubles as the dashboard dispatch key. Match the
        # health-check label so ``service_Crawler`` routes to this card.
        assert card.modal_id == "Crawler"
        health = next(h for h in spec.wiring.health_checks)
        assert card.modal_id == health.label, (
            "the card dispatch key is the health label"
        )

    def test_dashboard_modal_registered(self) -> None:
        """The card's click should open ``CrawlerDetailDialog`` via modal_map.

        The framework's ``modal_map`` is keyed by ``service_<label>`` for
        service health checks; the modal entry's ``modal_id`` must match
        that key so the dispatch lands here.
        """
        spec = get_spec()
        modal = next(
            m for m in spec.wiring.dashboard_modals if m.symbol == "CrawlerDetailDialog"
        )
        assert modal.module == (
            "app.components.frontend.dashboard.modals.crawler_modal"
        )
        assert modal.modal_id == "service_Crawler"
        health = next(h for h in spec.wiring.health_checks)
        assert modal.modal_id == f"service_{health.label}", (
            "the modal registers under service_<health label>"
        )


class TestFileManifest:
    def test_owns_crawler_service_dir(self) -> None:
        """``aegis remove crawl4ai`` walks ``files.primary`` to clean up.
        Anything the plugin creates outside this list will be orphaned."""
        spec = get_spec()
        assert "app/services/crawler" in spec.files.primary
