# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for provisioner models, claim reconciliation and the CRUD client."""

import json
import os
import pathlib
import subprocess

import pytest

from ansible_collections.matonb.step.plugins.module_utils.connection import StepConnection
from ansible_collections.matonb.step.plugins.module_utils.provisioner import (
    COMMAND_TIMEOUT,
    X509_CLAIMS,
    ACMEProvisioner,
    GenericProvisioner,
    JWKProvisioner,
    StepProvisionerClient,
    build_provisioner,
    claim_drift,
    claim_flags,
)

NO_CLAIMS = {spec.param: None for spec in X509_CLAIMS}


def completed(stdout="", stderr=""):
    """Build a CompletedProcess standing in for a step invocation."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


class RecordingConnection(StepConnection):
    """A StepConnection that records commands instead of running them."""

    def __init__(self, stdout="[]", error=None):
        """Record commands, optionally raising instead of running."""
        super().__init__()
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "timeouts", [])
        object.__setattr__(self, "_stdout", stdout)
        object.__setattr__(self, "_error", error)

    def run(self, argv, *, timeout=None):
        self.calls.append(argv)
        self.timeouts.append(timeout)
        if self._error:
            raise self._error
        return completed(stdout=self._stdout)


class TestClaimFlags:
    def test_only_requested_claims_are_emitted(self):
        assert claim_flags({**NO_CLAIMS, "x509_min": "20m"}) == ["--x509-min-dur", "20m"]

    def test_nothing_requested_emits_nothing(self):
        assert claim_flags(NO_CLAIMS) == []

    def test_every_claim_maps_to_a_real_step_flag(self):
        emitted = claim_flags({spec.param: "1h" for spec in X509_CLAIMS})
        assert set(emitted[::2]) == {"--x509-default-dur", "--x509-max-dur", "--x509-min-dur"}


class TestClaimDrift:
    def test_unset_claim_on_the_ca_counts_as_drift(self):
        # An absent claim means the provisioner inherits the authority default
        # rather than the value the task asked for.
        assert claim_drift({**NO_CLAIMS, "x509_min": "5m"}, {}) == ["x509_min"]

    def test_normalised_equivalent_is_not_drift(self):
        assert claim_drift({**NO_CLAIMS, "x509_min": "5m"}, {"minTLSCertDuration": "5m0s"}) == []

    def test_different_value_is_drift(self):
        assert claim_drift({**NO_CLAIMS, "x509_min": "5m"}, {"minTLSCertDuration": "10m0s"}) == ["x509_min"]

    def test_unmanaged_claim_is_left_alone(self):
        # A claim the task does not set must never be reconciled.
        assert claim_drift(NO_CLAIMS, {"minTLSCertDuration": "10m0s"}) == []

    def test_fractional_value_settles(self):
        # Under float arithmetic this reported drift forever.
        assert claim_drift({**NO_CLAIMS, "x509_default": "1.1h"}, {"defaultTLSCertDuration": "1h6m0s"}) == []

    def test_unreadable_requested_value_raises(self):
        # Reporting drift instead would update on every run without settling.
        with pytest.raises(ValueError, match="x509_min"):
            claim_drift({**NO_CLAIMS, "x509_min": "36hours"}, {"minTLSCertDuration": "5m0s"})

    def test_unreadable_reported_value_raises(self):
        with pytest.raises(ValueError, match="minTLSCertDuration"):
            claim_drift({**NO_CLAIMS, "x509_min": "5m"}, {"minTLSCertDuration": "not-a-duration"})

    def test_drift_is_reported_in_table_order(self):
        desired = {spec.param: "99h" for spec in X509_CLAIMS}
        assert claim_drift(desired, {}) == [spec.param for spec in X509_CLAIMS]


class TestBuildProvisioner:
    @pytest.mark.parametrize(
        ("provisioner_type", "expected"),
        [("JWK", JWKProvisioner), ("ACME", ACMEProvisioner)],
    )
    def test_supported_types_get_their_own_class(self, provisioner_type, expected):
        assert isinstance(build_provisioner({"name": "p", "type": provisioner_type}), expected)

    @pytest.mark.parametrize("provisioner_type", ["OIDC", "X5C", "SCEP", "Nebula", "K8SSA", "SSHPOP"])
    def test_other_types_are_still_modelled(self, provisioner_type):
        # Discarding these made `state: absent` a silent no-op against them.
        provisioner = build_provisioner({"name": "p", "type": provisioner_type})
        assert isinstance(provisioner, GenericProvisioner)
        assert provisioner.name == "p"

    def test_jwk_key_material_is_carried(self):
        provisioner = build_provisioner(
            {"name": "p", "type": "JWK", "key": {"kid": "abc"}, "encryptedKey": "enc"},
        )
        assert provisioner.to_dict()["key"] == {"kid": "abc"}
        assert provisioner.to_dict()["encryptedKey"] == "enc"

    def test_missing_claims_become_an_empty_mapping(self):
        assert build_provisioner({"name": "p", "type": "ACME"}).claims == {}


class TestAddArguments:
    def test_acme_needs_nothing(self):
        assert ACMEProvisioner(name="a", type="ACME").add_arguments().args == []

    def test_jwk_creates_a_key_and_a_password_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
        extra = JWKProvisioner(name="j", type="JWK").add_arguments()
        try:
            assert "--create" in extra.args
            assert extra.args[extra.args.index("--password-file") + 1] == extra.secret_file
            assert pathlib.Path(extra.secret_file).read_text(encoding="utf-8") == extra.password
        finally:
            os.remove(extra.secret_file)

    def test_jwk_honours_a_supplied_password(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
        extra = JWKProvisioner(name="j", type="JWK").add_arguments(password="chosen")
        try:
            assert extra.password == "chosen"
        finally:
            os.remove(extra.secret_file)

    def test_unsupported_type_refuses_with_a_useful_message(self):
        with pytest.raises(ValueError, match=r"OIDC.*not supported"):
            GenericProvisioner(name="o", type="OIDC").add_arguments()


class TestStepProvisionerClient:
    def test_list_parses_every_reported_provisioner(self):
        payload = json.dumps([{"name": "admin", "type": "JWK"}, {"name": "corp", "type": "OIDC"}])
        client = StepProvisionerClient(RecordingConnection(stdout=payload))
        assert [(p.name, p.type) for p in client.list()] == [("admin", "JWK"), ("corp", "OIDC")]

    def test_list_rejects_output_that_is_not_json(self):
        client = StepProvisionerClient(RecordingConnection(stdout="not json"))
        with pytest.raises(RuntimeError, match="JSON"):
            client.list()

    def test_add_builds_the_expected_command(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
        connection = RecordingConnection()
        StepProvisionerClient(connection).add("acme", "ACME", {**NO_CLAIMS, "x509_min": "20m"})
        argv = connection.calls[0]
        assert argv[:5] == ["step", "ca", "provisioner", "add", "acme"]
        assert argv[argv.index("--type") + 1] == "ACME"
        assert "--x509-min-dur" in argv

    def test_add_removes_its_secret_file_when_the_command_fails(self, tmp_path, monkeypatch):
        # The password file must never outlive a failed run.
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
        connection = RecordingConnection(error=RuntimeError("step exploded"))
        with pytest.raises(RuntimeError, match="step exploded"):
            StepProvisionerClient(connection).add("cicd", "JWK", NO_CLAIMS)
        assert list(tmp_path.iterdir()) == []

    def test_add_refuses_an_unsupported_type_before_running_anything(self):
        connection = RecordingConnection()
        with pytest.raises(ValueError, match="not supported"):
            StepProvisionerClient(connection).add("corp", "OIDC", NO_CLAIMS)
        assert connection.calls == []

    def test_update_sends_only_the_requested_claims(self):
        connection = RecordingConnection()
        StepProvisionerClient(connection).update("cicd", {**NO_CLAIMS, "x509_default": "48h"})
        assert connection.calls[0] == ["step", "ca", "provisioner", "update", "cicd", "--x509-default-dur", "48h"]

    def test_remove_names_the_provisioner(self):
        connection = RecordingConnection()
        StepProvisionerClient(connection).remove("acme")
        assert connection.calls[0] == ["step", "ca", "provisioner", "remove", "acme"]

    def test_every_command_carries_a_timeout(self, tmp_path, monkeypatch):
        # The timeout is how an unexpected interactive prompt surfaces as a
        # failure instead of a task that hangs until someone notices.
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
        connection = RecordingConnection()
        client = StepProvisionerClient(connection)
        client.list()
        client.add("acme", "ACME", NO_CLAIMS)
        client.update("acme", NO_CLAIMS)
        client.remove("acme")
        assert connection.timeouts == [COMMAND_TIMEOUT] * 4
