# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for building the `step ca init` command and its option guards."""

import json
import os

import pytest

from ansible_collections.matonb.smallstep.plugins.modules import initialize
from ansible_collections.matonb.smallstep.plugins.modules.initialize import (
    CA_FILE_NAMES,
    build_initialize_command,
    configured_paths,
    default_admin_subject,
    find_existing_ca_files,
    get_argument_spec,
    pki_file_paths,
    remove_ca_files,
    unusable_paths,
    validate_admin_options,
)

# Printed on stderr by the stubbed `step` and quoted back in the module's
# failure message, so a test can prove the stub - and therefore the environment
# carrying it - actually reached the child process.
STEP_STUB_MARKER = "stub-step-ca-refused"


class ModuleFailedError(Exception):
    """Raised in place of AnsibleModule.fail_json, which exits the process."""


class FakeModule:
    def __init__(self, **params):
        """Build a module stub carrying just the params under test."""
        self.params = params

    def fail_json(self, msg, **kwargs):
        raise ModuleFailedError(msg)


def command_for(**params):
    """Build an init command from the required options plus overrides."""
    base = {
        "name": "Test CA",
        "path": "/etc/step-ca",
        "password_file": "/secrets/pw",
        "provisioner_password_file": "/secrets/pp",
    }
    return build_initialize_command({**base, **params})


class TestBuildInitializeCommand:
    def test_starts_with_the_step_subcommand(self):
        assert command_for()[:3] == ["step", "ca", "init"]

    def test_underscores_become_hyphens(self):
        assert "--password-file" in command_for()
        assert "--provisioner-password-file" in command_for()

    def test_unset_options_emit_nothing(self):
        emitted = [token for token in command_for() if token.startswith("--")]
        assert "--acme" not in emitted
        assert "--ra" not in emitted

    def test_admin_subject_is_emitted(self):
        # It used to be special-cased, and silently dropped without
        # remote_management; validate_admin_options now rejects that instead.
        command = command_for(admin_subject="step", remote_management=True)
        assert command[command.index("--admin-subject") + 1] == "step"

    def test_remote_management_is_a_bare_flag(self):
        command = command_for(remote_management=True)
        assert "--remote-management" in command
        # The next token must be another flag, not a value.
        following = command[command.index("--remote-management") + 1 :]
        assert following == [] or following[0].startswith("--")

    @pytest.mark.parametrize("option", ["acme", "no_db", "pki", "ssh"])
    def test_boolean_flags_carry_no_value(self, option):
        flag = f"--{option.replace('_', '-')}"
        command = command_for(**{option: True})
        following = command[command.index(flag) + 1 :]
        assert following == [] or following[0].startswith("--")

    def test_false_booleans_are_omitted(self):
        assert "--acme" not in command_for(acme=False)

    def test_dns_repeats_the_flag_per_entry(self):
        command = command_for(dns=["ca.example.com", "10.0.0.1"])
        pairs = [(token, command[i + 1]) for i, token in enumerate(command) if token == "--dns"]
        assert pairs == [("--dns", "ca.example.com"), ("--dns", "10.0.0.1")]

    def test_values_are_stripped(self):
        command = command_for(name="  Test CA  ")
        assert command[command.index("--name") + 1] == "Test CA"

    def test_deployment_type_is_passed_through(self):
        command = command_for(deployment_type="standalone")
        assert command[command.index("--deployment-type") + 1] == "standalone"


class TestValidateAdminOptions:
    def test_remote_management_with_a_database_is_fine(self):
        validate_admin_options(FakeModule(remote_management=True, no_db=False, admin_subject=None))

    def test_remote_management_without_a_database_is_rejected(self):
        # step itself refuses this; failing here avoids spawning it.
        with pytest.raises(ModuleFailedError, match="no_db"):
            validate_admin_options(FakeModule(remote_management=True, no_db=True, admin_subject=None))

    def test_admin_subject_without_remote_management_is_rejected(self):
        with pytest.raises(ModuleFailedError, match="admin_subject"):
            validate_admin_options(FakeModule(remote_management=False, no_db=False, admin_subject="step"))

    def test_neither_option_is_fine(self):
        validate_admin_options(FakeModule(remote_management=None, no_db=None, admin_subject=None))


