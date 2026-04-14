"""
Tests for permissions.py

Covers every check() level and every helper:
  - is_bot_owner, is_server_owner, is_2fa_ready
  - is_link_manager, is_announcer, is_registered, is_elevated
  - can_setup_2fa
  - check(): bot_owner / owner / owner_no_2fa / link_manager / announcer / any_registered
  - guild_required
"""

import pytest
import types
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db_handler
import permissions


# ---------------------------------------------------------------------------
# Shared IDs
# ---------------------------------------------------------------------------

BOT_OWNER_ID   = 999999999999999999   # same as mock_bot.master_user in conftest
GUILD_OWNER_ID = 111111111111111111
GUILD_ID       = 200000000000000001
MANAGER_ID     = 300000000000000001
ANNOUNCER_ID   = 400000000000000001
RANDOM_ID      = 500000000000000001


# ---------------------------------------------------------------------------
# Helpers to build bot/ctx fixtures
# ---------------------------------------------------------------------------

def _make_bot(in_memory_db):
    bot = types.SimpleNamespace()
    bot.CONN = in_memory_db
    bot.master_user = BOT_OWNER_ID
    return bot


def _make_ctx(author_id, guild_id=GUILD_ID, guild_owner_id=GUILD_OWNER_ID):
    guild = types.SimpleNamespace()
    guild.id = guild_id
    guild.owner_id = guild_owner_id

    author = types.SimpleNamespace()
    author.id = author_id

    ctx = types.SimpleNamespace()
    ctx.guild = guild
    ctx.author = author
    return ctx


def _setup_verified_user(conn, user_id):
    """Insert a user that has completed 2FA setup."""
    db_handler.insert_user(conn, (user_id, "DUMMY", 1))


def _setup_unverified_user(conn, user_id):
    """Insert a user with 2FA registered but not yet verified."""
    db_handler.insert_user(conn, (user_id, "DUMMY", 0))


# ---------------------------------------------------------------------------
# is_bot_owner
# ---------------------------------------------------------------------------

