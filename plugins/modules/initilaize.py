"""Ansible module to initialize a Step CA instance."""

import os
import pathlib
import re
import select
import subprocess
import time
from typing import Tuple, Optional

from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = r"""
---
module: initialise
short_description: A brief description of your module
version_added: "1.0.0"
description:
  - Longer description of what your module does.
options:
  name:
    description:
      - The name to set.
    required: true
    type: str
author:
  - Your Name (@yourgithub)
"""

EXAMPLES = r"""
- name: Example usage of my module
  matonb.step.initialise:
    name: "example"
"""

RETURN = r"""
changed:
  description: Indicates if the module made changes
  returned: always
  type: bool
"""


class CommandTimeout(TimeoutError):
    """Exception raised when a command execution exceeds the timeout."""

    def __init__(self, message, stdout=None, stderr=None):
        """Initialize CommandTimeout with message and captured output.

        Parameters
        ----------
        message : str
            The error message
        stdout : str, optional
            The captured standard output
        stderr : str, optional
            The captured standard error
        """
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def run_command(command: str, timeout: int) -> Tuple[int, str, str]:
    """Execute a command using Popen with a timeout.

    Parameters
    ----------
    command : str
        The shell command to execute
    timeout : int
        The time limit in seconds before terminating the process

    Returns
    -------
    Tuple[int, str, str]
        A tuple containing return code, stdout, and stderr

    Raises
    ------
    CommandTimeout
        If the command execution exceeds the timeout
    """
    # Start the process
    with subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as process:
        start_time = time.time()

        # Prepare buffers for stdout and stderr
        stdout_lines = []
        stderr_lines = []
        killed = False

        while True:
            # Check if the process has completed
            if process.poll() is not None:
                break

            # Process readline functions are blocking if no data is available
            # Use select to check if there's data ready to be read
            rlist, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)

            for r in rlist:
                if r == process.stdout:
                    line = process.stdout.readline()
                    if line:
                        stdout_lines.append(line.decode("utf-8"))
                elif r == process.stderr:
                    line = process.stderr.readline()
                    if line:
                        stderr_lines.append(line.decode("utf-8"))

            # If timeout is exceeded, kill the process
            if time.time() - start_time > timeout:
                process.kill()
                killed = True
                break

            time.sleep(0.1)  # Avoid maxing out CPU usage

        if killed:
            raise CommandTimeout(
                f"Timed out after {timeout} seconds",
                "\n".join(stdout_lines),
                "\n".join(stderr_lines),
            )

        # If the process finished, read any remaining output
        stdout, stderr = process.communicate()
        # Decode the final output
        stdout_lines.append(stdout.decode("utf-8"))
        stderr_lines.append(stderr.decode("utf-8"))
        return process.returncode, "\n".join(stdout_lines), "\n".join(stderr_lines)


def run_step_ca_initialize(params, module) -> Optional[Tuple[int, str, str]]:
    """Run the step CA initialize command with provided parameters.

    Parameters
    ----------
    params : dict
        The Ansible module parameters
    module : AnsibleModule
        The Ansible module instance

    Returns
    -------
    Optional[Tuple[int, str, str]]
        A tuple containing return code, stdout, and stderr if successful
    """
    timeout = 15
    build_cmd = ["step", "ca", "init"]

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
                build_cmd.extend([f'--{key.replace("_", "-")}', value])

    # Add admin subject if remote management is enabled
    if params.get("remote_management") and params.get("admin_subject"):
        value = str(params["admin_subject"]).strip()
        if value:
            build_cmd.extend(["--admin-subject", value])

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
            build_cmd.append(flag)

    # Process DNS entries
    if params.get("dns"):
        for dns_entry in params["dns"]:
            build_cmd.extend(["--dns", dns_entry])

    cmd = " ".join(build_cmd)
    module.log("Executing: " + cmd)

    try:
        rc, stdout, stderr = run_command(cmd, timeout=timeout)
        return rc, stdout, stderr

    except CommandTimeout as exc:
        # Handle timeout with potential prompt detection
        prompt_pattern = r"(Please enter|Would you like to|\[y/n\])"
        if re.search(prompt_pattern, exc.stdout):
            module.fail_json(msg="Detected user input prompt")
        module.fail_json(
            msg=f"Step CA initialization timed out after {timeout} seconds."
        )

    except FileNotFoundError as exc:
        module.fail_json(msg=f"Command not found: {str(exc)}")

    except OSError as exc:
        # Handle OS-related errors
        module.fail_json(msg=f"OS error occurred: {str(exc)}")


def main():
    """Main entry point for the Ansible module."""
    module_args = {
        "acme": {"type": "bool"},
        "address": {
            "type": "str",
            "help": (
                "The address and port that the new CA will listen at " "e.g 0.0.0.0:443"
            ),
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
            "help": (
                "Will replace all existing certificates, secrets and " "configuration"
            ),
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
            "help": (
                "The path of an existing key file of the root " "certificate authority"
            ),
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
            "help": (
                "The path to the file containing the password to encrypt " "the keys"
            ),
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
            "help": (
                "The path to the file containing the password to encrypt "
                "the provisioner key"
            ),
            "no_log": True,
        },
        "ra": {"type": "str", "choices": ["StepCAS", "CloudCAS"]},
        "remote_management": {"type": "bool"},
        "root": {
            "type": "path",
            "help": (
                "The path of an existing PEM file to be used as the root "
                "certificate authority"
            ),
        },
        "ssh": {"type": "bool", "help": "Create keys to sign SSH certificates"},
        "with_ca_url": {"type": "str"},
    }

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    # Ensure STEPPATH is set when we invoke the step command
    step_path = module.params["path"]
    os.environ["STEPPATH"] = step_path

    if module.params["helm"]:
        module.fail_json(msg="Helm support is not yet implemented.")

    step_files = [
        f"{step_path}/certs/intermediate_ca.crt",
        f"{step_path}/certs/root_ca.crt",
        f"{step_path}/config/ca.json",
        f"{step_path}/config/defaults.json",
        f"{step_path}/secrets/intermediate_ca_key",
        f"{step_path}/secrets/root_ca_key",
    ]

    if module.params.get("force"):
        for file in step_files:
            pathlib.Path(file).unlink(missing_ok=True)
    else:
        file_found = next((file for file in step_files if os.path.exists(file)), None)
        if file_found:
            fail_msg = (
                f"Found {file_found}, cannot continue.\n"
                "Use force: true to override or ensure that none of the "
                "following files exist:\n" + "\n".join(step_files)
            )
            module.fail_json(msg=fail_msg)

    # Run step CA initialization
    return_code, _, stderr = run_step_ca_initialize(module.params, module)
    if return_code != 0:
        module.fail_json(msg=f"Step CA initialization failed: {stderr}")

    # Exit with appropriate message
    module.exit_json(changed=True, msg="Step CA initialization completed successfully.")


if __name__ == "__main__":
    main()
