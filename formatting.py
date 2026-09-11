"""
Indian financial number formatting utilities.
Used everywhere a rupee amount or large count is displayed in the dashboard.
"""


def format_inr(value: float, decimals: int = 2) -> str:
    """Format a rupee value using Indian Lakh/Crore convention.

    < 1,00,000        -> plain rupees, e.g. ₹45,000
    1,00,000 - 99,99,999   -> Lakhs, e.g. ₹42.00 L
    >= 1,00,00,000     -> Crores, e.g. ₹8.50 Cr
    Negative values are handled (shown with a leading '-').
    """
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_00_00_000:
        return f"{sign}₹{v / 1_00_00_000:.{decimals}f} Cr"
    if v >= 1_00_000:
        return f"{sign}₹{v / 1_00_000:.{decimals}f} L"
    return f"{sign}₹{v:,.0f}"


def format_count(value: float) -> str:
    """Format a plain count (clients, transactions) with Indian digit grouping."""
    if value is None:
        return "-"
    value = int(round(value))
    s = str(abs(value))
    if len(s) <= 3:
        grouped = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ",".join(parts) + "," + last3
    return ("-" if value < 0 else "") + grouped


def format_pct(value: float, decimals: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{decimals}f}%"


def status_from_achievement(pct: float) -> str:
    """Bucket an achievement percentage into a traffic-light status label."""
    if pct is None:
        return "No Target"
    if pct >= 90:
        return "On Track"
    if pct >= 70:
        return "Attention Required"
    return "Critical"


STATUS_COLOR = {
    "On Track": "#1a7f37",
    "Attention Required": "#b98900",
    "Critical": "#c22b2b",
    "No Target": "#6b7280",
}