class TestIsBotOwner:
    def test_returns_true_for_master_user(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        assert permissions.is_bot_owner(bot, BOT_OWNER_ID) is True

    def test_returns_false_for_other_user(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        assert permissions.is_bot_owner(bot, RANDOM_ID) is False


# ---------------------------------------------------------------------------
# is_server_owner
# ---------------------------------------------------------------------------

class TestIsServerOwner:
    def test_returns_true_for_guild_owner(self, in_memory_db):
        ctx = _make_ctx(GUILD_OWNER_ID)
        assert permissions.is_server_owner(ctx) is True

    def test_returns_false_for_non_owner(self, in_memory_db):
        ctx = _make_ctx(RANDOM_ID)
        assert permissions.is_server_owner(ctx) is False


# ---------------------------------------------------------------------------
# is_2fa_ready
# ---------------------------------------------------------------------------

class TestIs2faReady:
    def test_verified_user_is_ready(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, BOT_OWNER_ID)
        assert permissions.is_2fa_ready(bot, BOT_OWNER_ID) is True

    def test_unverified_user_not_ready(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_unverified_user(in_memory_db, BOT_OWNER_ID)
        assert permissions.is_2fa_ready(bot, BOT_OWNER_ID) is False

    def test_nonexistent_user_not_ready(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        assert permissions.is_2fa_ready(bot, RANDOM_ID) is False


# ---------------------------------------------------------------------------
# is_link_manager / is_announcer / is_registered
# ---------------------------------------------------------------------------

class TestRoleChecks:
    def test_is_link_manager_true(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.add_link_manager(in_memory_db, GUILD_ID, MANAGER_ID)
        assert permissions.is_link_manager(bot, GUILD_ID, MANAGER_ID) is True

    def test_is_link_manager_false(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        assert permissions.is_link_manager(bot, GUILD_ID, RANDOM_ID) is False

    def test_is_announcer_true(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.authorise_member(in_memory_db, (GUILD_ID, ANNOUNCER_ID))
        assert permissions.is_announcer(bot, GUILD_ID, ANNOUNCER_ID) is True

    def test_is_announcer_false(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        assert permissions.is_announcer(bot, GUILD_ID, RANDOM_ID) is False

    def test_is_registered_as_manager(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.add_link_manager(in_memory_db, GUILD_ID, MANAGER_ID)
        assert permissions.is_registered(bot, GUILD_ID, MANAGER_ID) is True

    def test_is_registered_as_announcer(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.authorise_member(in_memory_db, (GUILD_ID, ANNOUNCER_ID))
        assert permissions.is_registered(bot, GUILD_ID, ANNOUNCER_ID) is True

    def test_is_registered_neither(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        assert permissions.is_registered(bot, GUILD_ID, RANDOM_ID) is False


# ---------------------------------------------------------------------------
# can_setup_2fa
# ---------------------------------------------------------------------------

class TestCanSetup2FA:
    def test_bot_owner_can_setup(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(BOT_OWNER_ID)
        assert permissions.can_setup_2fa(bot, ctx) is True

    def test_guild_owner_can_setup(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(GUILD_OWNER_ID)
        assert permissions.can_setup_2fa(bot, ctx) is True

    def test_registered_manager_can_setup(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.add_link_manager(in_memory_db, GUILD_ID, MANAGER_ID)
        ctx = _make_ctx(MANAGER_ID)
        assert permissions.can_setup_2fa(bot, ctx) is True

    def test_registered_announcer_can_setup(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.authorise_member(in_memory_db, (GUILD_ID, ANNOUNCER_ID))
        ctx = _make_ctx(ANNOUNCER_ID)
        assert permissions.can_setup_2fa(bot, ctx) is True

    def test_random_user_cannot_setup(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(RANDOM_ID)
        assert permissions.can_setup_2fa(bot, ctx) is False


# ---------------------------------------------------------------------------
# check() — bot_owner level
# ---------------------------------------------------------------------------

class TestCheckBotOwner:
    def test_bot_owner_with_2fa_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, BOT_OWNER_ID)
        ctx = _make_ctx(BOT_OWNER_ID)
        ok, msg = permissions.check(bot, ctx, 'bot_owner')
        assert ok is True
        assert msg == ""

    def test_bot_owner_without_2fa_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(BOT_OWNER_ID)
        ok, msg = permissions.check(bot, ctx, 'bot_owner')
        assert ok is False
        assert "create-2fa" in msg or "verify" in msg.lower() or "Complete" in msg

    def test_server_owner_denied_at_bot_owner_level(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, GUILD_OWNER_ID)
        ctx = _make_ctx(GUILD_OWNER_ID)
        ok, msg = permissions.check(bot, ctx, 'bot_owner')
        assert ok is False

    def test_link_manager_denied_at_bot_owner_level(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.add_link_manager(in_memory_db, GUILD_ID, MANAGER_ID)
        _setup_verified_user(in_memory_db, MANAGER_ID)
        ctx = _make_ctx(MANAGER_ID)
        ok, _ = permissions.check(bot, ctx, 'bot_owner')
        assert ok is False


# ---------------------------------------------------------------------------
# check() — owner level
# ---------------------------------------------------------------------------

class TestCheckOwner:
    def test_bot_owner_with_2fa_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, BOT_OWNER_ID)
        ctx = _make_ctx(BOT_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'owner')
        assert ok is True

    def test_server_owner_with_2fa_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, GUILD_OWNER_ID)
        ctx = _make_ctx(GUILD_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'owner')
        assert ok is True

    def test_server_owner_without_2fa_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(GUILD_OWNER_ID)
        ok, msg = permissions.check(bot, ctx, 'owner')
        assert ok is False

    def test_random_user_denied_at_owner_level(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, RANDOM_ID)
        ctx = _make_ctx(RANDOM_ID)
        ok, _ = permissions.check(bot, ctx, 'owner')
        assert ok is False


# ---------------------------------------------------------------------------
# check() — owner_no_2fa level
# ---------------------------------------------------------------------------

class TestCheckOwnerNo2FA:
    def test_bot_owner_without_2fa_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(BOT_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'owner_no_2fa')
        assert ok is True

    def test_server_owner_without_2fa_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(GUILD_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'owner_no_2fa')
        assert ok is True

    def test_link_manager_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.add_link_manager(in_memory_db, GUILD_ID, MANAGER_ID)
        ctx = _make_ctx(MANAGER_ID)
        ok, _ = permissions.check(bot, ctx, 'owner_no_2fa')
        assert ok is False

    def test_random_user_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(RANDOM_ID)
        ok, _ = permissions.check(bot, ctx, 'owner_no_2fa')
        assert ok is False


# ---------------------------------------------------------------------------
# check() — link_manager level
# ---------------------------------------------------------------------------

class TestCheckLinkManager:
    def test_link_manager_with_2fa_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.add_link_manager(in_memory_db, GUILD_ID, MANAGER_ID)
        _setup_verified_user(in_memory_db, MANAGER_ID)
        ctx = _make_ctx(MANAGER_ID)
        ok, _ = permissions.check(bot, ctx, 'link_manager')
        assert ok is True

    def test_link_manager_without_2fa_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.add_link_manager(in_memory_db, GUILD_ID, MANAGER_ID)
        ctx = _make_ctx(MANAGER_ID)
        ok, _ = permissions.check(bot, ctx, 'link_manager')
        assert ok is False

    def test_bot_owner_with_2fa_allowed(self, in_memory_db):
        """Elevated users bypass the role check but still need 2FA."""
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, BOT_OWNER_ID)
        ctx = _make_ctx(BOT_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'link_manager')
        assert ok is True

    def test_server_owner_with_2fa_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, GUILD_OWNER_ID)
        ctx = _make_ctx(GUILD_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'link_manager')
        assert ok is True

    def test_bot_owner_without_2fa_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(BOT_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'link_manager')
        assert ok is False

    def test_announcer_only_denied(self, in_memory_db):
        """Being an announcer alone is not enough for link_manager level."""
        bot = _make_bot(in_memory_db)
        db_handler.authorise_member(in_memory_db, (GUILD_ID, ANNOUNCER_ID))
        _setup_verified_user(in_memory_db, ANNOUNCER_ID)
        ctx = _make_ctx(ANNOUNCER_ID)
        ok, _ = permissions.check(bot, ctx, 'link_manager')
        assert ok is False

    def test_random_user_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, RANDOM_ID)
        ctx = _make_ctx(RANDOM_ID)
        ok, _ = permissions.check(bot, ctx, 'link_manager')
        assert ok is False


# ---------------------------------------------------------------------------
# check() — announcer level
# ---------------------------------------------------------------------------

class TestCheckAnnouncer:
    def test_announcer_with_2fa_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.authorise_member(in_memory_db, (GUILD_ID, ANNOUNCER_ID))
        _setup_verified_user(in_memory_db, ANNOUNCER_ID)
        ctx = _make_ctx(ANNOUNCER_ID)
        ok, _ = permissions.check(bot, ctx, 'announcer')
        assert ok is True

    def test_announcer_without_2fa_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.authorise_member(in_memory_db, (GUILD_ID, ANNOUNCER_ID))
        ctx = _make_ctx(ANNOUNCER_ID)
        ok, _ = permissions.check(bot, ctx, 'announcer')
        assert ok is False

    def test_bot_owner_with_2fa_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        _setup_verified_user(in_memory_db, BOT_OWNER_ID)
        ctx = _make_ctx(BOT_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'announcer')
        assert ok is True

    def test_link_manager_only_denied(self, in_memory_db):
        """Being a link manager alone is not enough for announcer level."""
        bot = _make_bot(in_memory_db)
        db_handler.add_link_manager(in_memory_db, GUILD_ID, MANAGER_ID)
        _setup_verified_user(in_memory_db, MANAGER_ID)
        ctx = _make_ctx(MANAGER_ID)
        ok, _ = permissions.check(bot, ctx, 'announcer')
        assert ok is False

    def test_random_user_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(RANDOM_ID)
        ok, _ = permissions.check(bot, ctx, 'announcer')
        assert ok is False


# ---------------------------------------------------------------------------
# check() — any_registered level
# ---------------------------------------------------------------------------

class TestCheckAnyRegistered:
    def test_link_manager_allowed_no_2fa_needed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.add_link_manager(in_memory_db, GUILD_ID, MANAGER_ID)
        ctx = _make_ctx(MANAGER_ID)
        ok, _ = permissions.check(bot, ctx, 'any_registered')
        assert ok is True

    def test_announcer_allowed_no_2fa_needed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.authorise_member(in_memory_db, (GUILD_ID, ANNOUNCER_ID))
        ctx = _make_ctx(ANNOUNCER_ID)
        ok, _ = permissions.check(bot, ctx, 'any_registered')
        assert ok is True

    def test_bot_owner_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(BOT_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'any_registered')
        assert ok is True

    def test_server_owner_allowed(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(GUILD_OWNER_ID)
        ok, _ = permissions.check(bot, ctx, 'any_registered')
        assert ok is True

    def test_random_user_denied(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(RANDOM_ID)
        ok, _ = permissions.check(bot, ctx, 'any_registered')
        assert ok is False


# ---------------------------------------------------------------------------
# guild_required
# ---------------------------------------------------------------------------

class TestGuildRequired:
    def test_initialized_guild_passes(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        db_handler.init_guild(in_memory_db, GUILD_ID, log_channel=12345)
        ctx = _make_ctx(BOT_OWNER_ID)
        ok, _ = permissions.guild_required(bot, ctx)
        assert ok is True

    def test_uninitialized_guild_fails(self, in_memory_db):
        bot = _make_bot(in_memory_db)
        ctx = _make_ctx(BOT_OWNER_ID, guild_id=999)
        ok, msg = permissions.guild_required(bot, ctx)
        assert ok is False
        assert "setup" in msg.lower() or "set up" in msg.lower()
