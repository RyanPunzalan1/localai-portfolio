"""Portable date text. `strftime("%-d")` (day without a leading zero) works on macOS and Linux but raises on Windows."""


def month_day(t) -> str:
    """'Nov 5' for a datetime or pandas Timestamp; the same text on every platform."""
    return f"{t:%b} {t.day}"
