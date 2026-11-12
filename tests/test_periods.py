from datetime import date

from app.periods import compare_ranges, month_range


def test_month_range_december():
    assert month_range("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))


def test_current_month_compares_same_days():
    assert compare_ranges("2026-11", date(2026, 11, 12)) == (
        date(2026, 11, 1), date(2026, 11, 13), date(2026, 10, 1), date(2026, 10, 13), 12
    )


def test_day_31_against_shorter_month():
    # 31 марта сравниваем со всем февралём (28 дней)
    assert compare_ranges("2027-03", date(2027, 3, 31))[2:] == (date(2027, 2, 1), date(2027, 3, 1), 31)


def test_past_month_compares_whole_months():
    assert compare_ranges("2026-10", date(2026, 11, 12)) == (
        date(2026, 10, 1), date(2026, 11, 1), date(2026, 9, 1), date(2026, 10, 1), None
    )


def test_january_compares_with_december():
    assert compare_ranges("2027-01", date(2027, 1, 5))[2] == date(2026, 12, 1)
