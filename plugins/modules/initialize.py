"""Ansible module to initialize a Step CA instance."""

import os
import pathlib
import re
from typing import Dict, List, Optional, Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.matonb.step.plugins.module_utils.process import (
    run_command,
    CommandTimeout,
)


DOCUMENTATION = r"""
---
module: initialize
short_description: Initialize a Step CA instance
version_added: "1.0.0"
description:
  - This module initializes a new Step CA instance with the specified configuration.
  - It can create standalone, linked, or hosted deployments.
options:
  name:
    description:
      - The name of the new PKI.
    required: true
    type: str
  # Other options documented similarly...
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
"""

RETURN = r"""
changed:
  description: Indicates if the module made changes
  returned: always
  type: bool
"""


def get_argument_spec() -> Dict[str, Dict[str, Any]]:
    """Return the argument specification for the initialize module.

    Returns:
        Dict[str, Dict[str, Any]]: The module's argument specification
    """
    return {
        "acme": {"type": "bool"},
        "address": {
            "type": "str",
            "help": "The address and port that the new CA will listen at e.g 0.0.0.0:443",
        },
        "admin_subject": {
            "type": "str",
            "help": "The admin subject to use for generating admin credentials",
        },
        "authority": {"type": "str"},
        "context": {"type": "str"},
        "credentials_file": {"type": "path"},
        "deployment_type": {
            "type": "str",
            "choices": ["standalone", "linked", "hosted"],
            "default": "standalone",
            "help": (
                "The name of the deployment type to use. Options are:\n"
                "  standalone: An instance of step-ca that does not connect to "
                "any cloud services.\n"
                "              You manage authority keys and configuration "
                "yourself.\n"
                "              Choose standalone if you'd like to run step-ca "
                "yourself and do not\n"
                "              want cloud services or commercial support.\n"
                "\n"
                "  linked:     An instance of step-ca with locally managed "
                "keys that connects to your\n"
                "              Certificate Manager account for provisioner "
                "management, alerting, \n"
                "              reporting, revocation, and other managed "
                "services.\n"
                "              Choose linked if you'd like cloud services and "
                "support, but need to\n"
                "              control your authority's signing keys.\n"
                "\n"
                "  hosted:     A highly available, fully-managed instance of "
                "step-ca run by smallstep\n"
                "              just for you.\n"
                "              Choose hosted if you'd like cloud services and "
                "support"
            ),
        },
        "dns": {
            "type": "list",
            "elements": "str",
            "help": "The DNS name or IP addresses of the new CA",
        },
        "force": {
            "type": "bool",
            "default": False,
            "help": "Will replace all existing certificates, secrets and configuration",
        },
        "helm": {
            "type": "bool",
            "help": (
                "NOT IMPLEMENTED - Generates a Helm values YAML to be "
                "used with step-certificates chart"
            ),
        },
        "issuer": {"type": "str"},
        "issuer_fingerprint": {"type": "str"},
        "issuer_provisioner": {"type": "str"},
        "key": {
            "type": "path",
            "help": "The path of an existing key file of the root certificate authority",
        },
        "key_password_file": {
            "type": "path",
            "help": (
                "The path to the file containing the password to decrypt "
                "the existing root certificate key"
            ),
            "no_log": True,
        },
        "kms": {"type": "str", "choices": ["azurekms"]},
        "kms_intermediate": {"type": "str"},
        "kms_root": {"type": "str"},
        "kms_ssh_host": {"type": "str"},
        "kms_ssh_user": {
            "type": "str",
            "help": (
                "The kms URI used to generate the key used to sign SSH "
                "user certificates"
            ),
        },
        "name": {"type": "str", "required": True, "help": "The name of the new PKI"},
        "no_db": {"type": "bool"},
        "password_file": {
            "type": "path",
            "required": True,
            "help": "The path to the file containing the password to encrypt the keys",
            "no_log": True,
        },
        "path": {
            "type": "path",
            "help": (
                "Specifies the location where step stores its "
                "configuration, state, and Certificate Authority data"
            ),
            "required": True,
        },
        "pki": {
            "type": "bool",
            "help": "Generate only the PKI without the CA configuration",
        },
        "profile": {"type": "str"},
        "provisioner": {"type": "str", "default": "admin"},
        "provisioner_password_file": {
            "type": "path",
            "required": True,
            "help": "The path to the file containing the password to encrypt the provisioner key",
            "no_log": True,
        },
        "ra": {"type": "str", "choices": ["StepCAS", "CloudCAS"]},
        "remote_management": {"type": "bool"},
        "root": {
            "type": "path",
            "help": "The path of an existing PEM file to be used as the root certificate authority",
        },
        "ssh": {"type": "bool", "help": "Create keys to sign SSH certificates"},
        "with_ca_url": {"type": "str"},
    }


