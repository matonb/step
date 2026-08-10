# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for the provisioner module's argument spec and reconcile logic."""

import inspect
import subprocess

import pytest

from ansible_collections.matonb.smallstep.plugins.module_utils.connection import ManagementMode
from ansible_collections.matonb.smallstep.plugins.module_utils.provisioner import (
    StepProvisionerClient,
    build_provisioner,
)
from ansible_collections.matonb.smallstep.plugins.modules.provisioner import (
    apply_absent,
    apply_present,
    build_connection,
    build_credentials,
    get_argument_spec,
    guard_mode,
    match_provisioners,
    resolve_mode,
)

CONFIG_MARKER = "Success! Your `step-ca` config has been updated."


class ModuleFailedError(Exception):
    """Raised in place of AnsibleModule.fail_json, which exits the process."""


class FakeModule:
    """The slice of AnsibleModule these functions actually use."""

    def __init__(self, check_mode=False, **params):
        """Build a module stub with the option defaults these functions read."""
        # Sourced from the real spec so a renamed option breaks these tests
        # rather than silently leaving a default in place.
        defaults = {name: spec.get("default") for name, spec in get_argument_spec().items()}
        unknown = set(params) - set(defaults)
        if unknown:
            raise AssertionError(f"not module options: {sorted(unknown)}")

        self.params = {**defaults, **params}
        self.check_mode = check_mode
        self.warnings = []
        self.logged = []

    def log(self, message):
        self.logged.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def fail_json(self, msg, **kwargs):
        raise ModuleFailedError(msg)


class FakeClient:
    """Records which CRUD calls the reconcile logic made."""

    def __init__(self, marker=""):
        """Record CRUD calls, reporting the given mode marker on stderr."""
        self.calls = []
        self.marker = marker

    def _result(self):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=self.marker)

    def add(self, name, provisioner_type, claims, password=None):
        self.calls.append(("add", name, provisioner_type))
        return self._result(), "generated-password"

    def update(self, name, claims):
        self.calls.append(("update", name))
        return self._result()

    def remove(self, name):
        self.calls.append(("remove", name))
        return self._result()


def provisioner(name="acme", provisioner_type="ACME", claims=None):
    """Build a provisioner model for the reconcile tests."""
    return build_provisioner({"name": name, "type": provisioner_type, "claims": claims or {}})


class TestArgumentSpec:
    def test_deprecated_alias_is_declared_on_root(self):
        # ca_root emitted an invalid step flag, so it is an alias of root now.
        spec = get_argument_spec()["root"]
        assert spec["aliases"] == ["ca_root"]
        assert spec["deprecated_aliases"][0]["name"] == "ca_root"
        assert spec["deprecated_aliases"][0]["collection_name"] == "matonb.smallstep"

    def test_fingerprint_is_marked_for_removal(self):
        spec = get_argument_spec()["fingerprint"]
        assert spec["removed_in_version"]
        assert spec["removed_from_collection"] == "matonb.smallstep"

    @pytest.mark.parametrize("option", ["admin_key", "admin_password_file"])
    def test_path_options_opt_out_of_the_no_log_heuristic(self, option):
        # These name a file rather than hold a secret; without an explicit
        # no_log, Ansible warns purely on the option name.
        assert get_argument_spec()[option]["no_log"] is False

    def test_the_password_option_is_protected(self):
        assert get_argument_spec()["password"]["no_log"] is True

    def test_claims_have_no_defaults(self):
        # A default here would force every provisioner to that value and drive
        # a perpetual update loop.
        for option in ("x509_default", "x509_max", "x509_min"):
            assert "default" not in get_argument_spec()[option]

    def test_management_mode_choices(self):
        assert set(get_argument_spec()["management_mode"]["choices"]) == {"admin", "auto", "config"}


class TestDoublesMatchTheRealThing:
    """A double that has drifted from its subject keeps passing while broken."""

    @pytest.mark.parametrize("method", ["add", "update", "remove"])
    def test_fake_client_is_call_compatible_with_the_real_client(self, method):
        # Parameter names and defaults, not annotations: what matters is that a
        # call the module makes against the real client also works here, so a
        # renamed or added parameter fails loudly rather than passing silently.
        def shape(func):
            return [(p.name, p.default) for p in inspect.signature(func).parameters.values()]

        assert shape(getattr(FakeClient, method)) == shape(getattr(StepProvisionerClient, method))

    def test_fake_module_rejects_options_that_do_not_exist(self):
        # Guards against a typo silently leaving an option at its default,
        # which reads as "no change" and passes.
        with pytest.raises(AssertionError, match="not module options"):
            FakeModule(name="acme", x509min="20m")


