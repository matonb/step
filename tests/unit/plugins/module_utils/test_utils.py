# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for duration parsing and secret file handling."""

import json
import os
import pathlib
import shutil
import stat

import pytest

from ansible_collections.matonb.step.plugins.module_utils.utils import (
    generate_secure_password,
    parse_duration,
    save_json_file,
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


# The exceptions atomic_move really raises. A bind-mounted ca.json - which is
# how this collection's own integration suite runs - gives EBUSY on rename, and
# ansible-core turns that into a bare Exception.
MOVE_FAILURES = [
    OSError("no space left on device"),
    Exception("Unable to make temporary file into ca.json, failed final rename"),
]


class FakeModule:
    """Stands in for AnsibleModule's atomic_move, which is all this needs."""

    def __init__(self, raises=None):
        """Optionally make the move fail with the given exception instance.

        The real atomic_move does not raise OSError: current ansible-core
        raises a bare Exception, and older cores call fail_json, which is a
        SystemExit. Modelling only OSError here is exactly what let a handler
        that caught only OSError look correct.
        """
        self.raises = raises
        self.moves = []

    def atomic_move(self, src, dest):
        self.moves.append((src, dest))
        if self.raises is not None:
            raise self.raises
        shutil.move(src, dest)


class TestSaveJsonFile:
    """The write must not be able to destroy what it is replacing.

    Writing in place truncates first, so an interruption leaves a ca.json
    step-ca cannot load and there is nothing to restore from.
    """

    def test_the_data_round_trips(self, tmp_path):
        target = tmp_path / "ca.json"
        assert save_json_file(FakeModule(), str(target), {"authority": {"claims": {}}}) is None
        assert json.loads(target.read_text(encoding="utf-8")) == {"authority": {"claims": {}}}

    def test_an_existing_file_is_replaced(self, tmp_path):
        target = tmp_path / "ca.json"
        target.write_text('{"old": true}', encoding="utf-8")
        save_json_file(FakeModule(), str(target), {"new": True})
        assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}

    @pytest.mark.parametrize("failure", MOVE_FAILURES, ids=["oserror", "bare-exception"])
    def test_a_failed_move_leaves_the_original_untouched(self, tmp_path, failure):
        # The whole point: the previous implementation had already truncated
        # the file by the time anything could go wrong.
        target = tmp_path / "ca.json"
        target.write_text('{"precious": true}', encoding="utf-8")

        error = save_json_file(FakeModule(raises=failure), str(target), {"new": True})

        assert "Failed to write JSON file" in error
        assert json.loads(target.read_text(encoding="utf-8")) == {"precious": True}

    @pytest.mark.parametrize("failure", MOVE_FAILURES, ids=["oserror", "bare-exception"])
    def test_a_failed_move_leaves_no_temporary_file_behind(self, tmp_path, failure):
        target = tmp_path / "ca.json"
        target.write_text("{}", encoding="utf-8")
        save_json_file(FakeModule(raises=failure), str(target), {"new": True})
        assert [path.name for path in tmp_path.iterdir()] == ["ca.json"]

    def test_a_fail_json_inside_the_move_still_cleans_up(self, tmp_path):
        # Older cores call fail_json rather than raising, which is a SystemExit.
        # It must keep propagating - fail_json has already emitted the result -
        # but it must not leave a temporary file in the CA's config directory.
        target = tmp_path / "ca.json"
        target.write_text('{"precious": true}', encoding="utf-8")

        with pytest.raises(SystemExit):
            save_json_file(FakeModule(raises=SystemExit(1)), str(target), {"new": True})

        assert [path.name for path in tmp_path.iterdir()] == ["ca.json"]
        assert json.loads(target.read_text(encoding="utf-8")) == {"precious": True}

    def test_a_symlink_is_followed_not_replaced(self, tmp_path):
        # Replacing the link would leave whatever it pointed at holding stale
        # configuration while the CA carried on reading that file.
        real = tmp_path / "real-ca.json"
        real.write_text('{"old": true}', encoding="utf-8")
        link = tmp_path / "ca.json"
        link.symlink_to(real)

        assert save_json_file(FakeModule(), str(link), {"new": True}) is None

        assert link.is_symlink()
        assert json.loads(real.read_text(encoding="utf-8")) == {"new": True}

    def test_unserialisable_data_is_reported_not_raised(self, tmp_path):
        target = tmp_path / "ca.json"
        target.write_text('{"precious": true}', encoding="utf-8")

        error = save_json_file(FakeModule(), str(target), {"bad": object()})

        assert "Failed to write JSON file" in error
        assert json.loads(target.read_text(encoding="utf-8")) == {"precious": True}
        assert [path.name for path in tmp_path.iterdir()] == ["ca.json"]

    def test_the_temporary_file_shares_the_targets_directory(self, tmp_path):
        # A rename is only atomic within one filesystem, so the temporary file
        # cannot live in /tmp.
        module = FakeModule()
        target = tmp_path / "ca.json"
        save_json_file(module, str(target), {})
        source, destination = module.moves[0]
        assert pathlib.Path(source).parent == tmp_path
        assert destination == str(target)

    def test_an_unwritable_directory_is_reported(self, tmp_path):
        if os.geteuid() == 0:
            pytest.skip("root ignores directory permissions")
        unwritable = tmp_path / "readonly"
        unwritable.mkdir()
        unwritable.chmod(0o500)
        try:
            error = save_json_file(FakeModule(), str(unwritable / "ca.json"), {})
        finally:
            unwritable.chmod(0o700)
        assert "Failed to write JSON file" in error
