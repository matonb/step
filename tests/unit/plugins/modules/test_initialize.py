# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for building the `step ca init` command and its option guards."""

import json
import os
import subprocess
import sys

import pytest

from ansible_collections.matonb.step.plugins.modules import initialize
from ansible_collections.matonb.step.plugins.modules.initialize import (
    CA_FILE_NAMES,
    build_initialize_command,
    find_existing_ca_files,
    get_argument_spec,
    remove_ca_files,
    validate_admin_options,
)


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


def build_ca(tmp_path):
    """Populate a directory with every file `step ca init` creates."""
    for name in CA_FILE_NAMES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"PRECIOUS-{name}", encoding="utf-8")
    return [tmp_path / name for name in CA_FILE_NAMES]


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
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "step"
    stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    return {"PATH": os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])}


def run_module(step_path, password_file, extra_env=None, **requested):
    """Execute the module the way Ansible does and return its result.

    Driving main() is the only way to catch #35: the defect was purely the
    order of two calls, so every test of the functions themselves passed with
    it in place.
    """
    args = json.dumps(
        {
            "ANSIBLE_MODULE_ARGS": {
                "name": "Test CA",
                "path": str(step_path),
                "password_file": str(password_file),
                "provisioner_password_file": str(password_file),
                **requested,
            }
        }
    )
    collection_paths = [path for path in sys.path if path and os.path.isdir(os.path.join(path, "ansible_collections"))]
    completed = subprocess.run(
        [sys.executable, initialize.__file__],
        input=args,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(collection_paths), **(extra_env or {})},
    )
    if not completed.stdout:
        raise AssertionError(f"module produced no result (exit {completed.returncode}):\n{completed.stderr}")
    return json.loads(completed.stdout)


class TestCheckModeNeverDeletes:
    """Regression tests for #35.

    `check_existing_ca_files()` both detected and deleted, and ran before the
    check-mode guard, so `--check` with `force: true` unlinked the CA's private
    keys and then reported what it "would" do. The root CA key cannot be
    regenerated.
    """

    def test_check_mode_with_force_leaves_an_existing_ca_intact(self, tmp_path):
        ca = tmp_path / "ca"
        ca.mkdir()
        files = build_ca(ca)
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_module(ca, password_file, force=True, _ansible_check_mode=True)

        assert result["changed"] is True
        assert [path.name for path in files if not path.exists()] == []
        assert all(path.read_text(encoding="utf-8").startswith("PRECIOUS-") for path in files)

    def test_check_mode_with_force_says_it_would_delete(self, tmp_path):
        # Reporting `changed` is not enough: an operator running --check to find
        # out what force does needs to be told the CA goes away.
        ca = tmp_path / "ca"
        ca.mkdir()
        build_ca(ca)
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_module(ca, password_file, force=True, _ansible_check_mode=True)

        assert "deleted" in result["msg"]

    def test_check_mode_without_force_still_refuses_and_deletes_nothing(self, tmp_path):
        ca = tmp_path / "ca"
        ca.mkdir()
        files = build_ca(ca)
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_module(ca, password_file, _ansible_check_mode=True)

        assert "cannot continue" in result["msg"]
        assert all(path.exists() for path in files)

    def test_check_mode_on_an_empty_directory_creates_nothing(self, tmp_path):
        ca = tmp_path / "ca"
        ca.mkdir()
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_module(ca, password_file, _ansible_check_mode=True)

        assert result["changed"] is True
        assert list(ca.iterdir()) == []


class TestForceOutsideCheckMode:
    def test_force_still_removes_an_existing_ca(self, tmp_path):
        # The other half of the fix: moving the deletion below the check-mode
        # guard must not stop it happening on a real run. The stubbed step
        # fails, so nothing is recreated and the deletion is observable.
        ca = tmp_path / "ca"
        ca.mkdir()
        files = build_ca(ca)
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_module(ca, password_file, force=True, extra_env=stub_step_binary(tmp_path))

        assert result["failed"] is True
        assert [path for path in files if path.exists()] == []

    def test_without_force_a_real_run_refuses_and_deletes_nothing(self, tmp_path):
        # The production path. Check mode is covered above; if the guard on the
        # no-force branch were weakened, only this test would notice - and this
        # is the run that would actually overwrite a CA nobody asked to replace.
        ca = tmp_path / "ca"
        ca.mkdir()
        files = build_ca(ca)
        password_file = tmp_path / "pw"
        password_file.write_text("pw", encoding="utf-8")

        result = run_module(ca, password_file, extra_env=stub_step_binary(tmp_path))

        # The message matters, not just the failure: with the guard removed the
        # module reaches step, which also fails, so asserting `failed` alone
        # passes either way and proves nothing.
        assert "cannot continue" in result["msg"]
        assert all(path.read_text(encoding="utf-8").startswith("PRECIOUS-") for path in files)