class TestArgumentSpec:
    @pytest.mark.parametrize("option", ["name", "password_file", "path", "provisioner_password_file"])
    def test_required_options(self, option):
        assert get_argument_spec()[option]["required"] is True

    def test_help_keys_are_gone(self):
        # `help` is not part of the argument spec schema; Ansible ignores it, so
        # the text reached nobody. Descriptions belong in DOCUMENTATION.
        assert not [name for name, spec in get_argument_spec().items() if "help" in spec]

    def test_deployment_type_choices(self):
        assert set(get_argument_spec()["deployment_type"]["choices"]) == {"hosted", "linked", "standalone"}


class TestDefaultAdminSubject:
    """One derivation, used by both exits, so the two cannot drift apart.

    They did: the initializing path defaulted to "step" while the
    already-initialized path returned the raw parameter, so the same task
    reported a different subject on its second run.
    """

    def test_an_admin_ca_with_no_subject_gets_steps_default(self):
        assert default_admin_subject({}, "admin") == "step"

    def test_a_config_ca_has_no_administrator_to_name(self):
        assert default_admin_subject({}, "config") is None

    def test_a_supplied_subject_wins_in_admin_mode(self):
        assert default_admin_subject({"admin_subject": "ops"}, "admin") == "ops"

    def test_a_supplied_subject_is_dropped_in_config_mode(self):
        # The mode decides, not the request. A task asking for an admin CA and
        # meeting a config-mode one must not be handed back the subject it
        # asked for: there is no super administrator on that host to name.
        assert default_admin_subject({"admin_subject": "ops"}, "config") is None


class TestPkiFilePaths:
    """The one case with no ca.json to consult, so a fixed list is all there is."""

    def test_the_configuration_files_are_not_expected(self):
        # `step ca init --pki` writes the PKI and stops (pki.go, guarded by
        # pkiOnly), so neither config file ever appears.
        names = [os.path.basename(path) for path in pki_file_paths("/ca")]
        assert "ca.json" not in names
        assert "defaults.json" not in names

    def test_the_keys_and_certificates_are(self):
        # Asserted as literals: taking them from CA_FILE_NAMES would let the
        # filter widen to everything without a test noticing.
        assert set(pki_file_paths("/ca")) == {
            "/ca/certs/intermediate_ca.crt",
            "/ca/certs/root_ca.crt",
            "/ca/secrets/intermediate_ca_key",
            "/ca/secrets/root_ca_key",
        }


