# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Connection details and credentials for step CLI invocations.

A step-ca deployment stores its provisioners in one of two places, and the step
CLI decides which by probing the CA rather than by taking a flag:

- **Config mode** - provisioners live in C(ca.json). The CLI edits the file in
  place and the CA only picks the change up on SIGHUP or restart.
- **Admin mode** - the CA was initialised with C(--remote-management), so
  provisioners live in the CA database and are changed through the
  authenticated Admin API. Changes take effect immediately.

Because the mode is detected, a CA that is simply not running looks exactly
like a config-mode CA to the step CLI, which then rewrites a C(ca.json) that
the running CA will never read. :func:`observed_mode` exists so callers can
detect that and fail instead of silently corrupting the configuration.

This module owns three things: where the CA is (:class:`StepConnection`), how
to authenticate to its Admin API (:class:`AdminCredentials`), and which flags
each step subcommand actually accepts.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from subprocess import CompletedProcess
from typing import Optional

from .process import run_command
from .utils import read_json_file

# Connection attribute -> step CLI flag.
_FLAG_NAMES = {
    "ca_config": "--ca-config",
    "ca_url": "--ca-url",
    "context": "--context",
    "root": "--root",
}

# Credential attribute -> step CLI flag. `--admin-password-file` is spelled the
# same on every subcommand that takes it. On `add` it is distinct from
# `--password-file` (which carries the new provisioner's own key password);
# elsewhere the two are aliases of one flag. Always emitting the explicit
# spelling keeps the two passwords from colliding.
_ADMIN_FLAG_NAMES = {
    "cert": "--admin-cert",
    "key": "--admin-key",
    "password_file": "--admin-password-file",
    "provisioner": "--admin-provisioner",
    "subject": "--admin-subject",
}

# Connection flags each step command accepts, taken from the flag lists in
# smallstep/cli command/ca/provisioner/{list,add,update,remove}.go. Sending a
# flag a subcommand does not define is a hard usage error, so commands are
# built from this table rather than from one shared flag set.
_COMMAND_FLAGS = {
    "ca provisioner add": ("ca_config", "ca_url", "context", "root"),
    "ca provisioner list": ("ca_url", "context", "root"),
    "ca provisioner remove": ("ca_config", "ca_url", "context", "root"),
    "ca provisioner update": ("ca_config", "ca_url", "context", "root"),
}

# Commands that mutate the CA and therefore accept admin credentials. `list`
# reads the public /provisioners endpoint and needs none.
_ADMIN_COMMANDS = frozenset(
    {
        "ca provisioner add",
        "ca provisioner remove",
        "ca provisioner update",
    }
)

# Printed by the step CLI only after it has rewritten ca.json
# (command/ca/provisioner/caConfigClient.go), which makes it a reliable signal
# that the command took the config-mode path.
_CONFIG_MODE_MARKER = "config has been updated"


class ManagementMode(str, Enum):
    """How provisioner changes reach the CA."""

    ADMIN = "admin"
    CONFIG = "config"


