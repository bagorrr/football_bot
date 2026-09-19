# Ticket #104 UML Viewer architecture diagnostic

## Result

- Diagnostic execution: **PASS**. The requested source and tool revisions were verified, the import graph was rebuilt from the source, the EDN was loaded and reloaded by UML Viewer, and the rendered module view was captured.
- Architecture gate: **BLOCKED**. The source import graph contains one six-node strongly connected component that crosses application, persistence, test support, and an `apps` acceptance entry point. Three outward dependency edges are marked as violations in the EDN and rendered in red.
- Scope: static architecture diagnosis only. No Football Bot test or runtime command was run, and no production or protected environment was touched.

## Revisions and inputs

| Item | Exact value |
| --- | --- |
| Repository | `bagorrr/football_bot` |
| Base `origin/main` | [`bc77771d4f4b696f8ae4d18a1b954185e571206e`](https://github.com/bagorrr/football_bot/commit/bc77771d4f4b696f8ae4d18a1b954185e571206e) |
| Source branch | `codex/ticket-104-six-role-integration` |
| Source / PR #118 head | [`15fe70b1af0b0f77c6cdc45d6b937abdba5f73fa`](https://github.com/bagorrr/football_bot/commit/15fe70b1af0b0f77c6cdc45d6b937abdba5f73fa) |
| Diagnostic branch | `codex/ticket-104-uml-diagnostic` |
| UML Viewer | [`unclebob/uml-viewer@8e1c88d40ef1806ce60a6e83cf6ca894a5f95f61`](https://github.com/unclebob/uml-viewer/commit/8e1c88d40ef1806ce60a6e83cf6ca894a5f95f61) |
| Product sources | [Issue #99](https://github.com/bagorrr/football_bot/issues/99), [six-role amendment](https://github.com/bagorrr/football_bot/issues/99#issuecomment-5664415306), [Ticket #104](https://github.com/bagorrr/football_bot/issues/104), and [PR #118](https://github.com/bagorrr/football_bot/pull/118) |

## Artifacts

| Artifact | Description | SHA-256 |
| --- | --- | --- |
| [`architecture.edn`](architecture.edn) | Hand-written hierarchical UML Viewer IR | `513ec24a26d4e0d67fba2c9b3ceedd32822c3ba6b1ba2de11cdfdd3886435d9a` |
| [`architecture.png`](architecture.png) | Actual UML Viewer GUI render of the `modules` view | `90ec78d9a2636dd6eb1d9f00fb97d4fd59f0144a182f068ddebb548c55517fb0` |

The IR contains 41 nodes and 119 edges:

- 31 project nodes: every Python module under `apps/` and `modules/`, including package `__init__.py` modules;
- 10 confirmed external/runtime nodes;
- 101 unique internal import dependencies;
- 18 runtime or external associations confirmed by source, deployment configuration, or repository architecture documentation;
- 3 dependency-rule violations.

## Method

1. Parsed every `apps/**/*.py` and `modules/**/*.py` file with Python's AST and resolved absolute and relative imports to project module IDs. Imports inside functions were retained because they are real source dependencies, even when execution is deferred.
2. Used a hand-written EDN IR because the pinned UML Viewer LanguageGraph implementation is Clojure-specific. No previous UML report was searched, copied, or used as input.
3. Added only code-confirmed runtime associations: launcher-to-role service, the one-shot T3 worker, systemd, PostgreSQL/psycopg, Telethon/MTProto, Telegram Bot API, GeoNames, LocationIQ, Codex CLI, OpenAI Codex SDK, the inactive Responses API path, and IANA time-zone data.
4. Assigned display levels only to make the graph readable: core contracts/domain, ports/configuration, application/promotion, adapters, bootstrap, then `apps`. These levels are visualization metadata, not a claim that the repository enforces those layers mechanically.
5. Loaded the EDN with UML Viewer's own document loader, opened the GUI, drilled into `modules`, reloaded the final EDN with `R`, and captured the rendered window at 3248×2012 pixels.

## Findings

1. **The requested six-role topology is represented.** Five long-running roles—`ingestion`, `application`, `classification`, `recommendation`, and `bot_assistant`—are admitted by [`apps/runtime_launcher.py`](https://github.com/bagorrr/football_bot/blob/15fe70b1af0b0f77c6cdc45d6b937abdba5f73fa/apps/runtime_launcher.py#L27-L29). The Bot Assistant adapter separately spawns [`apps/codex_bot_assistant_worker.py`](https://github.com/bagorrr/football_bot/blob/15fe70b1af0b0f77c6cdc45d6b937abdba5f73fa/apps/codex_bot_assistant_worker.py) as the one-shot T3 boundary.
2. **Entrypoints match the deployment shape.** The systemd template executes `apps/runtime_launcher.py --role %i`, and that launcher executes `apps.runtime_service`; health and T2 checkpoint bootstrap remain separate operational entry points.
3. **PostgreSQL is the durable boundary.** `modules.postgres_adapter` is the main persistence adapter, and six modules have confirmed psycopg associations. No in-process object is presented as the authoritative cross-service store in the inspected composition.
4. **Telegram transports are separated correctly.** `modules.telethon_ingestion` owns Telethon/MTProto ingestion, while `modules.bot_api` owns the Telegram Bot API delivery/ingress boundary. The diagram does not collapse these into one provider edge.
5. **The primary direct dependency rule mostly holds.** `modules.domain` imports no project module; `modules.ports` imports only classifier contracts, shared contracts, and domain; `apps.runtime_service` acts as the expected high-fan-out composition root (14 internal imports).
6. **One non-trivial import cycle blocks the architecture gate.** The six-node strongly connected component is `apps.system_acceptance`, `modules.application`, `modules.classifier_promotion`, `modules.player_promotion_runtime`, `modules.postgres_adapter`, and `modules.testkit`. One concrete loop is `application → classifier_promotion → player_promotion_runtime → testkit → application`.
7. **The cycle is caused by outward production dependencies, not only test code pointing inward.** [`modules/player_promotion_runtime.py`](https://github.com/bagorrr/football_bot/blob/15fe70b1af0b0f77c6cdc45d6b937abdba5f73fa/modules/player_promotion_runtime.py#L60-L64) imports the concrete Responses adapter and later imports `modules.testkit`; [`modules.testkit/__init__.py`](https://github.com/bagorrr/football_bot/blob/15fe70b1af0b0f77c6cdc45d6b937abdba5f73fa/modules/testkit/__init__.py#L5246-L5247) imports both an `apps` entry point and the PostgreSQL adapter. These three outward edges are marked as violations.
8. **Concentration is high beyond the expected composition root.** `modules.application` is 33,382 lines with 8 outgoing project dependencies, `modules.postgres_adapter` is 20,688 lines, and `modules.testkit` is 5,497 lines with 10 outgoing project dependencies. This is a maintainability risk and amplifies the cycle, but file size alone is not treated as a specification failure.
9. **The Responses API edge is not evidence of an active production provider.** The module exists and is reachable from the promotion runtime, but the inspected runtime composition selects the Codex CLI classifier and the Codex SDK assistant worker; the diagram therefore labels Responses as an inactive provider path.

## Interpretation limits

- This is a static import graph plus confirmed associations. It does not prove that every deferred import executes in every role or environment.
- UML Viewer's native Clojure analysis metrics do not apply to this Python repository. No Python CRAP, coverage, cyclomatic-complexity, or mutation metrics were supplied, so missing metrics or viewer colors must not be interpreted as Python quality evidence.
- The PNG is an overview. The EDN is the canonical artifact for interactive drill-down and exact edge inspection.

## Recommendation for the next Ticket #104 coordinator

Treat the architecture gate as blocking and dispatch one narrowly scoped fix task to remove `player_promotion_runtime` dependencies on `modules.testkit` and the concrete Responses adapter, then break the remaining six-node SCC and regenerate this diagnostic on the exact new head before deciding whether PR #118 can advance.