class TestConfiguredPaths:
    """Which files a ca.json says step-ca needs.

    This is what replaced the hardcoded list: a registration authority owns no
    root key and a linked deployment keeps its keys elsewhere, so any fixed set
    of filenames is wrong for somebody. Asking the configuration is not.
    """

    def test_the_top_level_key_material(self):
        config = {"root": "/ca/certs/root_ca.crt", "crt": "/ca/certs/x.crt", "key": "/ca/secrets/x_key"}
        assert set(configured_paths(config, "/ca")) == set(config.values())

    def test_relative_entries_resolve_against_the_ca_directory(self):
        # step-ca runs with WorkingDirectory=STEPPATH and is handed a relative
        # config path, so relative means relative to the CA, not to Ansible.
        assert configured_paths({"root": "certs/root_ca.crt"}, "/ca") == ["/ca/certs/root_ca.crt"]

    def test_absolute_entries_are_left_alone(self):
        assert configured_paths({"root": "/elsewhere/root.crt"}, "/ca") == ["/elsewhere/root.crt"]

    def test_federated_roots_are_included(self):
        paths = configured_paths({"federatedRoots": ["certs/other.crt", "/abs/third.crt"]}, "/ca")
        assert paths == ["/ca/certs/other.crt", "/abs/third.crt"]

    @pytest.mark.parametrize("key", ["root", "federatedRoots"])
    def test_multistring_entries_are_read_as_a_bare_string(self, key):
        # Upstream types both as multiString, which unmarshals from a string or
        # a list. Reading only one shape leaves a multi-root CA unchecked.
        assert configured_paths({key: "certs/one.crt"}, "/ca") == ["/ca/certs/one.crt"]

    @pytest.mark.parametrize("key", ["root", "federatedRoots"])
    def test_multistring_entries_are_read_as_a_list(self, key):
        paths = configured_paths({key: ["certs/one.crt", "certs/two.crt"]}, "/ca")
        assert paths == ["/ca/certs/one.crt", "/ca/certs/two.crt"]

    @pytest.mark.parametrize(
        "uri",
        [
            "azurekms:name=intermediate;vault=my-vault",
            "pkcs11:token=YubiHSM;id=7331?pin-value=0001password",
            "cloudkms:projects/p/locations/l/keyRings/r/cryptoKeys/k",
            "awskms:key-id=abcd-1234",
        ],
    )
    def test_a_kms_uri_is_not_a_path_on_this_host(self, uri):
        # `--kms` and friends put these in `key`. Joining one onto the CA
        # directory produced a filename that could never exist, so a healthy
        # KMS-backed CA was reported broken and its operator told to use force
        # - the very defect this whole check was written to remove.
        assert configured_paths({"key": uri}, "/ca") == []

    def test_the_registration_authority_credentials_are_included(self):
        # CloudCAS writes this, and the module has a credentials_file option
        # that puts it there.
        config = {"authority": {"type": "cloudcas", "credentialsFile": "secrets/ra.json"}}
        assert configured_paths(config, "/ca") == ["/ca/secrets/ra.json"]

    def test_a_path_holding_a_colon_is_still_a_path(self):
        # The URI guard must not eat a legitimate filename. A scheme cannot
        # contain a separator, so a relative path never looks like one.
        assert configured_paths({"root": "certs/odd:name.crt"}, "/ca") == ["/ca/certs/odd:name.crt"]

    def test_the_ssh_template_files_are_deliberately_not_checked(self):
        # `--ssh` does write a templates block naming real files. Leaving them
        # out errs towards calling a CA complete, and erring the other way is
        # what made this module unusable for RA and linked deployments.
        config = {"templates": {"ssh": {"user": [{"template": "templates/ssh/config.tpl"}]}}}
        assert configured_paths(config, "/ca") == []

    def test_the_ssh_certificate_authorities_are_included(self):
        # `--ssh` adds these, and the old filename list could not see them at
        # all: an SSH CA missing its host key read as complete.
        config = {"ssh": {"hostKey": "secrets/ssh_host_ca_key", "userKey": "secrets/ssh_user_ca_key"}}
        assert configured_paths(config, "/ca") == [
            "/ca/secrets/ssh_host_ca_key",
            "/ca/secrets/ssh_user_ca_key",
        ]

    def test_the_database_is_not_a_file_to_check(self):
        # step-ca creates it on first start, so a CA that has never run has
        # none. Requiring it would fail a CA that works.
        assert configured_paths({"db": {"type": "badgerv2", "dataSource": "/ca/db"}}, "/ca") == []

    def test_a_configuration_naming_nothing_yields_nothing(self):
        # An RA proxies signing upstream and holds no local key material.
        assert configured_paths({"authority": {"type": "stepcas"}}, "/ca") == []

    def test_duplicates_are_reported_once(self):
        config = {"root": "certs/root_ca.crt", "crt": "/ca/certs/root_ca.crt"}
        assert configured_paths(config, "/ca") == ["/ca/certs/root_ca.crt"]

    @pytest.mark.parametrize("value", [None, "", 42, {}, [42, None], [""]])
    def test_entries_that_are_not_paths_are_ignored(self, value):
        assert configured_paths({"root": value}, "/ca") == []


