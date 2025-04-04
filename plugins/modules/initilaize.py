import os
import pathlib
import re
import select
import subprocess
import time
from typing import Tuple

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
    def __init__(self, message, stdout=None, stderr=None):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def run_command(command: str, timeout: int) -> Tuple[str, str, int]:
    """
    Executes a command using Popen with a timeout, capturing stdout and stderr.

    Args:
        command (str): The shell command to execute.
        timeout (int): The time limit in seconds before terminating the process.

    Returns:
        Tuple[str, str, int]: A tuple containing stdout, stderr, and the exit code.

    Raises:
        TimeoutError: If the command execution exceeds the timeout.
    """
    # Start the process
    process = subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    start_time = time.time()

    # Prepare buffers for stdout and stderr
    stdout_lines = []
    stderr_lines = []
    killed = False

    while True:
        # Check if the process has completed
        if process.poll() is not None:
            break

        # The process readline functions are blocking if no data is available
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


def run_step_ca_initialize(params, module):
    """Runs the step CA initialize command with provided parameters."""
    timeout = 15
    build_cmd = ["step", "ca", "init"]

    for key in [
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
    ]:
        # Add argument if supplied with value
        if params.get(key):
            value = str(params[key]).strip()
            if value:
                build_cmd.extend([f'--{key.replace("_", "-")}', value])

    if params.get("remote_management") and params.get("admin_subject"):
        value = str(params["admin_subject"]).strip()
        if value:
            build_cmd.extend(["--admin-subject", value])

    if params["acme"]:
        build_cmd.append("--acme")
    if params["dns"]:
        for dns_entry in params["dns"]:
            build_cmd.extend(["--dns", dns_entry])
    if params["no_db"]:
        build_cmd.append("--no-db")
    if params["pki"]:
        build_cmd.append("--pki")
    if params["remote_management"]:
        build_cmd.append("--remote-management")
    if params["ssh"]:
        build_cmd.append("--ssh")

    cmd = " ".join(build_cmd)
    module.log("Executing: " + cmd)

    try:
        rc, stdout, stderr = run_command(cmd, timeout=timeout)
        return rc, stdout, stderr

    except CommandTimeout as e:
        # Handle timeout with potential prompt detection
        prompt_pattern = r"(Please enter|Would you like to|\[y/n\])"
        if re.search(prompt_pattern, e.stdout):
            module.fail_json(msg="Detected user input prompt")
        module.fail_json(
            msg=f"Step CA initialization timed out after {timeout} seconds."
        )

    except FileNotFoundError as e:
        module.fail_json(msg=f"Command not found: {str(e)}")

    except OSError as e:
        # Handle OS-related errors
        module.fail_json(msg=f"OS error occurred: {str(e)}")


def main():
    module_args = {
        "acme": {"type": "bool"},
        "address": {
            "type": "str",
            "help": "The address and port that the new CA will listen at .e.g 0.0.0.0:443",
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
                "  standalone: An instance of step-ca that does not connect to any cloud services.\n"
                "              You manage authority keys and configuration yourself.\n"
                "              Choose standalone if you'd like to run step-ca yourself and do not\n"
                "              want cloud services or commercial support.\n"
                "\n"
                "  linked:     An instance of step-ca with locally managed keys that connects to your\n"
                "              Certificate Manager account for provisioner management, alerting, \n"
                "              reporting, revocation, and other managed services.\n"
                "              Choose linked if you'd like cloud services and support, but need to\n"
                "              control your authority's signing keys.\n"
                "\n"
                "  hosted:     A highly available, fully-managed instance of step-ca run by smallstep\n"
                "              just for you.\n"
                "              Choose hosted if you'd like cloud services and support"
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
            "help": "NOT IMPLEMENTED - Generates a Helm values YAML to be used with step-certificates chart",
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
            "help": "The path to the file containing the password to decrypt the existing root certificate key",
            "no_log": True,
        },
        "kms": {"type": "str", "choices": ["azurekms"]},
        "kms_intermediate": {"type": "str"},
        "kms_root": {"type": "str"},
        "kms_ssh_host": {"type": "str"},
        "kms_ssh_user": {
            "type": "str",
            "help": "The kms URI used to generate the key used to sign SSH user certificates",
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
            "help": "Specifies the location where step stores its configuration, state, and Certificate Authority data",
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
            module.fail_json(
                msg=f"Found {file_found}, cannot continue.\n"
                "Use force: true to override or ensure that none of the following files exist:\n"
                + "\n".join(step_files)
            )

    # Run step CA initialization
    return_code, _, stderr = run_step_ca_initialize(module.params, module)
    if return_code != 0:
        module.fail_json(msg=f"Step CA initialization failed: {stderr}")
    changed = True
    # Exit with appropriate message
    module.exit_json(
        changed=changed, msg="Step CA initialization completed successfully."
    )


if __name__ == "__main__":
    main()
