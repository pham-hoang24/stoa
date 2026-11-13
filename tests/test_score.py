"""Seam: stoa.eval.score.correct — challenge scoring rules from the dataset README."""
from stoa.eval.score import correct


def test_count_must_be_exact():
    assert correct("count", 13, 13)
    assert not correct("count", 13, 12)
    assert not correct("count", 13, 13.5)


def test_area_within_two_percent():
    assert correct("area", 100.0, 101.9)
    assert correct("area", 100.0, 98.1)
    assert not correct("area", 100.0, 102.1)


def test_length_and_volume_use_same_tolerance():
    assert correct("length", 185.129, 185.129 * 1.019)
    assert not correct("volume", 53.427, 53.427 * 1.03)


def test_abstain_is_never_correct():
    assert not correct("count", 0, None)
    assert not correct("area", 5.0, None)


def test_text_requires_the_numbers_in_truth():
    assert correct("text", "Total Walls: 121", "There are 121 walls")
    assert not correct("text", "Total Walls: 121", "There are 120 walls")
