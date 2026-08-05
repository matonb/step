# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Initialize a Step CA instance."""

DOCUMENTATION = r"""
---
module: initialize
short_description: Initialize a Step CA instance
version_added: "1.0.0"
description:
  - This module initializes a new Step CA instance with the specified configuration.
  - It can create standalone, linked, or hosted deployments.
  - >-
    Passing C(remote_management) enables the Admin API, which stores
    provisioners in the CA database instead of C(ca.json) and creates a super
    administrator. It requires a database, so it cannot be combined with
    C(no_db), and C(admin_subject) is only valid alongside it.
options:
  acme:
    description:
      - Create a default ACME provisioner.
      - Requires a database, so it cannot be combined with I(no_db).
    required: false
    type: bool
  address:
    description:
      - The address and port the new CA will listen on, for example C(0.0.0.0:443).
    required: false
    type: str
  admin_subject:
    description:
      - Subject of the first super administrator. Defaults to C(step).
      - Only valid when I(remote_management) is enabled.
    required: false
    type: str
  authority:
    description:
      - The name that will serve as the authority name for the context.
    required: false
    type: str
  context:
    description:
      - The name of the context for the new authority.
    required: false
    type: str
  credentials_file:
    description:
      - Path to the registration authority credentials file.
    required: false
    type: path
  debug:
    description:
      - If true, prints the step command to stderr before execution for debugging purposes.
    required: false
    type: bool
    default: false
  deployment_type:
    description:
      - The deployment type to use.
      - >-
        C(standalone) is an instance of step-ca that does not connect to any
        cloud services; you manage the authority keys and configuration
        yourself.
      - >-
        C(linked) is an instance with locally managed keys that connects to a
        Certificate Manager account for provisioner management, alerting,
        reporting and revocation.
      - C(hosted) is a fully managed instance run by smallstep.
    required: false
    type: str
    choices: ['standalone', 'linked', 'hosted']
    default: standalone
  dns:
    description:
      - The DNS names or IP addresses of the new CA.
    required: false
    type: list
    elements: str
  force:
    description:
      - Replace any existing certificates, secrets and configuration found at I(path).
      - Without this the module fails rather than overwrite an existing CA.
      - >-
        This deletes C(secrets/root_ca_key), which cannot be regenerated:
        everything the old CA issued becomes unverifiable and the trust chain
        has to be rebuilt from scratch. Nothing is backed up. Under C(--check)
        the deletion is reported but not performed.
    required: false
    type: bool
    default: false
  helm:
    description:
      - Generate a Helm values YAML to be used with the step-certificates chart.
      - Not implemented; supplying it fails the task.
    required: false
    type: bool
  issuer:
    description:
      - The registration authority issuer URL, used with I(ra).
    required: false
    type: str
  issuer_fingerprint:
    description:
      - The fingerprint of the registration authority issuer CA certificate.
    required: false
    type: str
  issuer_provisioner:
    description:
      - The name of the provisioner used with the registration authority issuer.
    required: false
    type: str
  key:
    description:
      - Path to an existing private key file for the root certificate authority.
      - Must be supplied together with I(root).
    required: false
    type: path
  key_password_file:
    description:
      - Path to the file containing the password that decrypts the existing root certificate key.
    required: false
    type: path
  kms:
    description:
      - The key management service to use for generating and storing keys.
    required: false
    type: str
    choices: ['azurekms']
  kms_intermediate:
    description:
      - The KMS URI used to generate the intermediate certificate key.
    required: false
    type: str
  kms_root:
    description:
      - The KMS URI used to generate the root certificate key.
    required: false
    type: str
  kms_ssh_host:
    description:
      - The KMS URI used to generate the key that signs SSH host certificates.
    required: false
    type: str
  kms_ssh_user:
    description:
      - The KMS URI used to generate the key that signs SSH user certificates.
    required: false
    type: str
  name:
    description:
      - The name of the new PKI.
    required: true
    type: str
  no_db:
    description:
      - Initialise the CA without a database.
      - Incompatible with I(remote_management) and I(acme), which both require one.
    required: false
    type: bool
  password_file:
    description:
      - Path to the file containing the password used to encrypt the keys.
    required: true
    type: path
  path:
    description:
      - Where step stores its configuration, state and Certificate Authority data.
      - Sets the STEPPATH environment variable for the step command.
    required: true
    type: path
  pki:
    description:
      - Generate only the PKI, without the CA configuration.
    required: false
    type: bool
  profile:
    description:
      - The name that will serve as the profile name for the context.
    required: false
    type: str
  provisioner:
    description:
      - The name of the first provisioner.
    required: false
    type: str
    default: admin
  provisioner_password_file:
    description:
      - Path to the file containing the password used to encrypt the provisioner key.
    required: true
    type: path
  ra:
    description:
      - The type of registration authority to create.
    required: false
    type: str
    choices: ['StepCAS', 'CloudCAS']
  remote_management:
    description:
      - Enable the Admin API so provisioners are managed remotely rather than in C(ca.json).
      - Requires a database, so it cannot be combined with I(no_db).
    required: false
    type: bool
  root:
    description:
      - Path to an existing PEM file to be used as the root certificate authority.
      - Must be supplied together with I(key).
    required: false
    type: path
  ssh:
    description:
      - Create keys for signing SSH certificates.
    required: false
    type: bool
  with_ca_url:
    description:
      - The URI of the Step Certificate Authority to write into C(defaults.json).
    required: false
    type: str
author:
  - Brett Maton (@matonb)
"""

