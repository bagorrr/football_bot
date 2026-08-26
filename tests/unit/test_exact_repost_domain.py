"""Pure exact-repost identity rules."""

from modules.domain import normalize_exact_repost_text


def test_exact_repost_normalization_only_removes_decorative_variation() -> None:
    assert normalize_exact_repost_text(
        "⚽ 4 Players available!!!\nOn 20 August 2026 ⚽"
    ) == normalize_exact_repost_text("4 players available! On 20 August 2026")


def test_exact_repost_normalization_does_not_fuzzy_match_content() -> None:
    assert normalize_exact_repost_text("4 players available") != (
        normalize_exact_repost_text("5 players available")
    )