class TestUnusablePaths:
    """Missing and unreadable are kept apart, because they want opposite advice.

    Answering a permission problem with `force` would delete a healthy root key
    over a file mode.
    """

    def test_a_present_non_empty_file_is_usable(self, tmp_path):
        path = tmp_path / "key"
        path.write_text("material", encoding="utf-8")
        assert unusable_paths([str(path)]) == ([], [])

    def test_a_missing_file_is_not(self, tmp_path):
        assert unusable_paths([str(tmp_path / "gone")]) == ([str(tmp_path / "gone")], [])

    def test_an_empty_file_is_not(self, tmp_path):
        # The reason unit.j2 uses ConditionFileNotEmpty: a truncated key is not
        # a key, and a zero-byte root certificate does not start a CA.
        path = tmp_path / "key"
        path.write_text("", encoding="utf-8")
        assert unusable_paths([str(path)]) == ([str(path)], [])

    def test_a_directory_is_not_a_file(self, tmp_path):
        assert unusable_paths([str(tmp_path)]) == ([str(tmp_path)], [])

    def test_a_file_behind_an_unsearchable_directory_is_unreadable_not_missing(self, tmp_path):
        # os.path.isfile() answers False for a permission error exactly as it
        # does for a file that is not there. Conflating them told an operator
        # running as the wrong user to destroy a working CA.
        secrets = tmp_path / "secrets"
        secrets.mkdir()
        key = secrets / "root_ca_key"
        key.write_text("material", encoding="utf-8")
        secrets.chmod(0o000)
        try:
            missing, unreadable = unusable_paths([str(key)])
        finally:
            secrets.chmod(0o700)

        assert missing == []
        assert unreadable == [str(key)]

    def test_a_symlink_is_judged_by_its_target(self, tmp_path):
        target = tmp_path / "real"
        target.write_text("material", encoding="utf-8")
        link = tmp_path / "link"
        link.symlink_to(target)
        assert unusable_paths([str(link)]) == ([], [])

    def test_a_broken_symlink_is_not_usable(self, tmp_path):
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "gone")
        assert unusable_paths([str(link)]) == ([str(link)], [])


# What `step ca init` writes into a standalone CA's ca.json. Relative, as step
# writes them, and naming exactly the files the module now checks for.
STANDALONE_CONFIG = {
    "root": "certs/root_ca.crt",
    "crt": "certs/intermediate_ca.crt",
    "key": "secrets/intermediate_ca_key",
}


def ca_file_body(name, enable_admin=False):
    """Return plausible content for one of the CA's files.

    `config/ca.json` is a real, standalone-shaped configuration, because
    completeness is now judged by the paths it names - a fixture writing
    something shapeless there would test the failure path while claiming to
    test the happy one.

    Every file also carries a marker, so a test can tell "untouched" from
    "rewritten", which is what the #35 regression tests turn on.
    """
    marker = f"PRECIOUS-{name}"
    if name == "config/ca.json":
        return json.dumps({**STANDALONE_CONFIG, "authority": {"enableAdmin": enable_admin}, "_marker": marker})
    if name.endswith(".json"):
        return json.dumps({"_marker": marker})
    return marker


def build_ca(tmp_path, names=CA_FILE_NAMES, enable_admin=False):
    """Populate a directory with the files `step ca init` creates.

    Pass a subset for a partially initialized directory, which the module
    treats differently from a complete one.
    """
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ca_file_body(name, enable_admin), encoding="utf-8")
    return [tmp_path / name for name in names]


class TestFindExistingCaFiles:
    """Detection must never delete. It used to, which is what caused #35."""

    def test_an_empty_directory_holds_no_ca(self, tmp_path):
        assert find_existing_ca_files(str(tmp_path)) == []

    def test_an_existing_ca_is_reported(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "ca.json").write_text("{}")
        assert find_existing_ca_files(str(tmp_path)) == [str(tmp_path / "config" / "ca.json")]

    def test_a_complete_ca_reports_every_file(self, tmp_path):
        build_ca(tmp_path)
        assert find_existing_ca_files(str(tmp_path)) == [str(tmp_path / name) for name in CA_FILE_NAMES]

    def test_detection_leaves_everything_in_place(self, tmp_path):
        # The heart of #35: asking whether a CA exists must not destroy it.
        files = build_ca(tmp_path)
        find_existing_ca_files(str(tmp_path))
        assert all(path.exists() for path in files)

    def test_the_file_list_is_the_one_step_creates(self):
        # Asserted as literals: every other test here takes the names from
        # CA_FILE_NAMES, so dropping the root key from it would go unnoticed
        # and force would silently stop removing it.
        assert CA_FILE_NAMES == (
            "certs/intermediate_ca.crt",
            "certs/root_ca.crt",
            "config/ca.json",
            "config/defaults.json",
            "secrets/intermediate_ca_key",
            "secrets/root_ca_key",
        )


class TestRemoveCaFiles:
    def test_every_file_is_removed(self, tmp_path):
        files = build_ca(tmp_path)
        remove_ca_files(str(tmp_path))
        assert not [path for path in files if path.exists()]

    def test_a_partial_ca_is_not_an_error(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "ca.json").write_text("{}")
        remove_ca_files(str(tmp_path))
        assert find_existing_ca_files(str(tmp_path)) == []