EXAMPLES = r"""
- name: Initialize a standalone Step CA
  matonb.step.initialize:
    name: "My CA"
    path: "/etc/step-ca"
    password_file: "/path/to/password"
    provisioner_password_file: "/path/to/provisioner_password"

- name: Initialize a Step CA with remote management (admin mode)
  matonb.step.initialize:
    admin_subject: step
    name: "My CA"
    path: "/etc/step-ca"
    password_file: "/path/to/password"
    provisioner_password_file: "/path/to/provisioner_password"
    remote_management: true
"""

RETURN = r"""
admin_subject:
  description: Subject of the super administrator, or null when remote management is disabled.
  returned: success
  type: str

changed:
  description: Indicates if the module made changes
  returned: always
  type: bool

management_mode:
  description: How provisioners will be managed, either C(admin) or C(config).
  returned: success
  type: str
"""

import os
import pathlib
import re
from typing import Any

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.matonb.step.plugins.module_utils.process import (
    CommandTimeoutError,
    run_command,
)

# The files `step ca init` creates. Their presence is what makes a directory an
# initialised CA, and what `force` deletes.
CA_FILE_NAMES = (
    "certs/intermediate_ca.crt",
    "certs/root_ca.crt",
    "config/ca.json",
    "config/defaults.json",
    "secrets/intermediate_ca_key",
    "secrets/root_ca_key",
)


