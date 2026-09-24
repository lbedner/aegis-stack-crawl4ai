"""PluginSpec for ``aegis-stack-crawl4ai``.

Declares a service-flavoured plugin that adds web-crawling-to-markdown
capability to an Aegis Stack project. Wraps the upstream ``crawl4ai``
library (Apache 2.0). Aegis discovers this spec via the
``aegis.plugins`` entry point in ``pyproject.toml`` (see
``aegis.core.plugins.discovery``).

Design notes:

- ``MigrationSpec(schema="crawler")`` — the plugin's tables live in
  their own Postgres schema, isolated from the project's other services.
  SQLite has no schemas; there the table lands unqualified.
- ``required_components=['database']`` — the resolver auto-installs
  the database component if the target project doesn't have it.
- ``crawled_page`` table is generic by design (URL + content + metadata
  JSONB) so future ingestion plugins (RSS, PDF, sitemap) can either
  share the schema or follow the same shape.
"""

from aegis.core.file_manifest import FileManifest
from aegis.core.migration_spec import MigrationSpec
from aegis.core.plugins.spec import (
    FrontendWidgetWiring,
    HealthCheckWiring,
    PluginKind,
    PluginSpec,
    PluginWiring,
    RouterWiring,
    SymbolWiring,
)

# The name the health check reports under. The dashboard groups services
# by it, the card factory dispatches on it, and the modal registers under
# ``service_<label>``; the rendered code mirrors it in
# ``app/components/frontend/dashboard/crawler_ui.py``, which derives it
# from ``SERVICE_NAME`` in the service package. One spelling, because a
# mismatch is a dead click rather than an error.
HEALTH_LABEL = "Crawler"


def get_spec() -> PluginSpec:
    """Return the plugin spec."""
    return PluginSpec(
        name="crawl4ai",
        kind=PluginKind.SERVICE,
        description="Web crawling and scraping via Crawl4AI",
        version="0.1.0rc2",
        verified=False,
        # PEP 440 specifier — the spec declares no tables (a revision is
        # derived from the model), which the CLI only understands from
        # 0.12 on. 0.13.1 is where the generated card-render test stops
        # failing on a plugin's card, so anything older installs and then
        # hands the user a red ``make check``.
        aegis_version=">=0.13.1",
        # CLI verb the plugin exposes in the generated project. Decoupled
        # from the install identifier (``crawl4ai``) so users type the
        # natural ``<project> crawl ...`` instead of the package name.
        cli_name="crawl",
        # Resolver auto-installs database if missing.
        required_components=["database"],
        # Pinned to >=0.8.6 because 0.8.6 is the supply-chain hotfix
        # that swapped the compromised ``litellm`` package out — earlier
        # 0.8.x builds pull the bad transitive dep.
        # ``alembic`` is required because this plugin ships migrations;
        # database-only projects (no auth / no insights) don't pull it
        # transitively, so we declare it here.
        pyproject_deps=["crawl4ai>=0.8.6", "alembic>=1.13"],
        # Generic ``pages`` table — URL + content + JSONB metadata.
        # Indexed on source_url, content_hash, and fetched_at for the
        # three common query shapes (last fetch, dedup, time-window).
        # ``doc_metadata`` rather than ``metadata`` because the latter
        # is reserved on SQLAlchemy's ``DeclarativeBase``.
        migrations=[
            MigrationSpec(
                service_name="crawler",
                description="Crawled page store",
                # Proof it ran: the startup hook stamps instead of
                # replaying DDL on a database that already has this.
                stamp_signature=("table", "crawler.crawled_page"),
                # Crawler tables live in their own ``crawler`` Postgres
                # schema. SQLite has no schemas: the generator drops the
                # qualifier there and the model gates ``__table_args__``
                # on the engine, so one declaration serves both.
                schema="crawler",
            ),
        ],
        # All files this plugin owns inside the target project.
        # ``aegis remove`` walks this list to clean up.
        files=FileManifest(
            primary=[
                "app/services/crawler",
                "app/components/backend/api/crawler",
                "app/components/frontend/dashboard/crawler_ui.py",
                "app/components/frontend/dashboard/cards/crawler_card.py",
                "app/components/frontend/dashboard/modals/crawler_modal.py",
                "app/components/frontend/dashboard/modals/crawler_pages_tab.py",
                "app/components/frontend/dashboard/modals/crawler_crawl_tab.py",
                "app/cli/crawl.py",
            ]
        ),
        wiring=PluginWiring(
            routers=[
                RouterWiring(
                    module="app.components.backend.api.crawler.router",
                    symbol="router",
                    prefix="/api/v1/crawler",
                    tags=["crawler"],
                ),
            ],
            settings_mixins=[
                SymbolWiring(
                    module="app.services.crawler.settings",
                    symbol="CrawlerSettingsMixin",
                ),
            ],
            health_checks=[
                HealthCheckWiring(
                    module="app.services.crawler.health",
                    symbol="crawler_health",
                    label=HEALTH_LABEL,
                ),
            ],
            dashboard_cards=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.cards.crawler_card",
                    symbol="CrawlerCard",
                    # ``modal_id`` here doubles as the dispatch key the
                    # frontend uses to pick this card, so it is the health
                    # label itself.
                    modal_id=HEALTH_LABEL,
                ),
            ],
            dashboard_modals=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.modals.crawler_modal",
                    symbol="CrawlerDetailDialog",
                    # The key the dashboard's click handler emits, and the
                    # one ``dashboard.crawler_ui.MODAL_KEY`` gives the card.
                    modal_id=f"service_{HEALTH_LABEL}",
                ),
            ],
        ),
    )
