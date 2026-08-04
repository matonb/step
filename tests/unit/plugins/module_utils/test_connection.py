# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Tests for command assembly, admin credentials and mode detection.

The flag table is the most valuable thing here. Before it existed, one shared
flag set was appended to every step invocation, which sent flags to subcommands
that do not define them; step rejects those outright. The tests below pin each
of those defects so they cannot return.
"""

import json
import re
import subprocess

import pytest

from ansible_collections.matonb.step.plugins.module_utils.connection import (
    _COMMAND_FLAGS,
    _FLAG_NAMES,
    AdminCredentials,
    ManagementMode,
    StepConnection,
    configured_mode,
    observed_mode,
)

# Every subcommand the module can issue.
COMMANDS = [
    "ca provisioner add",
    "ca provisioner list",
    "ca provisioner remove",
    "ca provisioner update",
]

# A connection with every field populated, so a flag that leaks does so loudly.
FULL = StepConnection(
    admin=AdminCredentials(
        password_file="/secrets/pp",
        provisioner="admin",
        subject="step",
    ),
    ca_config="/etc/step-ca/config/ca.json",
    ca_path="/etc/step-ca",
    ca_url="https://ca.example.com",
    context="prod",
    root="/etc/step-ca/certs/root_ca.crt",
    run_as="step",
)


def flags_of(argv):
    """Return only the flag tokens of an argument vector."""
    return [token for token in argv if token.startswith("--")]


class TestFlagVocabulary:
    """The set of flags the module knows how to emit, asserted structurally.

    Asserting only on generated commands is not enough: a flag with no value
    set produces nothing, so such a test passes whether or not the flag exists.
    These assertions fail the moment the vocabulary itself changes.
    """

    def test_vocabulary_is_exactly_the_flags_step_defines(self):
        # Taken from the flag lists in smallstep/cli
        # command/ca/provisioner/{list,add,update,remove}.go. Adding an entry
        # here should mean checking it against that source first.
        assert _FLAG_NAMES == {
            "ca_config": "--ca-config",
            "ca_url": "--ca-url",
            "context": "--context",
            "root": "--root",
        }

    def test_each_command_accepts_exactly_the_flags_step_defines(self):
        # Asserted exactly, because a *removed* entry is as much a defect as an
        # invented one and produces no visible flag to assert against. Sourced
        # from the Flags lists in smallstep/cli
        # command/ca/provisioner/{list,add,update,remove}.go.
        assert _COMMAND_FLAGS == {
            "ca provisioner add": ("ca_config", "ca_url", "context", "root"),
            "ca provisioner list": ("ca_url", "context", "root"),
            "ca provisioner remove": ("ca_config", "ca_url", "context", "root"),
            "ca provisioner update": ("ca_config", "ca_url", "context", "root"),
        }

    @pytest.mark.parametrize("command", COMMANDS)
    def test_a_fully_populated_connection_emits_every_accepted_flag(self, command):
        # Complements the exact table above: proves the table is actually
        # applied, so dropping an entry shows up as a missing flag too.
        expected = {_FLAG_NAMES[name] for name in _COMMAND_FLAGS[command]}
        emitted = {flag for flag in flags_of(FULL.command(command, "name")) if not flag.startswith("--admin-")}
        assert emitted == expected

    def test_fingerprint_is_not_in_the_vocabulary(self):
        # No `step ca provisioner` subcommand accepts --fingerprint; it belongs
        # to `step ca bootstrap`/`step ca root`. The module still accepts the
        # deprecated option, so this pins that it never becomes a flag again.
        assert "fingerprint" not in _FLAG_NAMES
        assert "--fingerprint" not in _FLAG_NAMES.values()
        referenced = {name for names in _COMMAND_FLAGS.values() for name in names}
        assert "fingerprint" not in referenced

    def test_ca_root_is_not_in_the_vocabulary(self):
        # --ca-root is not a flag on any subcommand; the option is spelled
        # --root. Emitting --ca-root made step exit "flag provided but not
        # defined".
        assert "--ca-root" not in _FLAG_NAMES.values()

    def test_every_referenced_name_is_a_real_field_with_a_flag(self):
        # Catches a typo in the command table, which would otherwise silently
        # drop a flag via getattr returning nothing.
        referenced = {name for names in _COMMAND_FLAGS.values() for name in names}
        assert referenced <= set(_FLAG_NAMES)
        for name in referenced:
            assert hasattr(StepConnection(), name)

    def test_no_duration_flag_is_in_the_vocabulary(self):
        # x509 durations are claims, valid only on add/update, and belong to
        # the claims table rather than the connection.
        assert not [flag for flag in _FLAG_NAMES.values() if flag.startswith("--x509-")]


class TestFlagTable:
    """Only flags a subcommand actually defines may be emitted."""

    @pytest.mark.parametrize("command", COMMANDS)
    def test_fingerprint_is_never_emitted(self, command):
        assert "--fingerprint" not in flags_of(FULL.command(command, "name"))

    @pytest.mark.parametrize("command", COMMANDS)
    def test_root_uses_the_real_flag_name(self, command):
        # The flag is --root. --ca-root is not defined by any subcommand, so
        # step exits with "flag provided but not defined".
        emitted = flags_of(FULL.command(command, "name"))
        assert "--root" in emitted
        assert "--ca-root" not in emitted

    def test_list_rejects_ca_config(self):
        # `step ca provisioner list` defines only --ca-url, --root, --context.
        assert "--ca-config" not in flags_of(FULL.command("ca provisioner list"))

    @pytest.mark.parametrize("command", ["ca provisioner add", "ca provisioner remove", "ca provisioner update"])
    def test_mutating_commands_accept_ca_config(self, command):
        assert "--ca-config" in flags_of(FULL.command(command, "name"))

    @pytest.mark.parametrize("command", COMMANDS)
    def test_connection_layer_never_emits_duration_flags(self, command):
        # x509 durations belong to the claims table and are valid only on
        # add/update. They were previously sent to list and remove, and twice
        # to add.
        emitted = flags_of(FULL.command(command, "name"))
        assert not [flag for flag in emitted if flag.startswith("--x509-")]

    @pytest.mark.parametrize("command", COMMANDS)
    def test_no_flag_is_emitted_twice(self, command):
        emitted = flags_of(FULL.command(command, "name"))
        assert len(emitted) == len(set(emitted))

    def test_unknown_command_raises(self):
        with pytest.raises(ValueError, match=r"No flag definition"):
            FULL.command("ca provisioner frobnicate")

    def test_unset_values_emit_nothing(self):
        assert flags_of(StepConnection().command("ca provisioner list")) == []

    def test_positional_arguments_precede_flags(self):
        argv = FULL.command("ca provisioner add", "acme", "--type", "ACME")
        assert argv[:6] == ["step", "ca", "provisioner", "add", "acme", "--type"]


class TestAdminFlagPlacement:
    """Admin credentials go only to commands that authenticate."""

    def test_list_carries_no_admin_flags(self):
        # `list` reads the public /provisioners endpoint and needs no credentials.
        assert not [f for f in flags_of(FULL.command("ca provisioner list")) if f.startswith("--admin-")]

    @pytest.mark.parametrize("command", ["ca provisioner add", "ca provisioner remove", "ca provisioner update"])
    def test_mutating_commands_carry_admin_flags(self, command):
        emitted = flags_of(FULL.command(command, "name"))
        assert "--admin-subject" in emitted
        assert "--admin-provisioner" in emitted

    def test_password_file_uses_the_unambiguous_spelling(self):
        # On `add`, --password-file is the new provisioner's own key password
        # and is a different flag from --admin-password-file. Always using the
        # explicit spelling keeps the two from colliding.
        emitted = AdminCredentials(password_file="/secrets/pp").flags()
        assert "--admin-password-file" in emitted
        assert "--password-file" not in emitted


class TestAdminCredentialValidation:
    """Anything the step CLI is not given, it prompts for, which hangs a task."""

    def test_complete_just_in_time_credentials_accepted(self):
        AdminCredentials(password_file="/p", provisioner="admin", subject="step").validate()

    def test_certificate_pair_accepted(self):
        AdminCredentials(cert="/c.crt", key="/c.key").validate()

    @pytest.mark.parametrize(
        ("missing", "credentials"),
        [
            ("admin_subject", AdminCredentials(password_file="/p", provisioner="admin")),
            ("admin_provisioner", AdminCredentials(password_file="/p", subject="step")),
            ("admin_password_file", AdminCredentials(provisioner="admin", subject="step")),
        ],
    )
    def test_incomplete_just_in_time_credentials_rejected(self, missing, credentials):
        with pytest.raises(ValueError, match=re.escape(missing)):
            credentials.validate()

    @pytest.mark.parametrize(
        "credentials",
        [AdminCredentials(cert="/c.crt"), AdminCredentials(key="/c.key")],
    )
    def test_half_a_certificate_pair_rejected(self, credentials):
        with pytest.raises(ValueError, match=r"admin_cert.*admin_key"):
            credentials.validate()

    def test_password_file_with_certificate_rejected(self):
        # step loads the admin key with no password option, so an encrypted
        # admin key prompts regardless of which password flag is passed.
        with pytest.raises(ValueError, match=r"admin_password_file"):
            AdminCredentials(cert="/c.crt", key="/c.key", password_file="/p").validate()


class TestObservedMode:
    """step reports a ca.json rewrite; that is how the config path is detected."""

    MARKER = "Success! Your `step-ca` config has been updated. To pick up the new configuration SIGHUP"

    def test_marker_on_stderr_means_config_mode(self):
        # step writes this through ui.Println, which goes to stderr, so both
        # streams have to be scanned.
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=self.MARKER)
        assert observed_mode(result) is ManagementMode.CONFIG

    def test_marker_on_stdout_means_config_mode(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout=self.MARKER, stderr="")
        assert observed_mode(result) is ManagementMode.CONFIG

    def test_absent_marker_means_admin_mode(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}", stderr="")
        assert observed_mode(result) is ManagementMode.ADMIN

    def test_none_streams_are_tolerated(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout=None, stderr=None)
        assert observed_mode(result) is ManagementMode.ADMIN


class TestConfiguredMode:
    """authority.enableAdmin in ca.json is what step-ca itself reads."""

    def write_ca_json(self, tmp_path, authority):
        config = tmp_path / "config"
        config.mkdir(exist_ok=True)
        (config / "ca.json").write_text(json.dumps({"authority": authority}))
        return StepConnection(ca_path=str(tmp_path))

    def test_enable_admin_true(self, tmp_path):
        mode, error = configured_mode(self.write_ca_json(tmp_path, {"enableAdmin": True}))
        assert (mode, error) == (ManagementMode.ADMIN, None)

    def test_enable_admin_false(self, tmp_path):
        mode, error = configured_mode(self.write_ca_json(tmp_path, {"enableAdmin": False}))
        assert (mode, error) == (ManagementMode.CONFIG, None)

    def test_enable_admin_absent_defaults_to_config(self, tmp_path):
        mode, error = configured_mode(self.write_ca_json(tmp_path, {}))
        assert (mode, error) == (ManagementMode.CONFIG, None)

    def test_unreadable_config_reports_an_error(self, tmp_path):
        mode, error = configured_mode(StepConnection(ca_path=str(tmp_path / "absent")))
        assert mode is None
        assert error

    def test_no_path_at_all_reports_an_error(self):
        mode, error = configured_mode(StepConnection())
        assert mode is None
        assert "ca_path" in error

    def test_explicit_ca_config_wins_over_ca_path(self, tmp_path):
        elsewhere = tmp_path / "elsewhere.json"
        elsewhere.write_text(json.dumps({"authority": {"enableAdmin": True}}))
        connection = StepConnection(ca_path=str(tmp_path), ca_config=str(elsewhere))
        assert connection.config_file() == str(elsewhere)
        assert configured_mode(connection)[0] is ManagementMode.ADMIN


class TestEnvironment:
    def test_ca_path_becomes_steppath(self):
        assert StepConnection(ca_path="/etc/step-ca").env() == {"STEPPATH": "/etc/step-ca"}

    def test_no_ca_path_means_no_override(self):
        assert StepConnection().env() is None
