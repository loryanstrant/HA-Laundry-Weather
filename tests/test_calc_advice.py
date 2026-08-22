"""The advice sentence — the one surface a non-developer actually reads."""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from custom_components.laundry_weather import calc

from .conftest import TEST_TZ

BRING_BY = datetime(2026, 8, 22, 17, 51, tzinfo=TEST_TZ)
MOVE_AT = datetime(2026, 8, 22, 11, 0, tzinfo=TEST_TZ)


def advice(**overrides) -> str:
    kwargs = {
        "spot": "Sunroom",
        "score": 8.24,
        "band_word": "Moderate",
        "sun": 4.15,
        "cov": 2.86,
        "move_at": None,
        "bring_by": BRING_BY,
        "window_text": "Sun 11:00-16:00 (peak 16.2)",
        "dew": True,
        "washing_out": False,
    }
    kwargs.update(overrides)
    return calc.build_advice(**kwargs)


def test_leads_with_the_place_and_the_band() -> None:
    """The band is the answer; the number is supporting detail."""
    assert advice().startswith("Sunroom now (8.2, moderate).")


def test_never_exceeds_the_state_limit() -> None:
    long_form = advice(
        spot="The upstairs spare bedroom with the big north-facing window",
        window_text="Sun 06:00-Mon 19:00 (peak 24.7)",
    )
    assert len(long_form) <= calc.ADVICE_LIMIT


def test_the_answer_survives_truncation() -> None:
    """Whatever gets dropped, the place and the bring-in time stay."""
    long_form = advice(
        spot="The upstairs spare bedroom with the big north-facing window",
        window_text="Sun 06:00-Mon 19:00 (peak 24.7)",
        move_at=MOVE_AT,
    )
    assert long_form.startswith("The upstairs spare bedroom")
    assert "in by 17:51" in long_form


def test_optional_clauses_are_dropped_least_useful_first() -> None:
    short = calc.build_advice(
        spot="Sunroom",
        score=8.24,
        band_word="Moderate",
        sun=4.15,
        cov=2.86,
        move_at=MOVE_AT,
        bring_by=BRING_BY,
        window_text="Sun 11:00-16:00 (peak 16.2)",
        dew=True,
        washing_out=False,
        limit=80,
    )
    # Dew goes first, then the window, then the comparison.
    assert "Dew overnight" not in short
    assert "Best Sun" not in short
    assert "Move out 11:00" in short


def test_no_entity_ids_or_jargon_leak_through() -> None:
    """This string is read by someone who has never seen an entity id."""
    text = advice(move_at=MOVE_AT)
    assert not re.search(r"\b(sensor|binary_sensor|weather|input_\w+)\.", text)
    assert "hPa" not in text
    assert "VPD" not in text


def test_says_when_outside_is_never_worth_it() -> None:
    """And still gives a bring-in time, because washing may already be out."""
    text = advice(move_at=None)
    assert "Outside will not beat inside today" in text
    assert "in by 17:51" in text


def test_wording_changes_when_the_washing_is_already_out() -> None:
    """The urgent fact is no longer 'where', it is 'when to rescue it'."""
    text = advice(washing_out=True, move_at=MOVE_AT)
    assert text.startswith("Washing is out - bring in by 17:51.")
    assert "is fastest now" in text


def test_no_window_no_window_clause() -> None:
    assert "Best" not in advice(window_text=None)


def test_no_dew_no_dew_clause() -> None:
    assert "Dew overnight" not in advice(dew=False)


def test_reproduces_the_production_sentence() -> None:
    """Character for character against the live reference implementation."""
    assert advice() == (
        "Sunroom now (8.2, moderate). Sun 4.2 vs cover 2.9. Outside will not "
        "beat inside today; if it is out, in by 17:51. "
        "Best Sun 11:00-16:00 (peak 16.2). Dew overnight."
    )


@pytest.mark.parametrize("band_word", calc.BAND_NAMES)
def test_the_band_word_is_always_present(band_word: str) -> None:
    assert band_word.lower() in advice(band_word=band_word)
