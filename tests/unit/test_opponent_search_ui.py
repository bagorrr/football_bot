"""Focused Opponent Search presentation seams."""

# ruff: noqa: RUF001 -- reviewed multilingual interface copy is intentional.

from __future__ import annotations

import pytest

from modules.application import _opponent_search_detail_submenu_message


@pytest.mark.parametrize(
    ("locale", "expected_labels"),
    (
        (
            "en",
            (
                "Our team has a venue",
                "We need the opponent’s venue",
                "Arrange jointly",
                "Any",
            ),
        ),
        (
            "ru",
            (
                "У нашей команды есть площадка",
                "Нужна площадка соперника",
                "Организуем вместе",
                "Неважно",
            ),
        ),
        (
            "es",
            (
                "Nuestro equipo tiene campo",
                "Necesitamos el campo del rival",
                "Organizar juntos",
                "Cualquiera",
            ),
        ),
        (
            "fr",
            (
                "Notre équipe a un terrain",
                "Nous avons besoin du terrain adverse",
                "Organiser ensemble",
                "Peu importe",
            ),
        ),
    ),
)
def test_venue_provision_renderer_is_one_answer_with_any(
    locale: str,
    expected_labels: tuple[str, ...],
) -> None:
    message = _opponent_search_detail_submenu_message(
        update_id=f"venue-menu:{locale}",
        telegram_user_id=1,
        locale=locale,
        screen_revision=7,
        detail_key="venue_provision",
        temporary=(),
    )

    labels = tuple(row[0][0].removeprefix("✓ ") for row in message.button_rows[:-1])
    callbacks = tuple(row[0][1] for row in message.button_rows[:-1])
    assert labels == expected_labels
    assert all("toggle" not in callback for callback in callbacks)
    assert callbacks[-1] == "opponent-details:venue:any:7"
