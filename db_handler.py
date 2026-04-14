import sqlite3
from sqlite3 import Error


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def create_connection(db_file: str):
    try:
        conn = sqlite3.connect(
            db_file,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except Error as e:
        print(f"[DB] Connection error: {e}")
        return None


def _exec(conn, sql: str, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    return cur


def startup_db():
    import os
    db_path = os.getenv("DATABASE_PATH", "database.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True) if os.path.dirname(db_path) else None
    conn = create_connection(db_path)
    if conn is None:
        return None

    tables = [
        # 2FA users
        """CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            secret    TEXT    NOT NULL,
            verified  INTEGER NOT NULL CHECK (verified IN (0, 1))
        )""",

        # Guild configuration
        """CREATE TABLE IF NOT EXISTS guilds (
            guild_id             INTEGER PRIMARY KEY,
            event_channel        INTEGER,
            announcement_channel INTEGER,
            log_channel          INTEGER,
            webhook_protection   INTEGER NOT NULL DEFAULT 1 CHECK (webhook_protection IN (0, 1)),
            verified_bots        INTEGER NOT NULL DEFAULT 0 CHECK (verified_bots IN (0, 1)),
            link_filter_enabled  INTEGER NOT NULL DEFAULT 0 CHECK (link_filter_enabled IN (0, 1)),
            panic_active         INTEGER NOT NULL DEFAULT 0 CHECK (panic_active IN (0, 1)),
            announce_timeout     INTEGER NOT NULL DEFAULT 300
        )""",

        # Announcers (trusted_members)
        """CREATE TABLE IF NOT EXISTS trusted_members (
            trusted_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id   INTEGER NOT NULL,
            member_id  INTEGER NOT NULL,
            UNIQUE (guild_id, member_id),
            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
        )""",

        # Announcement channels
        """CREATE TABLE IF NOT EXISTS channel_table (
            channel_id INTEGER PRIMARY KEY,
            guild_id   INTEGER NOT NULL,
            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
        )""",

        # Active announcement permission grants (kept for backward compat)
        """CREATE TABLE IF NOT EXISTS active_announcements (
            announcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id       INTEGER NOT NULL,
            channel_id      INTEGER NOT NULL,
            timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (member_id, channel_id),
            FOREIGN KEY (member_id) REFERENCES users(user_id) ON DELETE CASCADE
        )""",

        # Link whitelist (allowed domains / exact URLs)
        """CREATE TABLE IF NOT EXISTS link_whitelist (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            type     TEXT    NOT NULL CHECK (type IN ('domain', 'specific')),
            url      TEXT    NOT NULL,
            added_by INTEGER,
            UNIQUE (guild_id, type, url)
        )""",

        # Safe roles (allowed for /role and /bulk-role)
        """CREATE TABLE IF NOT EXISTS safe_roles (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            role_id  INTEGER NOT NULL,
            UNIQUE (guild_id, role_id)
        )""",

        # Backup codes — single-use recovery codes stored as SHA-256 hashes
        """CREATE TABLE IF NOT EXISTS backup_codes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            code_hash TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )""",

        # Link managers (can manage link whitelist, cannot toggle filter)
        """CREATE TABLE IF NOT EXISTS link_managers (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id  INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            UNIQUE (guild_id, member_id)
        )""",

        # Panic backups
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

        # Entities exempt from link filter (channels, roles, users, categories)
        """CREATE TABLE IF NOT EXISTS link_filter_whitelist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            entity_type TEXT    NOT NULL CHECK (entity_type IN ('channel', 'role', 'user', 'category')),
            entity_id   INTEGER NOT NULL,
            added_by    INTEGER,
            UNIQUE (guild_id, entity_type, entity_id)
        )""",

        # Temporary webhook protection bypass (30 min window)
        """CREATE TABLE IF NOT EXISTS webhook_temp_disable (
            guild_id    INTEGER PRIMARY KEY,
            disabled_by INTEGER NOT NULL,
            expires_at  DATETIME NOT NULL
        )""",
    ]

    for sql in tables:
        try:
            conn.execute(sql)
        except Error as e:
            print(f"[DB] Table creation error: {e}")

    # Migrations for existing databases
    _run_migrations(conn)

    conn.commit()
    return conn


def _run_migrations(conn):
    """Apply ALTER TABLE migrations for existing installs."""
    migrations = [
        # Add announce_timeout column to guilds if missing
        "ALTER TABLE guilds ADD COLUMN announce_timeout INTEGER NOT NULL DEFAULT 300",
        # Ensure webhook_protection defaults to 1 (we can't change defaults via ALTER, just document)
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists, skip

    # Correct stale announce_timeout value: the old default was 120s; bump to 300s
    # for any guild that still has the old default and hasn't manually changed it.
    try:
        conn.execute("UPDATE guilds SET announce_timeout = 300 WHERE announce_timeout = 120")
        conn.commit()
    except Exception:
        pass

    # Remove the erroneous FK on trusted_members.member_id → users.user_id.
    # Members must be addable before they have run /create-2fa.
    # SQLite can't DROP CONSTRAINT, so we recreate the table without it.
    try:
        conn.executescript("""
            PRAGMA foreign_keys=OFF;

            CREATE TABLE IF NOT EXISTS trusted_members_new (
                trusted_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER NOT NULL,
                member_id  INTEGER NOT NULL,
                UNIQUE (guild_id, member_id),
                FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
            );

            INSERT OR IGNORE INTO trusted_members_new (trusted_id, guild_id, member_id)
                SELECT trusted_id, guild_id, member_id FROM trusted_members;

            DROP TABLE trusted_members;

            ALTER TABLE trusted_members_new RENAME TO trusted_members;

            PRAGMA foreign_keys=ON;
        """)
        conn.commit()
    except Exception as e:
        print(f"[DB] Migration (trusted_members FK fix): {e}")


# ---------------------------------------------------------------------------
# Users (2FA)
# ---------------------------------------------------------------------------

def insert_user(conn, info):
    """info: (user_id, secret, verified)"""
    _exec(conn, "INSERT INTO users(user_id, secret, verified) VALUES (?,?,?)", info)


def check_user(conn, user_id: int) -> bool:
    cur = conn.execute("SELECT EXISTS(SELECT 1 FROM users WHERE user_id=?)", (user_id,))
    return bool(cur.fetchone()[0])


def check_verified(conn, user_id: int) -> int:
    cur = conn.execute("SELECT verified FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def get_secret(conn, user_id: int):
    cur = conn.execute("SELECT secret FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None


def verify(conn, user_id: int):
    _exec(conn, "UPDATE users SET verified=1 WHERE user_id=?", (user_id,))


def delete_user(conn, user_id: int):
    _exec(conn, "DELETE FROM users WHERE user_id=?", (user_id,))


# ---------------------------------------------------------------------------
# Guilds
# ---------------------------------------------------------------------------

def check_guild(conn, guild_id: int) -> bool:
    cur = conn.execute("SELECT EXISTS(SELECT 1 FROM guilds WHERE guild_id=?)", (guild_id,))
    return bool(cur.fetchone()[0])


def init_guild(conn, guild_id: int, log_channel: int, announcement_channel: int = None):
    """Initialize a guild with minimal required fields. Webhook protection ON by default."""
    _exec(conn,
        """INSERT INTO guilds(guild_id, log_channel, announcement_channel, webhook_protection)
           VALUES (?,?,?,1)""",
        (guild_id, log_channel, announcement_channel))
    if announcement_channel:
        try:
            _exec(conn, "INSERT INTO channel_table(channel_id, guild_id) VALUES (?,?)",
                  (announcement_channel, guild_id))
        except sqlite3.IntegrityError:
            pass


def insert_guild(conn, info):
    """Legacy insert: info=(guild_id, event_channel, announcement_channel, log_channel)."""
    _exec(conn,
        "INSERT INTO guilds(guild_id, event_channel, announcement_channel, log_channel, webhook_protection) VALUES (?,?,?,?,1)",
        info)


def delete_guild(conn, guild_id: int):
    _exec(conn, "DELETE FROM trusted_members WHERE guild_id=?", (guild_id,))
    _exec(conn, "DELETE FROM channel_table WHERE guild_id=?", (guild_id,))
    _exec(conn, "DELETE FROM link_whitelist WHERE guild_id=?", (guild_id,))
    _exec(conn, "DELETE FROM link_managers WHERE guild_id=?", (guild_id,))
    _exec(conn, "DELETE FROM safe_roles WHERE guild_id=?", (guild_id,))
    _exec(conn, "DELETE FROM link_filter_whitelist WHERE guild_id=?", (guild_id,))
    _exec(conn, "DELETE FROM webhook_temp_disable WHERE guild_id=?", (guild_id,))
    _exec(conn, "DELETE FROM guilds WHERE guild_id=?", (guild_id,))


def get_log_channel(conn, guild_id: int):
    cur = conn.execute("SELECT log_channel FROM guilds WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return row[0] if row else None


def set_log_channel(conn, guild_id: int, channel_id: int):
    _exec(conn, "UPDATE guilds SET log_channel=? WHERE guild_id=?", (channel_id, guild_id))


def get_event_channel(conn, guild_id: int):
    cur = conn.execute("SELECT event_channel FROM guilds WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return row[0] if row else None


def get_link_filter_enabled(conn, guild_id: int) -> bool:
    cur = conn.execute("SELECT link_filter_enabled FROM guilds WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return bool(row[0]) if row else False


def set_link_filter_enabled(conn, guild_id: int, enabled: bool):
    _exec(conn, "UPDATE guilds SET link_filter_enabled=? WHERE guild_id=?", (int(enabled), guild_id))


def toggle_link_filter(conn, guild_id: int) -> bool:
    """Toggle and return the new state."""
    current = get_link_filter_enabled(conn, guild_id)
    new_state = not current
    set_link_filter_enabled(conn, guild_id, new_state)
    return new_state


def get_panic_active(conn, guild_id: int) -> bool:
    cur = conn.execute("SELECT panic_active FROM guilds WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return bool(row[0]) if row else False


def set_panic_active(conn, guild_id: int, active: bool):
    _exec(conn, "UPDATE guilds SET panic_active=? WHERE guild_id=?", (int(active), guild_id))


def get_announce_timeout(conn, guild_id: int) -> int:
    cur = conn.execute("SELECT announce_timeout FROM guilds WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return row[0] if row else 300


def set_announce_timeout(conn, guild_id: int, seconds: int):
    _exec(conn, "UPDATE guilds SET announce_timeout=? WHERE guild_id=?", (seconds, guild_id))


# ---------------------------------------------------------------------------
# Webhook settings
# ---------------------------------------------------------------------------

def check_webhook(conn, guild_id: int) -> bool:
    cur = conn.execute("SELECT webhook_protection FROM guilds WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return bool(row[0]) if row else False


def check_verified_bots(conn, guild_id: int) -> bool:
    cur = conn.execute("SELECT verified_bots FROM guilds WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return bool(row[0]) if row else False


def set_webhook_parameters(conn, info):
    """info: (webhook_protection, verified_bots, guild_id)"""
    _exec(conn,
        "UPDATE guilds SET webhook_protection=?, verified_bots=? WHERE guild_id=?",
        info)


# ---------------------------------------------------------------------------
# Webhook temporary disable
# ---------------------------------------------------------------------------

def set_webhook_temp_disable(conn, guild_id: int, disabled_by: int, expires_iso: str):
    _exec(conn,
        """INSERT INTO webhook_temp_disable(guild_id, disabled_by, expires_at)
           VALUES (?,?,?)
           ON CONFLICT(guild_id) DO UPDATE SET disabled_by=excluded.disabled_by, expires_at=excluded.expires_at""",
        (guild_id, disabled_by, expires_iso))


def get_webhook_temp_disable(conn, guild_id: int):
    """Return the expires_at ISO string, or None if not temporarily disabled."""
    cur = conn.execute(
        "SELECT expires_at FROM webhook_temp_disable WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return row[0] if row else None


def clear_webhook_temp_disable(conn, guild_id: int):
    _exec(conn, "DELETE FROM webhook_temp_disable WHERE guild_id=?", (guild_id,))


# ---------------------------------------------------------------------------
# Trusted members (Announcers)
# ---------------------------------------------------------------------------

def authorise_member(conn, info):
    """info: (guild_id, member_id)"""
    _exec(conn, "INSERT INTO trusted_members(guild_id, member_id) VALUES (?,?)", info)


def deauthorise_member(conn, info):
    """info: (guild_id, member_id)"""
    _exec(conn, "DELETE FROM trusted_members WHERE guild_id=? AND member_id=?", info)


def check_authorised(conn, info) -> bool:
    """info: (guild_id, member_id)"""
    cur = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM trusted_members WHERE guild_id=? AND member_id=?)",
        info)
    return bool(cur.fetchone()[0])


def get_trusted_members(conn, guild_id: int) -> list:
    cur = conn.execute("SELECT member_id FROM trusted_members WHERE guild_id=?", (guild_id,))
    return [row[0] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Announcement channels
# ---------------------------------------------------------------------------

def insert_channel(conn, info):
    """info: (channel_id, guild_id)"""
    _exec(conn, "INSERT INTO channel_table(channel_id, guild_id) VALUES (?,?)", info)


def delete_channel(conn, channel_id: int):
    _exec(conn, "DELETE FROM channel_table WHERE channel_id=?", (channel_id,))


def get_channels(conn, guild_id: int) -> list:
    cur = conn.execute("SELECT channel_id FROM channel_table WHERE guild_id=?", (guild_id,))
    return [row[0] for row in cur.fetchall()]


def get_announcement_channel(conn, guild_id: int):
    cur = conn.execute("SELECT announcement_channel FROM guilds WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Active announcements (permission grant tracking)
# ---------------------------------------------------------------------------

def insert_active_announcement(conn, info):
    """info: (channel_id, member_id) — inserts or refreshes the session timestamp."""
    _exec(conn, "INSERT OR REPLACE INTO active_announcements(channel_id, member_id) VALUES (?,?)", info)


def delete_active_announcement(conn, info):
    """info: (channel_id, member_id)"""
    _exec(conn, "DELETE FROM active_announcements WHERE channel_id=? AND member_id=?", info)


def get_active_announcements_users(conn, channel_id: int) -> list:
    cur = conn.execute("SELECT member_id FROM active_announcements WHERE channel_id=?", (channel_id,))
    return [row[0] for row in cur.fetchall()]


def remove_inactive_announcements(conn):
    _exec(conn,
        "DELETE FROM active_announcements WHERE timestamp <= datetime('now', '-10 minutes')")


# ---------------------------------------------------------------------------
# Link whitelist
# ---------------------------------------------------------------------------

def add_link_whitelist(conn, guild_id: int, link_type: str, url: str, added_by: int) -> bool:
    try:
        _exec(conn,
            "INSERT INTO link_whitelist(guild_id, type, url, added_by) VALUES (?,?,?,?)",
            (guild_id, link_type, url, added_by))
        return True
    except sqlite3.IntegrityError:
        return False  # Already exists


def remove_link_whitelist(conn, guild_id: int, url: str) -> bool:
    cur = _exec(conn,
        "DELETE FROM link_whitelist WHERE guild_id=? AND url=?",
        (guild_id, url))
    return cur.rowcount > 0


def get_link_whitelist(conn, guild_id: int) -> list:
    cur = conn.execute(
        "SELECT type, url FROM link_whitelist WHERE guild_id=? ORDER BY type, url",
        (guild_id,))
    return cur.fetchall()


# ---------------------------------------------------------------------------
# Link filter entity whitelist (channels, roles, users, categories)
# ---------------------------------------------------------------------------

def add_filter_exempt(conn, guild_id: int, entity_type: str, entity_id: int, added_by: int) -> bool:
    """Exempt a channel/role/user/category from the link filter."""
    try:
        _exec(conn,
            "INSERT INTO link_filter_whitelist(guild_id, entity_type, entity_id, added_by) VALUES (?,?,?,?)",
            (guild_id, entity_type, entity_id, added_by))
        return True
    except sqlite3.IntegrityError:
        return False


def remove_filter_exempt(conn, guild_id: int, entity_type: str, entity_id: int) -> bool:
    cur = _exec(conn,
        "DELETE FROM link_filter_whitelist WHERE guild_id=? AND entity_type=? AND entity_id=?",
        (guild_id, entity_type, entity_id))
    return cur.rowcount > 0


def get_filter_exemptions(conn, guild_id: int) -> list:
    """Returns list of (entity_type, entity_id) tuples."""
    cur = conn.execute(
        "SELECT entity_type, entity_id FROM link_filter_whitelist WHERE guild_id=? ORDER BY entity_type",
        (guild_id,))
    return cur.fetchall()


def is_filter_exempt(conn, guild_id: int, entity_type: str, entity_id: int) -> bool:
    cur = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM link_filter_whitelist WHERE guild_id=? AND entity_type=? AND entity_id=?)",
        (guild_id, entity_type, entity_id))
    return bool(cur.fetchone()[0])


def is_filter_exempt_by_roles(conn, guild_id: int, role_ids: list) -> bool:
    """Check if ANY of the given role IDs are exempt — single efficient query."""
    if not role_ids:
        return False
    placeholders = ','.join('?' * len(role_ids))
    cur = conn.execute(
        f"SELECT EXISTS(SELECT 1 FROM link_filter_whitelist "
        f"WHERE guild_id=? AND entity_type='role' AND entity_id IN ({placeholders}))",
        (guild_id, *role_ids))
    return bool(cur.fetchone()[0])


# ---------------------------------------------------------------------------
# Safe roles
# ---------------------------------------------------------------------------

def add_safe_role(conn, guild_id: int, role_id: int) -> bool:
    try:
        _exec(conn, "INSERT INTO safe_roles(guild_id, role_id) VALUES (?,?)", (guild_id, role_id))
        return True
    except sqlite3.IntegrityError:
        return False


def remove_safe_role(conn, guild_id: int, role_id: int) -> bool:
    cur = _exec(conn, "DELETE FROM safe_roles WHERE guild_id=? AND role_id=?", (guild_id, role_id))
    return cur.rowcount > 0


def is_safe_role(conn, guild_id: int, role_id: int) -> bool:
    cur = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM safe_roles WHERE guild_id=? AND role_id=?)",
        (guild_id, role_id))
    return bool(cur.fetchone()[0])


def get_safe_roles(conn, guild_id: int) -> list:
    cur = conn.execute("SELECT role_id FROM safe_roles WHERE guild_id=?", (guild_id,))
    return [row[0] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Backup codes
# ---------------------------------------------------------------------------

def insert_backup_code(conn, user_id: int, code_hash: str):
    _exec(conn, "INSERT INTO backup_codes(user_id, code_hash) VALUES (?,?)", (user_id, code_hash))


def delete_backup_codes(conn, user_id: int):
    _exec(conn, "DELETE FROM backup_codes WHERE user_id=?", (user_id,))


def get_backup_code_id(conn, user_id: int, code_hash: str):
    """Return row ID if hash exists for user, else None."""
    cur = conn.execute(
        "SELECT id FROM backup_codes WHERE user_id=? AND code_hash=?",
        (user_id, code_hash))
    row = cur.fetchone()
    return row[0] if row else None


def delete_backup_code_by_id(conn, code_id: int):
    _exec(conn, "DELETE FROM backup_codes WHERE id=?", (code_id,))


def count_backup_codes(conn, user_id: int) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM backup_codes WHERE user_id=?", (user_id,))
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Link managers
# ---------------------------------------------------------------------------

def add_link_manager(conn, guild_id: int, member_id: int) -> bool:
    try:
        _exec(conn,
            "INSERT INTO link_managers(guild_id, member_id) VALUES (?,?)",
            (guild_id, member_id))
        return True
    except sqlite3.IntegrityError:
        return False


def remove_link_manager(conn, guild_id: int, member_id: int) -> bool:
    cur = _exec(conn,
        "DELETE FROM link_managers WHERE guild_id=? AND member_id=?",
        (guild_id, member_id))
    return cur.rowcount > 0


def is_link_manager(conn, guild_id: int, member_id: int) -> bool:
    cur = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM link_managers WHERE guild_id=? AND member_id=?)",
        (guild_id, member_id))
    return bool(cur.fetchone()[0])


def get_link_managers(conn, guild_id: int) -> list:
    cur = conn.execute("SELECT member_id FROM link_managers WHERE guild_id=?", (guild_id,))
    return [row[0] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Panic backups
# ---------------------------------------------------------------------------

def save_panic_role_backup(conn, guild_id: int, role_id: int, perms_value: int):
    _exec(conn,
        "INSERT INTO panic_role_backup(guild_id, role_id, perms_value) VALUES (?,?,?)",
        (guild_id, role_id, perms_value))


def save_panic_channel_backup(conn, guild_id: int, channel_id: int, allow_value: int, deny_value: int):
    _exec(conn,
        "INSERT INTO panic_channel_backup(guild_id, channel_id, allow_value, deny_value) VALUES (?,?,?,?)",
        (guild_id, channel_id, allow_value, deny_value))


def get_panic_role_backups(conn, guild_id: int) -> list:
    cur = conn.execute(
        "SELECT role_id, perms_value FROM panic_role_backup WHERE guild_id=?", (guild_id,))
    return cur.fetchall()


def get_panic_channel_backups(conn, guild_id: int) -> list:
    cur = conn.execute(
        "SELECT channel_id, allow_value, deny_value FROM panic_channel_backup WHERE guild_id=?",
        (guild_id,))
    return cur.fetchall()


def clear_panic_backups(conn, guild_id: int):
    _exec(conn, "DELETE FROM panic_role_backup WHERE guild_id=?", (guild_id,))
    _exec(conn, "DELETE FROM panic_channel_backup WHERE guild_id=?", (guild_id,))
