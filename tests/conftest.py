"""
Shared pytest fixtures.

Provides:
  - in_memory_db: a fresh SQLite connection (in-memory) with all tables created
  - mock_bot:     a minimal bot-like object with CONN and master_user for permission tests
  - mock_ctx:     a factory for creating mock Discord ApplicationContext objects
"""

import sqlite3
import types
import pytest
import sys
import os

# Ensure the project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db_handler


@pytest.fixture
def in_memory_db():
    """
    Returns a real SQLite connection (in-memory) with all tables and migrations applied.
    Each test gets a completely fresh database.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")

    # Run the same table creation as startup_db but against in-memory DB
    tables = [
        """CREATE TABLE IF NOT EXISTS users (
            user_id  INTEGER PRIMARY KEY,
            secret   TEXT NOT NULL,
            verified INTEGER NOT NULL CHECK (verified IN (0,1))
        )""",
        """CREATE TABLE IF NOT EXISTS guilds (
            guild_id             INTEGER PRIMARY KEY,
            event_channel        INTEGER,
            announcement_channel INTEGER,
            log_channel          INTEGER,
            webhook_protection   INTEGER NOT NULL DEFAULT 1,
            verified_bots        INTEGER NOT NULL DEFAULT 0,
            link_filter_enabled  INTEGER NOT NULL DEFAULT 0,
            panic_active         INTEGER NOT NULL DEFAULT 0,
            announce_timeout     INTEGER NOT NULL DEFAULT 300
        )""",
        """CREATE TABLE IF NOT EXISTS trusted_members (
            trusted_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id   INTEGER NOT NULL,
            member_id  INTEGER NOT NULL,
            UNIQUE (guild_id, member_id)
        )""",
        """CREATE TABLE IF NOT EXISTS channel_table (
            channel_id INTEGER PRIMARY KEY,
            guild_id   INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS link_whitelist (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            type     TEXT NOT NULL CHECK (type IN ('domain','specific')),
            url      TEXT NOT NULL,
            added_by INTEGER,
            UNIQUE (guild_id, type, url)
        )""",
        """CREATE TABLE IF NOT EXISTS safe_roles (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            role_id  INTEGER NOT NULL,
            UNIQUE (guild_id, role_id)
        )""",
        """CREATE TABLE IF NOT EXISTS backup_codes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            code_hash TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS link_managers (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id  INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            UNIQUE (guild_id, member_id)
        )""",
        """CREATE TABLE IF NOT EXISTS panic_role_backup (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            role_id     INTEGER NOT NULL,
            perms_value INTEGER NOT NULL,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS panic_channel_backup (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            channel_id  INTEGER NOT NULL,
            allow_value INTEGER NOT NULL,
            deny_value  INTEGER NOT NULL,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS link_filter_whitelist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            entity_type TEXT NOT NULL CHECK (entity_type IN ('channel','role','user','category')),
            entity_id   INTEGER NOT NULL,
            added_by    INTEGER,
            UNIQUE (guild_id, entity_type, entity_id)
        )""",
        """CREATE TABLE IF NOT EXISTS webhook_temp_disable (
            guild_id    INTEGER PRIMARY KEY,
            disabled_by INTEGER NOT NULL,
            expires_at  DATETIME NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS active_announcements (
            announcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id       INTEGER NOT NULL,
            channel_id      INTEGER NOT NULL,
            timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (member_id, channel_id)
        )""",
    ]
    for sql in tables:
        conn.execute(sql)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def mock_bot(in_memory_db):
    """Minimal bot-like namespace with CONN and master_user."""
    bot = types.SimpleNamespace()
    bot.CONN = in_memory_db
    bot.master_user = 999999999999999999  # Arbitrary bot owner ID
    return bot


def _make_mock_ctx(guild_id: int, author_id: int, guild_owner_id: int = 111111111111111111):
    """Create a minimal mock ApplicationContext-like object."""
    guild = types.SimpleNamespace()
    guild.id = guild_id
    guild.owner_id = guild_owner_id

    author = types.SimpleNamespace()
    author.id = author_id

    ctx = types.SimpleNamespace()
    ctx.guild = guild
    ctx.author = author
    return ctx


@pytest.fixture
def make_ctx():
    """Factory fixture for creating mock contexts."""
    return _make_mock_ctx