def stub_step_binary(tmp_path):
    """Put a `step` on PATH that always fails, and return the env to use.

    Without this, a test that reaches the real `step ca init` behaves
    differently on every host: absent in CI, refusing for want of a terminal
    under a pipe, and - for a developer running pytest in their own shell -
    opening /dev/tty to prompt for DNS names, which blocks until the command
    timeout. It also couples the assertion to step continuing to refuse to run
    non-interactively.

    The stub announces itself on stderr, which the module quotes back in its
    failure message. Failing silently would not be enough: the real step fails
    too, so `failed is True` holds whether or not this stub was ever on PATH,
    and nothing would notice the env that puts it there going missing.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "step"
    stub.write_text(f"#!/bin/sh\necho {STEP_STUB_MARKER} >&2\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    return {"PATH": os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])}


@pytest.fixture
def run_initialize(run_module):
    """Run the initialize module against a step path and return its result.

    Driving main() is the only way to catch #35: the defect was purely the
    order of two calls, so every test of the functions themselves passed with
    it in place.

    Environment handling - the PYTHONPATH filter and why the child needs it -
    lives in the `run_module` fixture in tests/unit/conftest.py.

    Returns:
        callable: (step_path, password_file, extra_env=None, **requested) ->
            dict, the module's parsed result. `extra_env` reaches the child's
            environment, which is how stub_step_binary puts its `step` on PATH.
    """

    def _run(step_path, password_file, extra_env=None, **requested):
        return run_module(
            initialize,
            {
                "name": "Test CA",
                "path": str(step_path),
                "password_file": str(password_file),
                "provisioner_password_file": str(password_file),
                **requested,
            },
            extra_env=extra_env,
        )

    return _run


class TestCheckModeNeverDeletes:
    """Regression tests for #35.

    `check_existing_ca_files()` both detected and deleted, and ran before the
    check-mode guard, so `--check` with `force: true` unlinked the CA's private
    keys and then reported what it "would" do. The root CA key cannot be
    regenerated.
    """

    def test_check_mode_with_force_leaves_an_existing_ca_intact(self, tmp_path, run_initialize):
        ca = tmp_path / "ca"
        ca.mkdir()
        files = build_ca(ca)
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_initialize(ca, password_file, force=True, _ansible_check_mode=True)

        assert result["changed"] is True
        assert [path.name for path in files if not path.exists()] == []
        assert all("PRECIOUS-" in path.read_text(encoding="utf-8") for path in files)

    def test_check_mode_with_force_says_it_would_delete(self, tmp_path, run_initialize):
        # Reporting `changed` is not enough: an operator running --check to find
        # out what force does needs to be told the CA goes away.
        ca = tmp_path / "ca"
        ca.mkdir()
        build_ca(ca)
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_initialize(ca, password_file, force=True, _ansible_check_mode=True)

        assert "deleted" in result["msg"]

    def test_check_mode_without_force_still_refuses_a_partial_ca(self, tmp_path, run_initialize):
        ca = tmp_path / "ca"
        ca.mkdir()
        files = build_ca(ca, names=CA_FILE_NAMES[:3])
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_initialize(ca, password_file, _ansible_check_mode=True)

        assert "not a working CA" in result["msg"]
        assert all(path.exists() for path in files)

    def test_check_mode_on_an_empty_directory_creates_nothing(self, tmp_path, run_initialize):
        ca = tmp_path / "ca"
        ca.mkdir()
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_initialize(ca, password_file, _ansible_check_mode=True)

        assert result["changed"] is True
        assert list(ca.iterdir()) == []


class TestForceOutsideCheckMode:
    def test_force_still_removes_an_existing_ca(self, tmp_path, run_initialize):
        # The other half of the fix: moving the deletion below the check-mode
        # guard must not stop it happening on a real run. The stubbed step
        # fails, so nothing is recreated and the deletion is observable.
        ca = tmp_path / "ca"
        ca.mkdir()
        files = build_ca(ca)
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_initialize(ca, password_file, force=True, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        # Pins `extra_env` reaching the child. Every other stubbed test either
        # fails before step is reached at all, or asserts a failure the real
        # step would produce too, so the forwarding could be dropped without any
        # of them noticing - exactly the regression a shared helper makes easy.
        assert STEP_STUB_MARKER in result["msg"]
        assert [path for path in files if path.exists()] == []

    def test_without_force_a_real_run_refuses_a_partial_ca(self, tmp_path, run_initialize):
        # The production path. Check mode is covered above; if the guard on the
        # no-force branch were weakened, only this test would notice - and this
        # is the run that would actually overwrite a PKI nobody asked to replace.
        ca = tmp_path / "ca"
        ca.mkdir()
        files = build_ca(ca, names=CA_FILE_NAMES[:3])
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        # The message matters, not just the failure: with the guard removed the
        # module reaches step, which also fails, so asserting `failed` alone
        # passes either way and proves nothing.
        assert "not a working CA" in result["msg"]
        assert all("PRECIOUS-" in path.read_text(encoding="utf-8") for path in files)


class TestAlreadyInitialized:
    """A CA that is already there is the desired state, not a failure (#36).

    Previously any of the six files existing made the task fail, so a play
    containing it could only ever be run once.
    """

    def build(self, tmp_path, names=CA_FILE_NAMES, enable_admin=False):
        """Return a CA directory and a password file to run against."""
        ca = tmp_path / "ca"
        ca.mkdir()
        files = build_ca(ca, names=names, enable_admin=enable_admin)
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")
        return ca, password_file, files

    def test_a_complete_ca_reports_ok_and_changes_nothing(self, tmp_path, run_initialize):
        ca, password_file, files = self.build(tmp_path)

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["changed"] is False
        assert "already initialized" in result["msg"]
        assert all("PRECIOUS-" in path.read_text(encoding="utf-8") for path in files)

    def test_the_same_holds_in_check_mode(self, tmp_path, run_initialize):
        ca, password_file, files = self.build(tmp_path)

        result = run_initialize(ca, password_file, _ansible_check_mode=True)

        assert result["changed"] is False
        assert all(path.exists() for path in files)

    def test_the_no_op_reports_the_mode_of_the_ca_on_disk(self, tmp_path, run_initialize):
        # Not the mode that was asked for. A task requesting remote_management
        # against a config-mode CA must not be told it got one: the key is what
        # examples/provisioner_admin_mode.yml asserts on.
        ca, password_file, _files = self.build(tmp_path, enable_admin=False)

        result = run_initialize(
            ca,
            password_file,
            remote_management=True,
            extra_env=stub_step_binary(tmp_path),
        )

        assert result["management_mode"] == "config"
        # And the subject follows the observed mode, not the request: a CA with
        # no Admin API has no super administrator to name.
        assert result["admin_subject"] is None

    def test_an_admin_ca_is_reported_as_admin(self, tmp_path, run_initialize):
        ca, password_file, _files = self.build(tmp_path, enable_admin=True)

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["management_mode"] == "admin"
        # step's own default, and the same value the initializing path reports,
        # so the second run of a task does not contradict the first.
        assert result["admin_subject"] == "step"

    def test_a_supplied_admin_subject_is_echoed(self, tmp_path, run_initialize):
        ca, password_file, _files = self.build(tmp_path, enable_admin=True)

        result = run_initialize(
            ca,
            password_file,
            remote_management=True,
            admin_subject="ops",
            extra_env=stub_step_binary(tmp_path),
        )

        assert result["admin_subject"] == "ops"

    def test_an_unparseable_ca_json_is_not_a_finished_ca(self, tmp_path, run_initialize):
        # Every file is present, so the old check called this complete and let
        # the play carry on against a CA that cannot start. Existing is not the
        # same as working.
        ca, password_file, _files = self.build(tmp_path)
        (ca / "config" / "ca.json").write_text("{ this is not json", encoding="utf-8")

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        assert "cannot read" in result["msg"]
        # And it must not reach for force. The keys are intact and the file can
        # be put back; force would delete the root key to clear a syntax error.
        assert "root key" not in result["msg"]

    def test_a_ca_json_of_the_wrong_shape_is_not_a_finished_ca(self, tmp_path, run_initialize):
        # Valid JSON, wrong document. read_authority separates "nothing is
        # configured" from "this is not the file you think it is".
        ca, password_file, _files = self.build(tmp_path)
        (ca / "config" / "ca.json").write_text(json.dumps({"authority": "nonsense"}), encoding="utf-8")

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        assert "cannot read" in result["msg"]

    def test_a_pki_only_directory_reports_the_requested_mode(self, tmp_path, run_initialize):
        # The one case with no ca.json to read, so the request is all there is.
        # Asking for admin proves the fallback runs: a hard-coded "config", or
        # one that failed on the missing file, would both be caught here.
        names = tuple(name for name in CA_FILE_NAMES if not name.startswith("config/"))
        ca, password_file, _files = self.build(tmp_path, names=names)

        result = run_initialize(
            ca,
            password_file,
            pki=True,
            remote_management=True,
            extra_env=stub_step_binary(tmp_path),
        )

        assert result["management_mode"] == "admin"
        assert result["admin_subject"] == "step"

    def test_a_pki_only_directory_is_complete_without_ca_json(self, tmp_path, run_initialize):
        # `step ca init --pki` writes the PKI and stops, so config/ca.json and
        # config/defaults.json never appear and their absence is not a
        # half-built CA.
        names = tuple(name for name in CA_FILE_NAMES if not name.startswith("config/"))
        ca, password_file, files = self.build(tmp_path, names=names)

        result = run_initialize(ca, password_file, pki=True, extra_env=stub_step_binary(tmp_path))

        assert result["changed"] is False
        assert all(path.exists() for path in files)

    def test_pki_does_not_switch_off_the_checks_on_a_full_ca(self, tmp_path, run_initialize):
        # The --pki branch is entered because there is no ca.json to consult,
        # not because the task asked for it. Otherwise one option would let a
        # broken CA through every integrity check the module has.
        ca, password_file, _files = self.build(tmp_path)
        (ca / "config" / "ca.json").write_text("{ this is not json", encoding="utf-8")

        result = run_initialize(ca, password_file, pki=True, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        assert "cannot read" in result["msg"]

    def test_a_pki_directory_missing_key_material_is_refused(self, tmp_path, run_initialize):
        # --pki is the one case judged against a fixed list, because it writes
        # no ca.json to ask. That list still has to be enforced: without this
        # the whole --pki branch could be deleted and every other test passes.
        names = tuple(name for name in CA_FILE_NAMES if not name.startswith("config/") and name != "secrets/root_ca_key")
        ca, password_file, _files = self.build(tmp_path, names=names)

        result = run_initialize(ca, password_file, pki=True, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        assert "root_ca_key" in result["msg"]

    def test_a_pki_only_directory_is_still_partial_without_the_flag(self, tmp_path, run_initialize):
        names = tuple(name for name in CA_FILE_NAMES if not name.startswith("config/"))
        ca, password_file, _files = self.build(tmp_path, names=names)

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        # The message, not just `failed`: with the guard gone the module reaches
        # the stubbed step, which fails too, so asserting the flag alone passes
        # either way and proves nothing.
        assert result["failed"] is True
        assert "not a working CA" in result["msg"]

    @pytest.mark.parametrize("count", [1, 3], ids=["one-file", "no-key-material"])
    def test_a_directory_that_is_not_yet_a_ca_is_refused(self, tmp_path, count, run_initialize):
        # Ambiguous: initializing over it could destroy half a PKI.
        ca, password_file, files = self.build(tmp_path, names=CA_FILE_NAMES[:count])

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        assert "not a working CA" in result["msg"]
        assert all(path.exists() for path in files)

    @pytest.mark.parametrize(
        "missing",
        ["certs/root_ca.crt", "certs/intermediate_ca.crt", "secrets/intermediate_ca_key"],
    )
    def test_a_ca_missing_a_file_its_own_config_names_is_refused(self, tmp_path, missing, run_initialize):
        # The half-built case the old filename list was there to catch, now
        # caught from the CA's own account of what it needs.
        names = tuple(name for name in CA_FILE_NAMES if name != missing)
        ca, password_file, _files = self.build(tmp_path, names=names)

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        assert "not a working CA" in result["msg"]
        # Named, not just counted: an operator has to know which file to restore.
        assert os.path.basename(missing) in result["msg"]

    def test_a_ca_whose_root_key_is_kept_offline_is_complete(self, tmp_path, run_initialize):
        # Best practice, and what the filename list got wrong. step-ca signs
        # with the intermediate key; the root key is only needed to issue a new
        # intermediate, so it belongs offline. ca.json never names it, and the
        # CA works without it.
        names = tuple(name for name in CA_FILE_NAMES if name != "secrets/root_ca_key")
        ca, password_file, _files = self.build(tmp_path, names=names)

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["changed"] is False
        assert "already initialized" in result["msg"]

    def test_a_ca_without_defaults_json_is_complete(self, tmp_path, run_initialize):
        # defaults.json holds client defaults for the step CLI. step-ca is
        # started with ca.json and never reads it, so its absence is not a
        # broken CA - and the old rule's remedy, force, would have deleted a
        # working root key to restore a convenience file.
        names = tuple(name for name in CA_FILE_NAMES if name != "config/defaults.json")
        ca, password_file, _files = self.build(tmp_path, names=names)

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["changed"] is False

    def test_a_registration_authority_is_complete(self, tmp_path, run_initialize):
        # An RA proxies signing to an upstream CA and holds no local key
        # material, so it has two of the six files a standalone CA has. Under
        # the old rule it failed on every re-run - the half of #36 that this
        # change exists to finish.
        ca, password_file, _files = self.build(tmp_path, names=("config/ca.json", "config/defaults.json"))
        (ca / "config" / "ca.json").write_text(
            json.dumps(
                {
                    "address": ":443",
                    "authority": {
                        "type": "stepcas",
                        "certificateAuthority": "https://upstream.example.com",
                        "certificateIssuer": {"type": "jwk", "provisioner": "ra@example.com"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["changed"] is False
        assert result["management_mode"] == "config"

    def test_an_ssh_ca_missing_its_host_key_is_refused(self, tmp_path, run_initialize):
        # `--ssh` adds key material the filename list could not see at all, so
        # an SSH CA missing its host key used to read as complete.
        ca, password_file, _files = self.build(tmp_path)
        config = json.loads((ca / "config" / "ca.json").read_text(encoding="utf-8"))
        config["ssh"] = {"hostKey": "secrets/ssh_host_ca_key", "userKey": "secrets/ssh_user_ca_key"}
        (ca / "config" / "ca.json").write_text(json.dumps(config), encoding="utf-8")
        (ca / "secrets" / "ssh_user_ca_key").write_text("material", encoding="utf-8")

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        assert "ssh_host_ca_key" in result["msg"]
        assert "ssh_user_ca_key" not in result["msg"]

    def test_a_file_named_by_the_config_but_empty_is_refused(self, tmp_path, run_initialize):
        # Present is not usable. A zero-byte root certificate does not start a
        # CA, and os.path.exists alone would wave it through.
        ca, password_file, _files = self.build(tmp_path)
        (ca / "certs" / "root_ca.crt").write_text("", encoding="utf-8")

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        assert "root_ca.crt" in result["msg"]

    def test_an_absolute_path_in_the_config_is_honoured(self, tmp_path, run_initialize):
        # step writes absolute paths by default; the relative form only shows
        # up because the unit runs with WorkingDirectory set to the CA.
        elsewhere = tmp_path / "vault"
        elsewhere.mkdir()
        (elsewhere / "root.crt").write_text("material", encoding="utf-8")

        ca, password_file, _files = self.build(tmp_path)
        config = json.loads((ca / "config" / "ca.json").read_text(encoding="utf-8"))
        config["root"] = str(elsewhere / "root.crt")
        (ca / "config" / "ca.json").write_text(json.dumps(config), encoding="utf-8")

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert result["changed"] is False

    def test_the_refusal_says_what_force_would_destroy(self, tmp_path, run_initialize):
        # It is the way out the message itself offers, and it deletes the root
        # key: unrecoverable, and it invalidates every certificate ever issued.
        ca, password_file, _files = self.build(tmp_path, names=CA_FILE_NAMES[:3])

        result = run_initialize(ca, password_file, extra_env=stub_step_binary(tmp_path))

        assert "root key" in result["msg"]
        assert "cannot be recovered" in result["msg"]

    def test_force_still_reinitializes_a_complete_ca(self, tmp_path, run_initialize):
        # The escape hatch has to keep working now that the no-force path no
        # longer fails.
        ca, password_file, files = self.build(tmp_path)

        result = run_initialize(ca, password_file, force=True, extra_env=stub_step_binary(tmp_path))

        # The marker is what makes "the stubbed step" true rather than assumed:
        # this is the only other test that reaches step at all, so without it
        # the failure could equally be the real binary's.
        assert result["failed"] is True
        assert STEP_STUB_MARKER in result["msg"]
        assert [path for path in files if path.exists()] == []