class TestDebugOutput:
    """A module must never write to stdout; Ansible parses it as the result."""

    def test_debug_routes_to_the_ansible_log(self):
        module = FakeModule(name="acme", debug=True)
        assert build_connection(module).logger == module.log

    def test_no_logger_when_debug_is_off(self):
        assert build_connection(FakeModule(name="acme", debug=False)).logger is None

    def test_reconciling_writes_nothing_to_stdout(self, capsys):
        apply_present(FakeModule(name="acme", type="ACME"), FakeClient(marker=CONFIG_MARKER), ManagementMode.CONFIG, [])
        assert capsys.readouterr().out == ""


class TestMatchProvisioners:
    def test_matches_by_name(self):
        found = match_provisioners([provisioner("acme"), provisioner("other")], "acme", None)
        assert [p.name for p in found] == ["acme"]

    def test_type_narrows_the_match(self):
        pool = [provisioner("dup", "ACME"), provisioner("dup", "JWK")]
        assert [p.type for p in match_provisioners(pool, "dup", "JWK")] == ["JWK"]

    def test_no_match_is_empty(self):
        assert match_provisioners([provisioner("acme")], "absent", None) == []


class TestResolveMode:
    def test_explicit_mode_is_taken_at_face_value(self):
        module = FakeModule(name="acme", management_mode="admin")
        assert resolve_mode(module, _connection(module)) is ManagementMode.ADMIN

    def test_explicit_admin_mode_needs_no_ca_json(self):
        # The way out for anyone reaching the CA by ca_url alone.
        module = FakeModule(name="acme", management_mode="admin", ca_url="https://ca.example.com")
        assert resolve_mode(module, _connection(module)) is ManagementMode.ADMIN

    def test_auto_reads_enable_admin(self, tmp_path):
        config_file = tmp_path / "ca.json"
        config_file.write_text('{"authority": {"enableAdmin": true}}', encoding="utf-8")
        module = FakeModule(name="acme", management_mode="auto", ca_config=str(config_file))
        assert resolve_mode(module, _connection(module)) is ManagementMode.ADMIN

    def test_auto_fails_rather_than_guessing_a_mode(self):
        # Assuming 'config' against an admin CA reads the wrong source and
        # writes a file the running CA will never load.
        module = FakeModule(name="acme", management_mode="auto")
        with pytest.raises(ModuleFailedError, match="Cannot determine the management mode"):
            resolve_mode(module, _connection(module))
        assert module.warnings == []

    def test_the_failure_names_both_ways_out(self, tmp_path):
        module = FakeModule(name="acme", management_mode="auto", ca_path=str(tmp_path / "absent"))
        with pytest.raises(ModuleFailedError, match=r"'ca_path'.*'management_mode'"):
            resolve_mode(module, _connection(module))


class TestBuildCredentials:
    def test_absent_options_produce_empty_credentials(self):
        module = FakeModule(name="acme")
        assert build_credentials(module).uses_certificate is False
        assert build_credentials(module).subject is None

    def test_options_are_carried_through(self):
        module = FakeModule(name="acme", admin_subject="step", admin_provisioner="admin", admin_password_file="/p")
        credentials = build_credentials(module)
        assert (credentials.subject, credentials.provisioner, credentials.password_file) == ("step", "admin", "/p")


class TestGuardMode:
    def test_matching_mode_passes_through(self):
        module = FakeModule(name="acme")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=CONFIG_MARKER)
        assert guard_mode(module, ManagementMode.CONFIG, result) is ManagementMode.CONFIG

    def test_config_fallback_during_admin_mode_fails_loudly(self):
        # step rewrote ca.json when the Admin API was expected, so the running
        # CA never saw the change.
        module = FakeModule(name="acme")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=CONFIG_MARKER)
        with pytest.raises(ModuleFailedError, match=r"ca\.json"):
            guard_mode(module, ManagementMode.ADMIN, result)

    def test_admin_path_during_config_mode_only_warns(self):
        module = FakeModule(name="acme")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        assert guard_mode(module, ManagementMode.CONFIG, result) is ManagementMode.ADMIN
        assert module.warnings


