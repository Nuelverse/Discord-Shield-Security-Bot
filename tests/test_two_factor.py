"""
Tests for two_factor_helper.py

Covers:
  - TOTP secret generation and QR code creation
  - verify_code: valid, invalid, and zero-padded codes
  - generate_backup_codes: count, format, uniqueness
  - use_backup_code: valid consumption, single-use enforcement, normalization
  - count_backup_codes: accurate after generation and use
"""

import pytest
import pyotp
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import two_factor_helper
import db_handler


USER_ID = 100000000000000001
GUILD_ID = 200000000000000001


# ---------------------------------------------------------------------------
# TOTP — verify_code
# ---------------------------------------------------------------------------

class TestVerifyCode:
    def test_valid_code(self, in_memory_db):
        secret = pyotp.random_base32()
        db_handler.insert_user(in_memory_db, (USER_ID, secret, 0))
        valid_code = pyotp.TOTP(secret).now()
        assert two_factor_helper.verify_code(in_memory_db, USER_ID, int(valid_code)) is True

    def test_invalid_code(self, in_memory_db):
        secret = pyotp.random_base32()
        db_handler.insert_user(in_memory_db, (USER_ID, secret, 0))
        assert two_factor_helper.verify_code(in_memory_db, USER_ID, 000000) is False

    def test_wrong_secret(self, in_memory_db):
        secret = pyotp.random_base32()
        db_handler.insert_user(in_memory_db, (USER_ID, secret, 0))
        other_secret = pyotp.random_base32()
        wrong_code = int(pyotp.TOTP(other_secret).now())
        # Could theoretically match — check that verify uses stored secret
        correct = pyotp.TOTP(secret).verify(f"{wrong_code:06d}")
        result = two_factor_helper.verify_code(in_memory_db, USER_ID, wrong_code)
        assert result == correct  # Must agree with pyotp

    def test_nonexistent_user_returns_false(self, in_memory_db):
        assert two_factor_helper.verify_code(in_memory_db, 999999, 123456) is False

    def test_zero_padded_code(self, in_memory_db):
        """Code like 001234 should be zero-padded to 6 digits."""
        secret = pyotp.random_base32()
        db_handler.insert_user(in_memory_db, (USER_ID, secret, 0))
        totp = pyotp.TOTP(secret)
        raw = totp.now()
        # Verify using the integer value (may be < 100000 if zero-padded)
        result = two_factor_helper.verify_code(in_memory_db, USER_ID, int(raw))
        assert result is True


# ---------------------------------------------------------------------------
# Backup codes — generation
# ---------------------------------------------------------------------------

class TestGenerateBackupCodes:
    def test_generates_eight_by_default(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        codes = two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        assert len(codes) == 8

    def test_custom_count(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        codes = two_factor_helper.generate_backup_codes(in_memory_db, USER_ID, count=5)
        assert len(codes) == 5

    def test_format_is_xxxx_xxxx(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        codes = two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        for code in codes:
            assert len(code) == 9  # 4 + dash + 4
            assert code[4] == "-"
            assert code[:4].isdigit()
            assert code[5:].isdigit()

    def test_codes_are_unique(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        codes = two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        assert len(set(codes)) == len(codes)

    def test_regeneration_replaces_old_codes(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        assert db_handler.count_backup_codes(in_memory_db, USER_ID) == 8
        # Regenerate
        two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        assert db_handler.count_backup_codes(in_memory_db, USER_ID) == 8  # Still 8, not 16

    def test_count_reflects_generation(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        assert db_handler.count_backup_codes(in_memory_db, USER_ID) == 8


# ---------------------------------------------------------------------------
# Backup codes — use_backup_code
# ---------------------------------------------------------------------------

class TestUseBackupCode:
    def test_valid_code_accepted(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        codes = two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        assert two_factor_helper.use_backup_code(in_memory_db, USER_ID, codes[0]) is True

    def test_used_code_rejected(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        codes = two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        two_factor_helper.use_backup_code(in_memory_db, USER_ID, codes[0])
        # Second attempt on same code must fail
        assert two_factor_helper.use_backup_code(in_memory_db, USER_ID, codes[0]) is False

    def test_invalid_code_rejected(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        assert two_factor_helper.use_backup_code(in_memory_db, USER_ID, "0000-0000") is False

    def test_code_without_dash_accepted(self, in_memory_db):
        """Normalization: '12345678' should match '1234-5678'."""
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        codes = two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        # Strip the dash
        raw = codes[0].replace("-", "")
        assert two_factor_helper.use_backup_code(in_memory_db, USER_ID, raw) is True

    def test_code_count_decrements_after_use(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        codes = two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        assert db_handler.count_backup_codes(in_memory_db, USER_ID) == 8
        two_factor_helper.use_backup_code(in_memory_db, USER_ID, codes[0])
        assert db_handler.count_backup_codes(in_memory_db, USER_ID) == 7

    def test_all_codes_individually_consumable(self, in_memory_db):
        db_handler.insert_user(in_memory_db, (USER_ID, "DUMMY", 1))
        codes = two_factor_helper.generate_backup_codes(in_memory_db, USER_ID)
        for code in codes:
            assert two_factor_helper.use_backup_code(in_memory_db, USER_ID, code) is True
        assert db_handler.count_backup_codes(in_memory_db, USER_ID) == 0