def get_argument_spec() -> dict[str, dict[str, Any]]:
    """Return the argument specification for the initialize module.

    Option descriptions live in DOCUMENTATION, which is the only place Ansible
    surfaces them to users.

    Returns:
        Dict[str, Dict[str, Any]]: The module's argument specification
    """
    return {
        "acme": {"type": "bool"},
        "address": {"type": "str"},
        "admin_subject": {"type": "str"},
        "authority": {"type": "str"},
        "context": {"type": "str"},
        "credentials_file": {"type": "path"},
        "debug": {"type": "bool", "default": False},
        "deployment_type": {
            "type": "str",
            "choices": ["standalone", "linked", "hosted"],
            "default": "standalone",
        },
        "dns": {"type": "list", "elements": "str"},
        "force": {"type": "bool", "default": False},
        "helm": {"type": "bool"},
        "issuer": {"type": "str"},
        "issuer_fingerprint": {"type": "str"},
        "issuer_provisioner": {"type": "str"},
        "key": {"type": "path"},
        "key_password_file": {"type": "path", "no_log": False},
        "kms": {"type": "str", "choices": ["azurekms"]},
        "kms_intermediate": {"type": "str"},
        "kms_root": {"type": "str"},
        "kms_ssh_host": {"type": "str"},
        "kms_ssh_user": {"type": "str"},
        "name": {"type": "str", "required": True},
        "no_db": {"type": "bool"},
        # The *_password_file options name a file rather than hold a secret;
        # no_log is set explicitly so Ansible's name-based heuristic does not
        # flag them.
        "password_file": {"type": "path", "required": True, "no_log": False},
        "path": {"type": "path", "required": True},
        "pki": {"type": "bool"},
        "profile": {"type": "str"},
        "provisioner": {"type": "str", "default": "admin"},
        "provisioner_password_file": {"type": "path", "required": True, "no_log": False},
        "ra": {"type": "str", "choices": ["StepCAS", "CloudCAS"]},
        "remote_management": {"type": "bool"},
        "root": {"type": "path"},
        "ssh": {"type": "bool"},
        "with_ca_url": {"type": "str"},
    }


def build_initialize_command(params: dict[str, Any]) -> list[str]:
    """Build the step CA initialize command from module parameters.

    Args:
        params: The module parameters

    Returns:
        List[str]: The command as a list of arguments
    """
    cmd = ["step", "ca", "init"]

    # Process string parameters with values
    param_keys = [
        "address",
        "admin_subject",
        "authority",
        "context",
        "credentials_file",
        "deployment_type",
        "issuer",
        "issuer_fingerprint",
        "issuer_provisioner",
        "key",
        "key_password_file",
        "kms",
        "kms_intermediate",
        "kms_root",
        "kms_ssh_host",
        "kms_ssh_user",
        "name",
        "password_file",
        "profile",
        "provisioner",
        "provisioner_password_file",
        "ra",
        "root",
        "with_ca_url",
    ]

    # Add parameters with values
    for key in param_keys:
        if params.get(key):
            value = str(params[key]).strip()
            if value:
                cmd.extend([f"--{key.replace('_', '-')}", value])

    # Add boolean flag parameters
    boolean_flags = {
        "acme": "--acme",
        "no_db": "--no-db",
        "pki": "--pki",
        "remote_management": "--remote-management",
        "ssh": "--ssh",
    }

    for param, flag in boolean_flags.items():
        if params.get(param):
            cmd.append(flag)

    # Process DNS entries
    if params.get("dns"):
        for dns_entry in params["dns"]:
            cmd.extend(["--dns", dns_entry])

    return cmd


def ca_file_paths(step_path: str) -> list[str]:
    """Return the full paths of the files C(step ca init) creates.

    Args:
        step_path: The path to the Step CA directory.

    Returns:
        List[str]: The paths, in a stable order.
    """
    return [os.path.join(step_path, name) for name in CA_FILE_NAMES]


def find_existing_ca_files(step_path: str) -> list[str]:
    """Report which of the CA's files are already present.

    Detection only. Deletion is :func:`remove_ca_files`, kept separate so that
    the caller can decide - the two used to be one function, which meant asking
    whether a CA existed destroyed it.

    Args:
        step_path: The path to the Step CA directory.

    Returns:
        List[str]: The paths that exist, empty if the directory holds no CA.
    """
    return [path for path in ca_file_paths(step_path) if os.path.exists(path)]


def remove_ca_files(step_path: str) -> None:
    """Delete the files C(step ca init) creates.

    Irreversible: C(secrets/root_ca_key) cannot be regenerated, and everything
    the CA ever issued becomes unverifiable without it. Only ever call this
    when C(force) was asked for and the module is not in check mode.

    Args:
        step_path: The path to the Step CA directory.
    """
    for path in ca_file_paths(step_path):
        pathlib.Path(path).unlink(missing_ok=True)


