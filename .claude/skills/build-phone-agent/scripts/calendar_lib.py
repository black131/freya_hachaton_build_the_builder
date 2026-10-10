# Calendar helpers for Freya code nodes. Standard library only.
#
# This file is pasted in front of the snippet you write for a code node
# (scripts/build_code.py does that). It holds NO bank rule: every holiday,
# weekend, band and deadline comes from the brief, through the RULES dict that
# your snippet defines.
#
# It is written without a doubled opening or closing brace anywhere, because
# Freya may treat those as template placeholders inside a code node.

import datetime as _dt
import json as _json
import re as _re

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def parse_now(value):
    """Turn the call variable `now` (for example 2026-10-14T11:00) into a datetime."""
    text = str(value or "").strip().replace("Z", "")
    m = _re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2}))?", text)
    if not m:
        raise ValueError("cannot read now: " + text)
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4) or 0)
    mm = int(m.group(5) or 0)
    return _dt.datetime(y, mo, d, hh, mm)


def to_date(value):
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    return _dt.date.fromisoformat(str(value)[:10])


def spoken(d):
    """Monday 26 October 2026"""
    d = to_date(d)
    return "%s %d %s %d" % (_DAY_NAMES[d.weekday()], d.day, _MONTHS[d.month - 1], d.year)


class Calendar:
    """Business-day arithmetic.

    weekend:  Python weekday numbers that are not business days (Monday=0 ... Sunday=6).
    holidays: ISO dates that are not business days.
    """

    def __init__(self, weekend=(5, 6), holidays=()):
        self.weekend = set(int(x) for x in weekend)
        self.holidays = set(to_date(h) for h in holidays)

    def is_business_day(self, d):
        d = to_date(d)
        return d.weekday() not in self.weekend and d not in self.holidays

    def why_not(self, d):
        """'' for a business day, else 'weekend' or 'holiday'."""
        d = to_date(d)
        if d in self.holidays:
            return "holiday"
        if d.weekday() in self.weekend:
            return "weekend"
        return ""

    def next_business_day(self, d, include_today=False):
        """The first business day after d (or d itself when include_today and d is one)."""
        d = to_date(d)
        if include_today and self.is_business_day(d):
            return d
        d += _dt.timedelta(days=1)
        while not self.is_business_day(d):
            d += _dt.timedelta(days=1)
        return d

    def previous_business_day(self, d, include_today=True):
        d = to_date(d)
        if include_today and self.is_business_day(d):
            return d
        d -= _dt.timedelta(days=1)
        while not self.is_business_day(d):
            d -= _dt.timedelta(days=1)
        return d

    def add_business_days(self, d, n):
        """The n-th business day after d. d itself is never counted."""
        d = to_date(d)
        for _ in range(int(n)):
            d = self.next_business_day(d)
        return d

    def add_calendar_days(self, d, n, roll="none"):
        """d + n calendar days. roll: none, back (to the previous business day), forward."""
        d = to_date(d) + _dt.timedelta(days=int(n))
        if roll == "back":
            return self.previous_business_day(d)
        if roll == "forward":
            return self.next_business_day(d, include_today=True)
        return d

    def week_start(self, d):
        d = to_date(d)
        return d - _dt.timedelta(days=d.weekday())

    def last_business_day_of_week(self, d, weeks_ahead=0):
        """The last business day of d's calendar week (Monday to Sunday), or of a later week."""
        start = self.week_start(d) + _dt.timedelta(days=7 * int(weeks_ahead))
        for i in range(6, -1, -1):
            day = start + _dt.timedelta(days=i)
            if self.is_business_day(day):
                return day
        return None

    def weekday_in_week(self, d, weekday, weeks_ahead=0):
        """The given weekday (0=Monday) in d's week, or in a later week."""
        start = self.week_start(d) + _dt.timedelta(days=7 * int(weeks_ahead))
        return start + _dt.timedelta(days=int(weekday))

    def last_business_day_of_month(self, d, months_ahead=0):
        d = to_date(d)
        y, m = d.year, d.month + int(months_ahead)
        while m > 12:
            y, m = y + 1, m - 12
        first_next = _dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        return self.previous_business_day(first_next - _dt.timedelta(days=1))

    def table(self, start, days, deadline=None):
        """One line per calendar day from start: date, weekday, status. Give it to the model
        so it can check any date the customer names without doing date arithmetic."""
        start = to_date(start)
        out = []
        for i in range(int(days)):
            d = start + _dt.timedelta(days=i)
            why = self.why_not(d)
            if why:
                status = "NOT a business day (%s), next business day %s" % (why, self.next_business_day(d).isoformat())
            else:
                status = "business day"
            if deadline is not None and d > to_date(deadline):
                status += ", AFTER the deadline"
            out.append("%s %s: %s" % (d.isoformat(), _DAY_NAMES[d.weekday()], status))
        return "\n".join(out)


def answer_table(cal, start, days, answer):
    """One line per calendar day from start, each with the RESPONSE the agent must give when the
    customer names that day. `answer(d)` is a function you write from the brief's date rules; it
    returns the text for one day, for example 'accept' or 'offer Tuesday 27 October 2026 (2026-10-27)'.

    Prefer this to `Calendar.table`: a table of statuses still makes the model combine two or three
    rules (weekend, holiday, deadline) in its head, and it gets that wrong some of the time. A table
    of answers needs only a lookup.
    """
    start = to_date(start)
    out = []
    for i in range(int(days)):
        d = start + _dt.timedelta(days=i)
        out.append("%s %s: %s" % (d.isoformat(), _DAY_NAMES[d.weekday()], answer(d)))
    return "\n".join(out)


def read_list(vars_, *names):
    """Read a list that an earlier api_request node stored. It can arrive as a list,
    as a JSON string, or only as flattened keys such as 'x.data.products.0.past_due'."""
    for name in names:
        v = vars_.get(name)
        if isinstance(v, list):
            return v
        if isinstance(v, str) and v.strip().startswith("["):
            try:
                return _json.loads(v)
            except Exception:
                pass
    for name in names:
        prefix = name + "."
        items = {}
        for k, v in vars_.items():
            if not str(k).startswith(prefix):
                continue
            rest = str(k)[len(prefix):].split(".")
            if not rest[0].isdigit():
                continue
            idx = int(rest[0])
            if len(rest) == 1:
                items[idx] = v
            else:
                items.setdefault(idx, {})
                if isinstance(items[idx], dict):
                    items[idx][".".join(rest[1:])] = v
        if items:
            return [items[i] for i in sorted(items)]
    return []


def money(x):
    """Format an amount the way a person reads it: 420 -> 420.00"""
    try:
        return "%.2f" % float(x)
    except Exception:
        return str(x)
