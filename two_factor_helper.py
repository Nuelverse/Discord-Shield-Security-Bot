import hashlib
import secrets
import string
import pyotp
import pyqrcode
import discord
import db_handler


# ---------------------------------------------------------------------------
# TOTP
# ---------------------------------------------------------------------------

def setup_and_get_path(ctx, connection):
    """
    Generate a TOTP secret for the user, create a QR code PNG, insert into DB.
    Returns (png_path, secret).
    """
    secret = pyotp.random_base32()
    file_token = pyotp.random_base32()
    user_id = int(ctx.user.id)
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name="Security Bot",
        issuer_name="SecurityBot"
    )
    qr = pyqrcode.create(uri, error='L')
    png_path = f'./data/QR-{file_token}.png'
    qr.png(png_path, scale=6)
    db_handler.insert_user(conn=connection, info=(user_id, secret, 0))
    return png_path, secret


def verify_code(connection, user_id: int, code) -> bool:
    """
    Verify a 6-digit TOTP code. Accepts int or str, zero-pads to 6 digits.
    Does NOT check backup codes — use use_backup_code() for that separately.
    """
    code_str = "{0:06d}".format(int(code))
    secret = db_handler.get_secret(conn=connection, user_id=user_id)
    if secret is None:
        return False
    return pyotp.TOTP(secret).verify(code_str)


def get_log_channel(bot, guild: discord.Guild):
    """Return the log channel object for a guild, or None."""
    log_id = db_handler.get_log_channel(bot.CONN, guild.id)
    return bot.get_channel(log_id) if log_id else None


# ---------------------------------------------------------------------------
# Backup codes
# ---------------------------------------------------------------------------

_ALPHABET = string.digits + string.ascii_uppercase


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def generate_backup_codes(connection, user_id: int, count: int = 8) -> list[str]:
    """
    Generate `count` single-use backup codes, store their hashes, and return
    the plaintext codes formatted as XXXX-XXXX.
    Any existing backup codes for this user are replaced.
    """
    db_handler.delete_backup_codes(connection, user_id)
    codes = []
    for _ in range(count):
        raw = ''.join(secrets.choice(string.digits) for _ in range(8))
        formatted = f"{raw[:4]}-{raw[4:]}"
        db_handler.insert_backup_code(connection, user_id, _hash_code(raw))
        codes.append(formatted)
    return codes


def use_backup_code(connection, user_id: int, raw_code: str) -> bool:
    """
    Try to consume a backup code (plaintext, with or without dash).
    Returns True and deletes the code if valid. Returns False otherwise.
    """
    normalized = raw_code.replace("-", "").replace(" ", "").strip()
    code_hash = _hash_code(normalized)
    code_id = db_handler.get_backup_code_id(connection, user_id, code_hash)
    if code_id is None:
        return False
    db_handler.delete_backup_code_by_id(connection, code_id)
    return True