def validate_admin_options(module: AnsibleModule) -> None:
    """Reject option combinations that step itself rejects.

    Checking here means the task fails with a clear message instead of
    spawning step only to have it exit non-zero.

    Args:
        module: The Ansible module instance
    """
    if module.params.get("remote_management") and module.params.get("no_db"):
        module.fail_json(msg="'remote_management' requires a database and cannot be combined with 'no_db'.")

    if module.params.get("admin_subject") and not module.params.get("remote_management"):
        module.fail_json(msg="'admin_subject' is only supported when 'remote_management' is enabled.")


def run_step_ca_initialize(module: AnsibleModule) -> None:
    """Run the step CA initialize command with provided parameters.

    Args:
        module: The Ansible module instance

    Raises:
        RuntimeError: If the initialization fails
    """
    timeout = 15
    command = build_initialize_command(module.params)
    module.log("Executing: " + " ".join(command))

    try:
        result = run_command(
            command=command,
            timeout=timeout,
            logger=module.log if module.params.get("debug") else None,
            env_vars={"STEPPATH": module.params["path"]},
            check=False,  # We'll handle the return code ourselves
        )

        if result.returncode != 0:
            module.fail_json(msg=f"Step CA initialization failed: {result.stderr}")

        return

    except CommandTimeoutError as exc:
        # Handle timeout with potential prompt detection
        prompt_pattern = r"(Please enter|Would you like to|\[y/n\])"
        if re.search(prompt_pattern, exc.stdout or ""):
            module.fail_json(msg="Detected user input prompt")
        module.fail_json(msg=f"Step CA initialization timed out after {timeout} seconds.")

    except FileNotFoundError as exc:
        module.fail_json(msg=f"Command not found: {str(exc)}")

    except OSError as exc:
        # Handle OS-related errors
        module.fail_json(msg=f"OS error occurred: {str(exc)}")


def main() -> None:
    """Run the Ansible module."""
    module = AnsibleModule(argument_spec=get_argument_spec(), supports_check_mode=True)

    step_path = module.params["path"]

    if module.params["helm"]:
        module.fail_json(msg="Helm support is not yet implemented.")

    validate_admin_options(module)

    # Provisioners of a remote-management CA live in the CA database and are
    # managed through the Admin API; every other CA keeps them in ca.json.
    management_mode = "admin" if module.params.get("remote_management") else "config"
    admin_subject = module.params.get("admin_subject") or ("step" if management_mode == "admin" else None)

    existing = find_existing_ca_files(step_path)
    if existing and not module.params["force"]:
        module.fail_json(
            msg=(
                f"Found {existing[0]}, cannot continue.\n"
                "Use force: true to override or ensure that none of the "
                "following files exist:\n" + "\n".join(ca_file_paths(step_path))
            )
        )

    # Nothing above this line modifies anything, and nothing below it may run
    # under check mode: with force: true the next step deletes the CA's private
    # keys. Detection and deletion used to be one call placed above this guard,
    # so a --check run destroyed the CA and then reported what it "would" do.
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg=(
                "Check mode: the existing CA would be deleted and Step CA reinitialized"
                if existing
                else "Check mode: Step CA would be initialized"
            ),
            admin_subject=admin_subject,
            management_mode=management_mode,
        )

    # Keyed on force rather than on what was detected: find_existing_ca_files
    # uses os.path.exists, which is False for a symlink whose target is gone,
    # and step would then meet a directory it expected to be empty. Unreachable
    # without force, because the fail_json above has already returned.
    if module.params["force"]:
        remove_ca_files(step_path)

    # Run step CA initialization
    try:
        run_step_ca_initialize(module)
        # Exit with success message
        module.exit_json(
            changed=True,
            msg="Step CA initialization completed successfully.",
            admin_subject=admin_subject,
            management_mode=management_mode,
        )
    except Exception as exc:
        module.fail_json(msg=f"Unexpected error: {str(exc)}")


if __name__ == "__main__":
    main()
