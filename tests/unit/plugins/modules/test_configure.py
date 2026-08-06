# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for the configure module's update logic.

The module previously reported C(changed) unconditionally, so a play using the
documented C(notify: restart step-ca) pattern restarted the CA on every run.
These tests pin the comparison that stopped that.
"""

import json
import os
import pathlib
import stat
import subprocess
import sys

import pytest

from ansible_collections.matonb.step.plugins.modules import configure
from ansible_collections.matonb.step.plugins.modules.configure import (
    CLAIM_KEYS,
    TOP_LEVEL_KEYS,
    apply_updates,
    get_argument_spec,
)

# Options controlling how the file is located and written, rather than what
# goes into it. Everything else must end up somewhere in the configuration.
BEHAVIOUR_OPTIONS = {"backup", "create", "json_path"}

# Sourced from the real spec so an option that stops being written shows up
# here, rather than only in the constants the module happens to still list.
NOTHING_REQUESTED = dict.fromkeys(set(get_argument_spec()) - BEHAVIOUR_OPTIONS)


def params(**requested):
    """Build module parameters with only the named options set."""
    unknown = set(requested) - set(NOTHING_REQUESTED)
    if unknown:
        raise AssertionError(f"not module options: {sorted(unknown)}")
    return {**NOTHING_REQUESTED, **requested}


class TestOptionCoverage:
    def test_every_option_is_written_somewhere(self):
        # Without this, deleting an entry from TOP_LEVEL_KEYS makes the module
        # silently stop writing that option while every other test still
        # passes: they all derive their parameters from those same constants.
        assert set(get_argument_spec()) - BEHAVIOUR_OPTIONS == set(TOP_LEVEL_KEYS) | set(CLAIM_KEYS)

    def test_the_claim_names_are_the_ones_step_reads(self):
        # Asserted as literals, because everything else in this file takes the
        # names from CLAIM_KEYS itself: a typo there would write a claim
        # step-ca silently ignores, and no other test would notice.
        assert CLAIM_KEYS == {
            "default_tls_cert_duration": "defaultTLSCertDuration",
            "max_tls_cert_duration": "maxTLSCertDuration",
            "min_tls_cert_duration": "minTLSCertDuration",
        }


class TestChangeDetection:
    """apply_updates returns something equal to its input when nothing differs.

    main() reports changed on exactly that comparison, so these are the tests
    that keep the CA from being restarted on every play.
    """

    def test_requesting_nothing_changes_nothing(self):
        config = {"root": "/etc/step-ca/certs/root_ca.crt", "authority": {"claims": {"maxTLSCertDuration": "8760h"}}}
        assert apply_updates(config, params()) == config

    def test_requesting_what_is_already_set_changes_nothing(self):
        config = {"root": "/root.crt", "authority": {"claims": {"maxTLSCertDuration": "8760h"}}}
        updated = apply_updates(config, params(root="/root.crt", max_tls_cert_duration="8760h"))
        assert updated == config

    def test_a_differing_top_level_value_changes_the_result(self):
        config = {"root": "/old.crt"}
        assert apply_updates(config, params(root="/new.crt")) != config

    def test_a_differing_claim_changes_the_result(self):
        config = {"authority": {"claims": {"maxTLSCertDuration": "8760h"}}}
        assert apply_updates(config, params(max_tls_cert_duration="17520h")) != config

    @pytest.mark.parametrize(
        ("stored", "requested"),
        [
            ("8760h0m0s", "8760h"),
            ("5m0s", "5m"),
            ("1h30m0s", "90m"),
            ("1h6m0s", "1.1h"),
            ("8760h", "8760h"),
        ],
        ids=["hours", "minutes", "mixed-units", "fractional", "identical"],
    )
    def test_a_renormalized_duration_is_not_a_change(self, stored, requested):
        # step rewrites ca.json's claims in its own spelling: a value set here
        # as 8760h comes back as 8760h0m0s. Comparing the text would report a
        # change on every run and restart the CA each time, forever.
        config = {"authority": {"claims": {"maxTLSCertDuration": stored}}}
        assert apply_updates(config, params(max_tls_cert_duration=requested)) == config

    def test_a_genuinely_different_duration_is_still_a_change(self):
        config = {"authority": {"claims": {"maxTLSCertDuration": "8760h0m0s"}}}
        assert apply_updates(config, params(max_tls_cert_duration="8761h")) != config

    def test_an_unparseable_stored_duration_is_corrected(self):
        # Whatever put "forever" there, it is not a duration step can read.
        config = {"authority": {"claims": {"maxTLSCertDuration": "forever"}}}
        updated = apply_updates(config, params(max_tls_cert_duration="8760h"))
        assert updated["authority"]["claims"]["maxTLSCertDuration"] == "8760h"

    def test_an_unparseable_requested_duration_names_the_option(self):
        with pytest.raises(ValueError, match="max_tls_cert_duration"):
            apply_updates({}, params(max_tls_cert_duration="forever"))


class TestUpdates:
    def test_the_input_is_never_mutated(self):
        # main() compares against the original, so mutating it would make every
        # run report no change - the opposite failure, and a silent one.
        config = {"root": "/old.crt", "authority": {"claims": {"maxTLSCertDuration": "1h"}}}
        apply_updates(config, params(root="/new.crt", max_tls_cert_duration="2h"))
        assert config == {"root": "/old.crt", "authority": {"claims": {"maxTLSCertDuration": "1h"}}}

    @pytest.mark.parametrize("key", TOP_LEVEL_KEYS)
    def test_every_top_level_option_is_written_at_the_top_level(self, key):
        assert apply_updates({}, params(**{key: "value"})) == {key: "value"}

    @pytest.mark.parametrize(("key", "claim"), sorted(CLAIM_KEYS.items()))
    def test_every_duration_option_is_written_under_authority_claims(self, key, claim):
        assert apply_updates({}, params(**{key: "5m"})) == {"authority": {"claims": {claim: "5m"}}}

    def test_unmanaged_settings_are_preserved(self):
        # ca.json holds far more than this module knows about; anything it does
        # not manage must survive untouched.
        config = {
            "address": ":443",
            "authority": {"claims": {"minTLSCertDuration": "5m"}, "provisioners": [{"name": "acme"}]},
            "dnsNames": ["ca.example.com"],
        }
        updated = apply_updates(config, params(max_tls_cert_duration="8760h"))
        assert updated["address"] == ":443"
        assert updated["dnsNames"] == ["ca.example.com"]
        assert updated["authority"]["provisioners"] == [{"name": "acme"}]
        assert updated["authority"]["claims"]["minTLSCertDuration"] == "5m"

    def test_claims_are_created_when_the_file_has_no_authority_block(self):
        assert apply_updates({}, params(min_tls_cert_duration="5m")) == {
            "authority": {"claims": {"minTLSCertDuration": "5m"}}
        }

    def test_an_existing_authority_block_is_not_replaced(self):
        config = {"authority": {"enableAdmin": True}}
        updated = apply_updates(config, params(min_tls_cert_duration="5m"))
        assert updated["authority"]["enableAdmin"] is True
        assert updated["authority"]["claims"] == {"minTLSCertDuration": "5m"}


def run_module(json_path, **requested):
    """Execute the module the way Ansible does and return its result.

    Driving main() rather than apply_updates is what pins the reported
    `changed` value: the original defect was in main() alone, and every
    apply_updates test would have passed with it still in place.

    The child inherits the environment but not this process's sys.path, which
    is where conftest made `ansible_collections.matonb.step` importable, so it
    is handed over rather than recomputed. Only the entries that actually carry
    collections are passed: exporting the whole path would also export pytest's
    insertion of this test's own directory, letting it shadow stdlib imports in
    the child. `ansible` itself comes from the interpreter's own site-packages.
    """
    args = json.dumps({"ANSIBLE_MODULE_ARGS": {"json_path": str(json_path), **requested}})
    collection_paths = [path for path in sys.path if path and os.path.isdir(os.path.join(path, "ansible_collections"))]
    completed = subprocess.run(
        [sys.executable, configure.__file__],
        input=args,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(collection_paths)},
    )
    if not completed.stdout:
        # Without this the failure surfaces as a JSONDecodeError and the real
        # traceback, which is on stderr, is thrown away.
        raise AssertionError(f"module produced no result (exit {completed.returncode}):\n{completed.stderr}")
    return json.loads(completed.stdout)


def existing_config(tmp_path, claims=None, **contents):
    """Write a ca.json directly and return its path.

    Written rather than produced by running the module, so a write regression
    cannot corrupt the fixture and the assertion at the same time.
    """
    config = dict(contents)
    if claims:
        config["authority"] = {"claims": claims}
    config_file = tmp_path / "ca.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    return config_file


class TestReportedChangedState:
    """The module as Ansible actually invokes it.

    A play following the documented `notify: restart step-ca` pattern restarts
    the CA whenever this reports changed, so an unconditional true meant a CA
    restart on every single run.
    """

    def test_first_run_changes_the_file_and_the_second_does_not(self, tmp_path):
        config_file = tmp_path / "ca.json"
        config_file.write_text(json.dumps({"address": ":443"}), encoding="utf-8")

        first = run_module(config_file, max_tls_cert_duration="8760h")
        second = run_module(config_file, max_tls_cert_duration="8760h")

        assert first["changed"] is True
        assert second["changed"] is False
        assert json.loads(config_file.read_text(encoding="utf-8")) == {
            "address": ":443",
            "authority": {"claims": {"maxTLSCertDuration": "8760h"}},
        }

    def test_a_no_op_run_leaves_the_file_byte_for_byte_alone(self, tmp_path):
        # Not just "changed is false" - the file must not be rewritten at all,
        # or anything watching its mtime sees churn.
        config_file = existing_config(tmp_path, claims={"maxTLSCertDuration": "8760h"})
        before = config_file.read_bytes()
        mtime = config_file.stat().st_mtime_ns

        assert run_module(config_file, max_tls_cert_duration="8760h")["changed"] is False
        assert config_file.read_bytes() == before
        assert config_file.stat().st_mtime_ns == mtime

    def test_a_changed_setting_is_reported_and_written(self, tmp_path):
        config_file = existing_config(tmp_path, claims={"maxTLSCertDuration": "8760h"})

        result = run_module(config_file, max_tls_cert_duration="17520h")

        assert result["changed"] is True
        assert result["new_data"]["authority"]["claims"]["maxTLSCertDuration"] == "17520h"

    def test_check_mode_predicts_without_writing(self, tmp_path):
        config_file = tmp_path / "ca.json"
        config_file.write_text(json.dumps({"address": ":443"}), encoding="utf-8")

        result = run_module(config_file, max_tls_cert_duration="8760h", _ansible_check_mode=True)

        assert result["changed"] is True
        assert json.loads(config_file.read_text(encoding="utf-8")) == {"address": ":443"}

    def test_check_mode_reports_no_change_when_already_correct(self, tmp_path):
        config_file = existing_config(tmp_path, claims={"maxTLSCertDuration": "8760h"})

        result = run_module(config_file, max_tls_cert_duration="8760h", _ansible_check_mode=True)

        assert result["changed"] is False

    def test_a_renormalized_file_is_left_alone_end_to_end(self, tmp_path):
        # The realistic case: this module wrote 8760h, then step rewrote ca.json
        # while adding a provisioner and normalized it to 8760h0m0s. Re-running
        # the same play must not report changed.
        config_file = tmp_path / "ca.json"
        config_file.write_text(
            json.dumps({"authority": {"claims": {"maxTLSCertDuration": "8760h0m0s"}}}),
            encoding="utf-8",
        )
        before = config_file.read_bytes()

        result = run_module(config_file, max_tls_cert_duration="8760h")

        assert result["changed"] is False
        assert config_file.read_bytes() == before

    def test_every_exit_carries_a_message(self, tmp_path):
        config_file = existing_config(tmp_path)
        changed = run_module(config_file, max_tls_cert_duration="8760h")
        unchanged = run_module(config_file, max_tls_cert_duration="8760h")
        predicted = run_module(config_file, max_tls_cert_duration="17520h", _ansible_check_mode=True)

        assert changed["msg"] == "JSON file updated"
        assert unchanged["msg"] == "Configuration already up to date"
        assert predicted["msg"] == "Configuration would be updated"


class TestFailures:
    def test_a_malformed_ca_json_fails_with_an_explanation(self, tmp_path):
        config_file = tmp_path / "ca.json"
        config_file.write_text("{ not json", encoding="utf-8")

        result = run_module(config_file, max_tls_cert_duration="8760h")

        assert result["failed"] is True
        assert "Failed to load JSON file" in result["msg"]

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
    def test_an_unwritable_path_fails_with_an_explanation(self, tmp_path):
        unwritable = tmp_path / "readonly"
        unwritable.mkdir()
        unwritable.chmod(0o500)
        try:
            result = run_module(unwritable / "ca.json", max_tls_cert_duration="8760h", create=True)
        finally:
            unwritable.chmod(0o700)

        assert result["failed"] is True
        assert "Failed to write JSON file" in result["msg"]

    def test_an_invalid_duration_names_the_option(self, tmp_path):
        result = run_module(existing_config(tmp_path), max_tls_cert_duration="forever")

        assert result["failed"] is True
        assert "max_tls_cert_duration" in result["msg"]

    def test_a_file_that_is_not_a_json_object_is_refused(self, tmp_path):
        # Reaches .update() otherwise, and surfaces as an AttributeError
        # traceback rather than something an operator can act on.
        config_file = tmp_path / "ca.json"
        config_file.write_text('["an", "array"]', encoding="utf-8")

        result = run_module(config_file, max_tls_cert_duration="8760h")

        assert result["failed"] is True
        assert "does not hold a JSON object" in result["msg"]


class TestMissingFile:
    """A path that is not there is a mistake until the task says otherwise.

    Treating it as an empty configuration meant a mistyped json_path produced a
    new, nearly empty file and reported success, while the CA it was meant to
    configure was never touched (#37).
    """

    def test_a_missing_file_fails_and_creates_nothing(self, tmp_path):
        config_file = tmp_path / "ca.json"

        result = run_module(config_file, max_tls_cert_duration="8760h")

        assert result["failed"] is True
        assert "does not exist" in result["msg"]
        assert "create" in result["msg"]
        assert not config_file.exists()

    def test_a_missing_file_with_nothing_requested_still_fails(self, tmp_path):
        # The mistyped-path case is usually noticed on a run that changes
        # nothing, so this must not quietly report ok either.
        config_file = tmp_path / "ca.json"

        assert run_module(config_file)["failed"] is True
        assert not config_file.exists()

    def test_create_writes_a_new_file(self, tmp_path):
        config_file = tmp_path / "ca.json"

        result = run_module(config_file, max_tls_cert_duration="8760h", create=True)

        assert result["changed"] is True
        assert json.loads(config_file.read_text(encoding="utf-8")) == {
            "authority": {"claims": {"maxTLSCertDuration": "8760h"}}
        }

    def test_create_writes_nothing_in_check_mode(self, tmp_path):
        config_file = tmp_path / "ca.json"

        result = run_module(config_file, max_tls_cert_duration="8760h", create=True, _ansible_check_mode=True)

        assert result["changed"] is True
        assert not config_file.exists()


class TestBackup:
    def test_no_backup_is_taken_by_default(self, tmp_path):
        config_file = existing_config(tmp_path)

        result = run_module(config_file, max_tls_cert_duration="8760h")

        assert "backup_file" not in result
        assert [path.name for path in tmp_path.iterdir()] == ["ca.json"]

    def test_backup_preserves_the_previous_contents(self, tmp_path):
        config_file = existing_config(tmp_path, claims={"maxTLSCertDuration": "8760h"})
        before = config_file.read_text(encoding="utf-8")

        result = run_module(config_file, max_tls_cert_duration="17520h", backup=True)

        assert pathlib.Path(result["backup_file"]).read_text(encoding="utf-8") == before
        assert "17520h" in config_file.read_text(encoding="utf-8")

    def test_no_backup_when_nothing_changes(self, tmp_path):
        # A backup per run would litter the CA directory with copies of a file
        # that never changed.
        config_file = existing_config(tmp_path, claims={"maxTLSCertDuration": "8760h"})

        result = run_module(config_file, max_tls_cert_duration="8760h", backup=True)

        assert result["changed"] is False
        assert "backup_file" not in result
        assert [path.name for path in tmp_path.iterdir()] == ["ca.json"]

    def test_no_backup_in_check_mode(self, tmp_path):
        config_file = existing_config(tmp_path)

        run_module(config_file, max_tls_cert_duration="8760h", backup=True, _ansible_check_mode=True)

        assert [path.name for path in tmp_path.iterdir()] == ["ca.json"]


class TestPathHandling:
    def test_a_tilde_in_json_path_is_expanded(self, tmp_path, monkeypatch):
        # json_path used to be type: str, so `~` stayed literal while ca_path
        # and ca_config beside it expanded - and the missing file was then
        # created, producing a directory named `~`.
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "step").mkdir()
        expanded = tmp_path / "step" / "ca.json"
        expanded.write_text("{}", encoding="utf-8")

        result = run_module("~/step/ca.json", max_tls_cert_duration="8760h")

        assert result["changed"] is True
        assert "8760h" in expanded.read_text(encoding="utf-8")
        assert not (tmp_path / "~").exists()


class TestFilePreservation:
    """Attributes of the file being replaced, against the real atomic_move.

    The FakeModule in test_utils uses shutil.move, which models neither
    copystat nor chown, so nothing there would notice atomic_move being called
    with keep_dest_attrs=False. Losing the mode is how step-ca ends up locked
    out of its own configuration.
    """

    def test_the_existing_mode_survives_the_write(self, tmp_path):
        config_file = existing_config(tmp_path)
        config_file.chmod(0o640)

        assert run_module(config_file, max_tls_cert_duration="8760h")["changed"] is True
        assert stat.S_IMODE(config_file.stat().st_mode) == 0o640

    def test_a_symlink_is_followed_not_replaced(self, tmp_path):
        # Replacing the link would leave the file it named holding stale
        # configuration while the CA carried on reading it.
        real = tmp_path / "real-ca.json"
        real.write_text("{}", encoding="utf-8")
        link = tmp_path / "ca.json"
        link.symlink_to(real)

        assert run_module(link, max_tls_cert_duration="8760h")["changed"] is True

        assert link.is_symlink()
        assert "8760h" in real.read_text(encoding="utf-8")

    def test_no_temporary_file_is_left_beside_the_target(self, tmp_path):
        config_file = existing_config(tmp_path)
        run_module(config_file, max_tls_cert_duration="8760h")
        assert sorted(path.name for path in tmp_path.iterdir()) == ["ca.json"]


class TestMalformedAuthority:
    @pytest.mark.parametrize("authority", ["null", '"text"', "3", "[]"], ids=["null", "string", "int", "array"])
    def test_an_authority_that_is_not_an_object_is_refused(self, tmp_path, authority):
        # Reaches setdefault() otherwise, and surfaces as an AttributeError
        # traceback rather than something an operator can act on.
        config_file = tmp_path / "ca.json"
        config_file.write_text(f'{{"authority": {authority}}}', encoding="utf-8")

        result = run_module(config_file, max_tls_cert_duration="8760h")

        assert result["failed"] is True
        assert "'authority' entry" in result["msg"]
