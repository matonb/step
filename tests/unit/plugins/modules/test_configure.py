# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for the configure module's update logic.

The module previously reported C(changed) unconditionally, so a play using the
documented C(notify: restart step-ca) pattern restarted the CA on every run.
These tests pin the comparison that stopped that.
"""

import json
import os
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

# Sourced from the real spec so an option that stops being written shows up
# here, rather than only in the constants the module happens to still list.
NOTHING_REQUESTED = dict.fromkeys(set(get_argument_spec()) - {"json_path"})


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
        assert set(get_argument_spec()) - {"json_path"} == set(TOP_LEVEL_KEYS) | set(CLAIM_KEYS)

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
    def test_a_renormalised_duration_is_not_a_change(self, stored, requested):
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
        config_file = tmp_path / "ca.json"
        run_module(config_file, max_tls_cert_duration="8760h")
        before = config_file.read_bytes()
        mtime = config_file.stat().st_mtime_ns

        assert run_module(config_file, max_tls_cert_duration="8760h")["changed"] is False
        assert config_file.read_bytes() == before
        assert config_file.stat().st_mtime_ns == mtime

    def test_a_changed_setting_is_reported_and_written(self, tmp_path):
        config_file = tmp_path / "ca.json"
        run_module(config_file, max_tls_cert_duration="8760h")

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
        config_file = tmp_path / "ca.json"
        run_module(config_file, max_tls_cert_duration="8760h")

        result = run_module(config_file, max_tls_cert_duration="8760h", _ansible_check_mode=True)

        assert result["changed"] is False

    def test_a_renormalised_file_is_left_alone_end_to_end(self, tmp_path):
        # The realistic case: this module wrote 8760h, then step rewrote ca.json
        # while adding a provisioner and normalised it to 8760h0m0s. Re-running
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
        config_file = tmp_path / "ca.json"
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
            result = run_module(unwritable / "ca.json", max_tls_cert_duration="8760h")
        finally:
            unwritable.chmod(0o700)

        assert result["failed"] is True
        assert "Failed to write JSON file" in result["msg"]

    def test_an_invalid_duration_names_the_option(self, tmp_path):
        result = run_module(tmp_path / "ca.json", max_tls_cert_duration="forever")

        assert result["failed"] is True
        assert "max_tls_cert_duration" in result["msg"]

    def test_requesting_nothing_against_a_missing_file_creates_nothing(self, tmp_path):
        # Behaviour change: this used to write a file containing "{}", which was
        # never a usable ca.json, and reported changed for doing so.
        config_file = tmp_path / "ca.json"

        result = run_module(config_file)

        assert result["changed"] is False
        assert not config_file.exists()