class TestApplyAbsent:
    def test_missing_provisioner_is_a_no_op(self):
        client = FakeClient()
        fragment, _mode = apply_absent(FakeModule(state="absent", name="acme"), client, ManagementMode.CONFIG, [])
        assert fragment["changed"] is False
        assert client.calls == []

    def test_existing_provisioner_is_removed(self):
        client = FakeClient(marker=CONFIG_MARKER)
        fragment, mode = apply_absent(
            FakeModule(state="absent", name="acme"), client, ManagementMode.CONFIG, [provisioner()]
        )
        assert fragment["changed"] is True
        assert client.calls == [("remove", "acme")]
        assert mode is ManagementMode.CONFIG

    def test_check_mode_predicts_without_removing(self):
        client = FakeClient()
        fragment, _mode = apply_absent(
            FakeModule(state="absent", name="acme", check_mode=True), client, ManagementMode.CONFIG, [provisioner()]
        )
        assert fragment["changed"] is True
        assert client.calls == []


class TestApplyPresent:
    def test_missing_provisioner_is_created(self):
        client = FakeClient(marker=CONFIG_MARKER)
        module = FakeModule(name="acme", type="ACME")
        fragment, _mode = apply_present(module, client, ManagementMode.CONFIG, [])
        assert fragment["changed"] is True
        assert client.calls == [("add", "acme", "ACME")]

    def test_a_generated_password_is_reported(self):
        client = FakeClient(marker=CONFIG_MARKER)
        fragment, _mode = apply_present(FakeModule(name="acme", type="JWK"), client, ManagementMode.CONFIG, [])
        assert fragment["generated_password"] == "generated-password"

    def test_a_supplied_password_is_never_echoed_back(self):
        client = FakeClient(marker=CONFIG_MARKER)
        fragment, _mode = apply_present(
            FakeModule(name="acme", type="JWK", password="mine"), client, ManagementMode.CONFIG, []
        )
        assert "generated_password" not in fragment

    def test_creating_without_a_type_fails(self):
        with pytest.raises(ModuleFailedError, match="type"):
            apply_present(FakeModule(name="acme"), FakeClient(), ManagementMode.CONFIG, [])

    def test_matching_provisioner_is_left_alone(self):
        client = FakeClient()
        existing = [provisioner(claims={"minTLSCertDuration": "5m0s"})]
        module = FakeModule(name="acme", type="ACME", x509_min="5m")
        fragment, _mode = apply_present(module, client, ManagementMode.CONFIG, existing)
        assert fragment["changed"] is False
        assert client.calls == []

    def test_drifted_claims_are_reconciled(self):
        client = FakeClient(marker=CONFIG_MARKER)
        existing = [provisioner(claims={"minTLSCertDuration": "5m0s"})]
        module = FakeModule(name="acme", type="ACME", x509_min="20m")
        fragment, _mode = apply_present(module, client, ManagementMode.CONFIG, existing)
        assert fragment["changed"] is True
        assert fragment["updated"] == ["x509_min"]
        assert client.calls == [("update", "acme")]

    def test_check_mode_predicts_drift_without_updating(self):
        client = FakeClient()
        existing = [provisioner(claims={"minTLSCertDuration": "5m0s"})]
        module = FakeModule(name="acme", type="ACME", x509_min="20m", check_mode=True)
        fragment, _mode = apply_present(module, client, ManagementMode.CONFIG, existing)
        assert fragment["changed"] is True
        assert client.calls == []

    def test_admin_mode_reports_the_admin_path(self):
        # No ca.json marker means step used the Admin API, which is what makes
        # restart_required false.
        client = FakeClient(marker="")
        _fragment, mode = apply_present(FakeModule(name="acme", type="ACME"), client, ManagementMode.ADMIN, [])
        assert mode is ManagementMode.ADMIN


def _connection(module):
    """Build a connection the way the module does, for resolve_mode tests."""
    return build_connection(module)
