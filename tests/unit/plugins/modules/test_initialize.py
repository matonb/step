# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for building the `step ca init` command and its option guards."""

import pytest

from ansible_collections.matonb.step.plugins.modules.initialize import (
    build_initialize_command,
    check_existing_ca_files,
    get_argument_spec,
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


class TestCheckExistingCaFiles:
    def test_empty_directory_is_acceptable(self, tmp_path):
        assert check_existing_ca_files(str(tmp_path)) is None

    def test_an_existing_ca_is_reported(self, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "ca.json").write_text("{}")
        message = check_existing_ca_files(str(tmp_path))
        assert message is not None
        assert "ca.json" in message

    def test_force_clears_the_way(self, tmp_path):
        (tmp_path / "config").mkdir()
        target = tmp_path / "config" / "ca.json"
        target.write_text("{}")
        assert check_existing_ca_files(str(tmp_path), force=True) is None
        assert not target.exists()
