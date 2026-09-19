from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from modules.application import RuntimeApplication
from modules.contracts import ContractEnvelope, ContractName, RuntimeRole
from modules.domain import (
    SourceChatAddressKind,
    SourceChatAdmissionResolution,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.ports import ConsumeResult
from modules.source_chat_bootstrap import (
    SourceChatBootstrapError,
    bootstrap_source_chat_catalog,
    load_source_chat_seed_catalog,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def test_load_source_chat_seed_catalog_accepts_the_four_approved_seeds() -> None:
    catalog = load_source_chat_seed_catalog(
        REPOSITORY_ROOT / "config" / "source-chats.yaml"
    )

    assert [seed.address for seed in catalog.seeds] == [
        "@piterfut",
        "@lovefootballspb",
        "@fballer_spb",
        "@spbfutbol",
    ]


@pytest.mark.parametrize(
    ("name", "replacement"),
    (
        ("unknown field", "    unexpected: true\n"),
        ("unknown seed", "    username: unknown_source\n"),
        (
            "duplicate seed",
            "  - username: piterfut\n"
            "    url: https://t.me/piterfut\n"
            "    enabled: true\n",
        ),
        ("disabled seed", "    enabled: false\n"),
    ),
)
def test_load_source_chat_seed_catalog_rejects_unsafe_data(
    tmp_path: Path,
    name: str,
    replacement: str,
) -> None:
    del name
    source = (REPOSITORY_ROOT / "config" / "source-chats.yaml").read_text()
    if "unexpected:" in replacement:
        source = source.replace(
            "    url: https://t.me/piterfut\n",
            "    url: https://t.me/piterfut\n" + replacement,
            1,
        )
    elif "unknown_source" in replacement:
        source = source.replace("  - username: piterfut\n", replacement, 1)
    elif "enabled: false" in replacement:
        source = source.replace("    enabled: true\n", replacement, 1)
    else:
        source = source.replace("\n\n", "\n" + replacement + "\n", 1)
    path = tmp_path / "source-chats.yaml"
    path.write_text(source)

    with pytest.raises(SourceChatBootstrapError):
        load_source_chat_seed_catalog(path)


@dataclass
class _Resolver:
    resolutions: dict[str, SourceChatAdmissionResolution]
    boundaries: dict[TelegramPeerIdentity, str]

    def resolve_source_chat(self, address: str) -> SourceChatAdmissionResolution:
        return self.resolutions[address]

    def capture_source_chat_registration_boundary(
        self, identity: TelegramPeerIdentity
    ) -> str:
        return self.boundaries[identity]


@dataclass
class _Publisher:
    envelopes: dict[str, ContractEnvelope]

    def publish_source_chat_seed_resolution(
        self,
        *,
        envelope: ContractEnvelope,
    ) -> None:
        key = envelope.idempotency_key
        self.envelopes.setdefault(key, envelope)


@dataclass
class _RegistryStore:
    registration: dict[str, Any] | None = None

    def register_source_chat(self, **kwargs: Any) -> ConsumeResult:
        self.registration = kwargs
        return ConsumeResult.APPLIED


@dataclass(frozen=True)
class _Clock:
    def now(self) -> datetime:
        return NOW


def test_bootstrap_publishes_exactly_four_deterministic_resolutions_idempotently() -> (
    None
):
    catalog = load_source_chat_seed_catalog(
        REPOSITORY_ROOT / "config" / "source-chats.yaml"
    )
    identities = {
        seed.address: TelegramPeerIdentity(TelegramPeerKind.CHANNEL, index)
        for index, seed in enumerate(catalog.seeds, start=101)
    }
    resolver = _Resolver(
        resolutions={
            seed.address: SourceChatAdmissionResolution(
                identity=identities[seed.address],
                address_kind=SourceChatAddressKind.PUBLIC_USERNAME,
                current_address=seed.address,
            )
            for seed in catalog.seeds
        },
        boundaries={
            identity: f"channel-pts:{index}"
            for index, identity in enumerate(identities.values(), start=1)
        },
    )
    publisher = _Publisher(envelopes={})

    bootstrap_source_chat_catalog(
        catalog,
        ingestion=resolver,
        publisher=publisher,
        telegram_user_id=46_001,
        recorded_at=NOW,
    )
    bootstrap_source_chat_catalog(
        catalog,
        ingestion=resolver,
        publisher=publisher,
        telegram_user_id=46_001,
        recorded_at=NOW,
    )

    assert len(publisher.envelopes) == 4
    assert all(
        envelope.contract_name is ContractName.SOURCE_CHAT_ADMISSION_RESOLVED
        for envelope in publisher.envelopes.values()
    )


def test_application_commits_seed_resolution_without_bot_admin_result() -> None:
    catalog = load_source_chat_seed_catalog(
        REPOSITORY_ROOT / "config" / "source-chats.yaml"
    )
    identities = {
        item.address: TelegramPeerIdentity(TelegramPeerKind.CHANNEL, index)
        for index, item in enumerate(catalog.seeds, start=501)
    }
    resolver = _Resolver(
        resolutions={
            item.address: SourceChatAdmissionResolution(
                identity=identities[item.address],
                address_kind=SourceChatAddressKind.PUBLIC_USERNAME,
                current_address=item.address,
            )
            for item in catalog.seeds
        },
        boundaries={
            identity: f"channel-pts:{index}"
            for index, identity in enumerate(identities.values(), start=1)
        },
    )
    publisher = _Publisher(envelopes={})
    envelope = bootstrap_source_chat_catalog(
        catalog,
        ingestion=resolver,
        publisher=publisher,
        telegram_user_id=46_001,
        recorded_at=NOW,
    )[0]
    store = _RegistryStore()
    application = RuntimeApplication(
        role=RuntimeRole.APPLICATION,
        store=store,  # type: ignore[arg-type]
        clock=_Clock(),
    )

    application._register_source_chat_seed(envelope)

    assert store.registration is not None
    assert store.registration["outgoing"] is None
    assert store.registration["stale_outgoing"] is None
    activation = store.registration["activation_outgoing"]
    assert activation.contract_name is ContractName.SOURCE_CHAT_SCOPE_ACTIVATED
    assert activation.consumer is RuntimeRole.INGESTION
