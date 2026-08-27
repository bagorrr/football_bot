"""Localized optional Number of Players controls."""

import pytest

from modules.application import _player_search_number_message


@pytest.mark.parametrize(
    ("locale", "any_label"),
    (
        ("en", "Any"),
        ("ru", "Неважно"),
        ("es", "Cualquiera"),
        ("fr", "Peu importe"),
    ),
)
def test_number_prompt_renders_localized_clear_control(
    locale: str,
    any_label: str,
) -> None:
    message = _player_search_number_message(
        update_id="number-prompt",
        telegram_user_id=49_900,
        locale=locale,
        screen_revision=17,
    )

    assert message.button_rows[0] == ((any_label, "details:number:any:17"),)
    assert message.button_rows[1][0][1] == "details:back:17"
