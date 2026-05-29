"""Tests for domain enum helpers."""

from src.core.enums import BidStatus, TradeCategory


def test_in_progress_statuses_are_resumable() -> None:
    for status in (BidStatus.VALIDATING, BidStatus.MATCHING_PROJECT, BidStatus.CATEGORIZING_JOB):
        assert status.is_in_progress is True
        assert status.is_terminal is False


def test_terminal_statuses() -> None:
    for status in (BidStatus.CATEGORIZED, BidStatus.REJECTED, BidStatus.FAILED):
        assert status.is_terminal is True
        assert status.is_in_progress is False


def test_trade_from_label_is_case_insensitive() -> None:
    assert TradeCategory.from_label("hvac") is TradeCategory.HVAC
    assert TradeCategory.from_label("  Electrical ") is TradeCategory.ELECTRICAL
    assert TradeCategory.from_label("Metals/Steel") is TradeCategory.METALS_STEEL


def test_trade_from_label_unknown_defaults_to_other() -> None:
    assert TradeCategory.from_label("Underwater Basket Weaving") is TradeCategory.OTHER
