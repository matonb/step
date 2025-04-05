"""Process utilities for executing commands as another user.

This module provides a function to run shell commands as another
user (e.g., the Step CA system user), without requiring that user
to have a login shell. It is intended for use in Ansible modules
and other automation environments.

Note:
    To switch to another user, the calling process must run as root.
"""

import os
import pwd
import subprocess
from typing import List, Optional, Dict


def run_command_as_user(
    command: List[str],
    debug: bool = False,
    env_vars: Optional[Dict[str, str]] = None,
    shell: bool = False,
    username: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """
    Run a command optionally as another system user.

    If a username is provided, the process is demoted to the target
    user's UID/GID using os.setuid and os.setgid. The environment is
    updated with standard variables such as HOME, USER, and LOGNAME
    based on the user's passwd entry. The function requires root
    privileges to perform user switching.

    Args:
        command (List[str]): The command to execute as a list of args.
        debug (bool): If True, print the command before executing.
        env_vars (Optional[Dict[str, str]]): Additional environment
            variables to include during execution. These will override
            any inherited ones.
        shell (bool): Whether to run the command using the shell.
        username (Optional[str]): The target system user to impersonate.

    Returns:
        subprocess.CompletedProcess: The result of the command execution.

    Raises:
        RuntimeError: If the user switch fails or the command fails.
    """
    user_env = os.environ.copy()
    preexec_fn = None

    if username:
        if os.geteuid() != 0:
            raise RuntimeError(
                f"Unable to switch to user '{username}'. This operation "
                "requires root privileges (use 'become: true' in your "
                "playbook)."
            )

        try:
            pw_record = pwd.getpwnam(username)
        except KeyError as exc:
            raise RuntimeError(
                f"User '{username}' not found on the system."
            ) from exc

        user_uid = pw_record.pw_uid
        user_gid = pw_record.pw_gid
        user_home = pw_record.pw_dir

        user_env.update({
            "HOME": user_home,
            "USER": username,
            "LOGNAME": username,
        })

        def demote():
            os.setgid(user_gid)
            os.setuid(user_uid)

        preexec_fn = demote

    if env_vars:
        user_env.update(env_vars)

    if debug:
        print(f"Executing command: {command}")

    try:
        return subprocess.run(
            command,
            preexec_fn=preexec_fn,
            env=user_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=shell,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Command failed with return code {exc.returncode}.\n"
            f"STDOUT: {exc.stdout.strip()}\n"
            f"STDERR: {exc.stderr.strip()}"
        ) from exc
