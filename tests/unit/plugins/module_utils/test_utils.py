# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for duration parsing and secret file handling."""

import os
import pathlib
import stat

import pytest

from ansible_collections.matonb.step.plugins.module_utils.utils import (
    generate_secure_password,
    parse_duration,
    write_secret_file,
)

# Left is what a task requests; right is what step actually stored when given
# that value. Captured by round-tripping each through
# `step ca provisioner add --x509-default-dur` and reading back ca.json, rather
# than being derived from the same arithmetic under test.
EQUIVALENT_DURATIONS = [
    ("1.1h", "1h6m0s"),
    ("1.5h", "1h30m0s"),
    ("0.5s", "500ms"),
    ("0.25h", "15m0s"),
    ("2.675s", "2.675s"),
    ("90m", "1h30m0s"),
    ("36h", "36h0m0s"),
    ("5m", "5m0s"),
    ("2h45m", "2h45m0s"),
]


class TestParseDuration:
    @pytest.mark.parametrize(("requested", "stored"), EQUIVALENT_DURATIONS)
    def test_spellings_of_one_duration_compare_equal(self, requested, stored):
        # Durations are compared for equality to detect drift. Accumulating in
        # float makes 1.1h and 1h6m0s differ, which reported drift on every run
        # and re-ran `update` forever.
        assert parse_duration(requested) == parse_duration(stored)

    def test_result_is_an_exact_integer_of_nanoseconds(self):
        assert parse_duration("1.1h") == 3_960_000_000_000
        assert isinstance(parse_duration("1.1h"), int)

    @pytest.mark.parametrize(
        ("value", "nanoseconds"),
        [
            ("0", 0),
            ("1ns", 1),
            ("1us", 1_000),
            ("1ms", 1_000_000),
            ("1s", 1_000_000_000),
            ("1m", 60_000_000_000),
            ("1h", 3_600_000_000_000),
        ],
    )
    def test_unit_suffixes(self, value, nanoseconds):
        assert parse_duration(value) == nanoseconds

    def test_compound_values_sum(self):
        assert parse_duration("2h45m30s") == parse_duration("2h") + parse_duration("45m") + parse_duration("30s")

    def test_sign_is_honoured(self):
        assert parse_duration("-5m") == -parse_duration("5m")
        assert parse_duration("+5m") == parse_duration("5m")

    def test_fraction_truncates_toward_zero_like_go(self):
        # 0.1ns is below the resolution Go keeps.
        assert parse_duration("0.0000000001s") == 0

    @pytest.mark.parametrize("value", ["", "   ", "-", "+", "36hours", "abc", "5m junk", "5", "m", "5x"])
    def test_invalid_values_are_rejected(self, value):
        with pytest.raises(ValueError, match=r"[Dd]uration"):
            parse_duration(value)


class TestWriteSecretFile:
    def test_content_is_written_verbatim(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
        path = write_secret_file("s3cret")
        try:
            assert pathlib.Path(path).read_text(encoding="utf-8") == "s3cret"
        finally:
            os.remove(path)

    def test_file_is_private(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
        path = write_secret_file("s3cret")
        try:
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        finally:
            os.remove(path)

    def test_unknown_owner_raises_and_leaves_nothing_behind(self, tmp_path, monkeypatch):
        # The previous implementation fell back to a world-readable file here.
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
        with pytest.raises(RuntimeError, match="no-such-user"):
            write_secret_file("s3cret", owner="no-such-user")
        assert list(tmp_path.iterdir()) == []


class TestGenerateSecurePassword:
    def test_length_is_honoured(self):
        assert len(generate_secure_password(32)) == 32

    def test_passwords_differ(self):
        assert generate_secure_password() != generate_secure_password()

    def test_character_classes_are_represented(self):
        password = generate_secure_password(64)
        assert any(c.isupper() for c in password)
        assert any(c.islower() for c in password)
        assert any(c.isdigit() for c in password)
        assert any(not c.isalnum() for c in password)
