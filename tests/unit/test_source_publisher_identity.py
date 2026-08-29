"""Opaque Source Publisher references at the contract boundary."""

from copy import deepcopy
from dataclasses import replace

import pytest

from modules.contracts import ContractEnvelope, RawContractEnvelope
from modules.domain import source_publisher_id_from_metadata
from tests.unit.test_classifier_reply_context import _valid_classify_command


def _classify_command_with_publisher(publisher_id: str) -> RawContractEnvelope:
    command = _valid_classify_command()
    payload = deepcopy(command.payload)
    assert isinstance(payload, dict)
    payload["bounded_metadata"] = {
        "message_language": "ru",
        "attachment_types": [],
        "source_author_dm_url": None,
        "reply_route_url": None,
        "source_message_url": None,
        "source_message_reply_capable": False,
        "source_publisher_id": publisher_id,
    }
    return replace(command, payload=payload)


@pytest.mark.parametrize(
    "publisher_id",
    (
        "publisher:one",
        "publisher:10x10",
        "unknown-publisher:" + "a" * 64,
    ),
)
def test_classifier_contract_accepts_only_the_opaque_publisher_shape(
    publisher_id: str,
) -> None:
    ContractEnvelope.from_raw(_classify_command_with_publisher(publisher_id))


@pytest.mark.parametrize(
    "publisher_id",
    (
        "123456",
        "@publisher",
        "https://t.me/publisher",
        "publisher: with-space",
        " publisher:one",
    ),
)
def test_classifier_contract_rejects_non_opaque_publisher_values(
    publisher_id: str,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        ContractEnvelope.from_raw(_classify_command_with_publisher(publisher_id))


@pytest.mark.parametrize(
    ("metadata_value", "expected"),
    (
        ("publisher:one", "publisher:one"),
        ("@publisher", None),
        ("https://t.me/publisher", None),
        (" publisher:one", None),
        (None, None),
    ),
)
def test_source_publisher_metadata_reader_never_returns_raw_identity(
    metadata_value: object,
    expected: str | None,
) -> None:
    assert (
        source_publisher_id_from_metadata({"source_publisher_id": metadata_value})
        == expected
    )
