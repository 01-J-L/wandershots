"""Small, idempotent schema upgrades for the existing WanderShots database.

The project historically relied on ``db.create_all()``. That creates new tables
but never adds indexes to tables that already exist. These upgrades are safe to
run on every application start and never drop or rewrite data.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from . import db

logger = logging.getLogger(__name__)


INDEX_UPGRADES = (
    ('booking', 'ix_booking_status_date_archived', ('status', 'date', 'is_archived')),
    ('booking', 'ix_booking_user_id', ('user_id',)),
    ('booking', 'ix_booking_date', ('date',)),
    ('booking', 'ix_booking_created_at', ('created_at',)),
    ('contact_message', 'ix_contact_message_archived_date', ('is_archived', 'date')),
    ('blocked_date', 'ix_blocked_date_date', ('date',)),
    ('portfolio_item', 'ix_portfolio_item_created_at', ('created_at',)),
)

COLUMN_UPGRADES = (
    ('booking_calendar_sync', 'event_generation', 'INTEGER NOT NULL DEFAULT 0'),
)


def _existing_indexes(inspector, table):
    names = {index.get('name') for index in inspector.get_indexes(table) if index.get('name')}
    names.update(
        constraint.get('name')
        for constraint in inspector.get_unique_constraints(table)
        if constraint.get('name')
    )
    return names


def _ensure_column(inspector, table, column, definition):
    columns = {col['name'] for col in inspector.get_columns(table)}
    if column in columns:
        return
    statement = f'ALTER TABLE {table} ADD COLUMN {column} {definition}'
    with db.engine.begin() as connection:
        connection.execute(text(statement))
    logger.info('Added missing column %s.%s', table, column)


def upgrade_schema():
    """Apply additive indexes/columns that ``create_all`` cannot add."""
    try:
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
    except Exception as exc:  # pragma: no cover - database is unavailable
        logger.warning('Skipping schema upgrade, database inspection failed: %s', exc)
        return

    for table, column, definition in COLUMN_UPGRADES:
        if table not in tables:
            continue
        try:
            _ensure_column(inspector, table, column, definition)
        except Exception as exc:
            logger.warning('Could not add column %s.%s: %s', table, column, exc)

    # Refresh after possible column changes.
    inspector = inspect(db.engine)
    for table, index_name, columns in INDEX_UPGRADES:
        if table not in tables:
            continue
        try:
            if index_name in _existing_indexes(inspector, table):
                continue
            column_sql = ', '.join(columns)
            statement = f'CREATE INDEX {index_name} ON {table} ({column_sql})'
            with db.engine.begin() as connection:
                connection.execute(text(statement))
            logger.info('Created index %s on %s', index_name, table)
        except Exception as exc:
            # Duplicate index names and restricted hosting accounts should not
            # prevent the application from starting.
            logger.warning('Could not create index %s on %s: %s', index_name, table, exc)