@dataclass(frozen=True)
class AdminCredentials:
    """Credentials for the step-ca Admin API.

    The step CLI accepts two forms. Either an existing admin certificate and
    key are supplied, or the CLI mints a short-lived credential by signing a
    certificate for C(subject) using C(provisioner). The second form is what
    C(step ca init --remote-management) sets up.
    """

    cert: Optional[str] = None
    key: Optional[str] = None
    password_file: Optional[str] = None
    provisioner: Optional[str] = None
    subject: Optional[str] = None

    @property
    def uses_certificate(self) -> bool:
        """Whether an existing admin certificate is being presented.

        Returns:
            bool: True if a certificate or key was supplied.
        """
        return bool(self.cert or self.key)

    def validate(self) -> None:
        """Reject combinations that would make the step CLI prompt.

        Every missing admin input makes the CLI ask for it interactively, which
        an Ansible module experiences as a hang rather than a failure. Checking
        up front turns that into an immediate, actionable error.

        Raises:
            ValueError: If the credentials are incomplete or unusable.
        """
        if self.uses_certificate:
            if not (self.cert and self.key):
                raise ValueError("Both 'admin_cert' and 'admin_key' are required to authenticate with a certificate.")
            if self.password_file:
                # step loads the admin key with pemutil.Read() and no password
                # option (utils/cautils/client.go), so an encrypted admin key
                # prompts no matter which password flag is passed. On `add` the
                # flag it would consult, --password-file, is in any case the
                # new provisioner's own key password.
                raise ValueError(
                    "'admin_password_file' cannot be combined with 'admin_cert': step cannot decrypt an "
                    "admin key from it and would prompt. Supply an unencrypted 'admin_key', or "
                    "authenticate with 'admin_subject' and 'admin_provisioner' instead."
                )
            return

        missing = [
            name
            for name, value in (
                ("admin_password_file", self.password_file),
                ("admin_provisioner", self.provisioner),
                ("admin_subject", self.subject),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"Admin mode requires {', '.join(missing)}. The step CLI prompts for anything it is not "
                "given, which hangs the task. Alternatively supply 'admin_cert' and 'admin_key'."
            )

    def flags(self) -> list[str]:
        """Render the credentials as step CLI flags.

        Returns:
            List[str]: The C(--admin-*) flags for the supplied values.
        """
        flags: list[str] = []
        for name, flag in sorted(_ADMIN_FLAG_NAMES.items()):
            value = getattr(self, name)
            if value:
                flags.extend([flag, value])
        return flags


@dataclass(frozen=True)
class StepConnection:
    """Where a CA is, and how to reach and authenticate to it."""

    admin: Optional[AdminCredentials] = None
    ca_config: Optional[str] = None
    ca_path: Optional[str] = None
    ca_url: Optional[str] = None
    context: Optional[str] = None
    logger: Optional[Callable[[str], None]] = None
    root: Optional[str] = None
    run_as: Optional[str] = None

    def env(self) -> Optional[dict[str, str]]:
        """Build the environment overrides for step invocations.

        Returns:
            dict or None: A STEPPATH override, or None when C(ca_path) is unset.
        """
        return {"STEPPATH": self.ca_path} if self.ca_path else None

    def config_file(self) -> Optional[str]:
        """Resolve the path to the CA's C(ca.json).

        Returns:
            str or None: The explicit C(ca_config), else the conventional
            location under C(ca_path), else None.
        """
        if self.ca_config:
            return self.ca_config
        return os.path.join(self.ca_path, "config", "ca.json") if self.ca_path else None

    def command(self, command: str, *args: str) -> list[str]:
        """Build a step command with only the flags that command accepts.

        Args:
            command: A key of C(_COMMAND_FLAGS), e.g. "ca provisioner add".
            *args: Positional arguments and command-specific flags.

        Returns:
            List[str]: The full argument vector.

        Raises:
            ValueError: If the command has no entry in the flag table.
        """
        accepted = _COMMAND_FLAGS.get(command)
        if accepted is None:
            raise ValueError(f"No flag definition for step command: {command!r}")

        argv = ["step", *command.split(), *args]
        for name in accepted:
            value = getattr(self, name)
            if value:
                argv.extend([_FLAG_NAMES[name], value])

        if self.admin and command in _ADMIN_COMMANDS:
            argv.extend(self.admin.flags())

        return argv

    def run(self, argv: list[str], *, timeout: Optional[float] = None) -> CompletedProcess:
        """Execute a step command.

        Args:
            argv: The argument vector, normally from :meth:`command`.
            timeout: Seconds to wait before giving up. A timeout is how an
                unexpected interactive prompt surfaces.

        Returns:
            subprocess.CompletedProcess: The completed command.
        """
        return run_command(
            argv,
            username=self.run_as,
            env_vars=self.env(),
            logger=self.logger,
            timeout=timeout,
        )


def configured_mode(connection: StepConnection) -> tuple[Optional[ManagementMode], Optional[str]]:
    """Determine the management mode from the CA's own configuration.

    C(authority.enableAdmin) in C(ca.json) is what step-ca itself reads, so it
    is authoritative and needs no network access.

    Args:
        connection: The connection identifying the CA.

    Returns:
        Tuple of the detected mode (or None) and an error message (or None).
    """
    config_file = connection.config_file()
    if not config_file:
        return None, "Cannot determine the management mode without 'ca_path' or 'ca_config'."

    config, error = read_json_file(config_file)
    if error:
        return None, error

    enabled = config.get("authority", {}).get("enableAdmin", False)
    return (ManagementMode.ADMIN if enabled else ManagementMode.CONFIG), None


def observed_mode(result: CompletedProcess) -> ManagementMode:
    """Classify the mode a completed step command actually used.

    Args:
        result: A completed mutating step command.

    Returns:
        ManagementMode: CONFIG if step reported rewriting C(ca.json),
        otherwise ADMIN.
    """
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    return ManagementMode.CONFIG if _CONFIG_MODE_MARKER in output else ManagementMode.ADMIN