def build_initialize_command(params: Dict[str, Any]) -> List[str]:
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
                cmd.extend([f'--{key.replace("_", "-")}', value])

    # Add admin subject if remote management is enabled
    if params.get("remote_management") and params.get("admin_subject"):
        value = str(params["admin_subject"]).strip()
        if value:
            cmd.extend(["--admin-subject", value])

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


def check_existing_ca_files(step_path: str, force: bool = False) -> Optional[str]:
    """Check if CA files already exist and handle them based on the force parameter.

    Args:
        step_path: The path to the Step CA directory
        force: Whether to force deletion of existing files

    Returns:
        Optional[str]: Error message if files exist and force is False, None otherwise
    """
    step_files = [
        f"{step_path}/certs/intermediate_ca.crt",
        f"{step_path}/certs/root_ca.crt",
        f"{step_path}/config/ca.json",
        f"{step_path}/config/defaults.json",
        f"{step_path}/secrets/intermediate_ca_key",
        f"{step_path}/secrets/root_ca_key",
    ]

    if force:
        for file in step_files:
            pathlib.Path(file).unlink(missing_ok=True)
        return None

    file_found = next((file for file in step_files if os.path.exists(file)), None)
    if file_found:
        return (
            f"Found {file_found}, cannot continue.\n"
            "Use force: true to override or ensure that none of the "
            "following files exist:\n" + "\n".join(step_files)
        )

    return None


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
            debug=True,
            check=False,  # We'll handle the return code ourselves
        )

        if result.returncode != 0:
            module.fail_json(msg=f"Step CA initialization failed: {result.stderr}")

        return

    except CommandTimeout as exc:
        # Handle timeout with potential prompt detection
        prompt_pattern = r"(Please enter|Would you like to|\[y/n\])"
        if re.search(prompt_pattern, exc.stdout or ""):
            module.fail_json(msg="Detected user input prompt")
        module.fail_json(
            msg=f"Step CA initialization timed out after {timeout} seconds."
        )

    except FileNotFoundError as exc:
        module.fail_json(msg=f"Command not found: {str(exc)}")

    except OSError as exc:
        # Handle OS-related errors
        module.fail_json(msg=f"OS error occurred: {str(exc)}")


def main() -> None:
    """Main entry point for the Ansible module."""
    module = AnsibleModule(argument_spec=get_argument_spec(), supports_check_mode=True)

    # Ensure STEPPATH is set when we invoke the step command
    step_path = module.params["path"]
    os.environ["STEPPATH"] = step_path

    if module.params["helm"]:
        module.fail_json(msg="Helm support is not yet implemented.")

    # Check for existing CA files
    error_msg = check_existing_ca_files(
        step_path, force=module.params.get("force", False)
    )
    if error_msg:
        module.fail_json(msg=error_msg)

    # In check mode, report that changes would be made
    if module.check_mode:
        module.exit_json(changed=True, msg="Check mode: Step CA would be initialized")

    # Run step CA initialization
    try:
        run_step_ca_initialize(module)
        # Exit with success message
        module.exit_json(
            changed=True, msg="Step CA initialization completed successfully."
        )
    except Exception as exc:
        module.fail_json(msg=f"Unexpected error: {str(exc)}")


if __name__ == "__main__":
    main()
