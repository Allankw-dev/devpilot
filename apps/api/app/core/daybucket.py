"""Grouping rows by UTC calendar day, the same way on PostgreSQL and SQLite."""

from datetime import date, datetime

from sqlalchemy import ColumnElement, func
from sqlalchemy.orm import InstrumentedAttribute, Session


def day_bucket(
    db: Session, column: InstrumentedAttribute[datetime | None] | InstrumentedAttribute[datetime]
) -> ColumnElement[object]:
    """The UTC calendar day of a timestamp column."""
    if db.get_bind().dialect.name == "postgresql":
        return func.date(func.timezone("UTC", column))
    return func.date(column)


def to_date(value: object) -> date:
    """A day from either database: PostgreSQL gives a date, SQLite gives text."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
