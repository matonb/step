"""Process utilities for executing commands as another user.

This module provides functions to run shell commands, optionally as another
user (e.g., the Step CA system user), without requiring that user
to have a login shell. It is intended for use in Ansible modules
and other automation environments.

Note:
    To switch to another user, the calling process must run as root.
"""

import os
import pwd
import select
import subprocess
import time
from typing import Dict, List, Optional, Union


class CommandTimeout(TimeoutError):
    """Exception raised when a command execution exceeds the timeout."""

    def __init__(self, message: str, stdout: Optional[str] = None, stderr: Optional[str] = None):
        """Initialize CommandTimeout with message and captured output.

        Args:
            message: The error message
            stdout: The captured standard output
            stderr: The captured standard error
        """
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def run_command(
    command: Union[List[str], str],
    debug: bool = False,
    env_vars: Optional[Dict[str, str]] = None,
    shell: bool = False,
    username: Optional[str] = None,
    timeout: Optional[float] = None,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run a command optionally as another system user with timeout support.

    If a username is provided, the process is demoted to the target
    user's UID/GID using os.setuid and os.setgid. The environment is
    updated with standard variables such as HOME, USER, and LOGNAME
    based on the user's passwd entry.

    Args:
        command: The command to execute as a list of args or a string.
        debug: If True, print the command before executing.
        env_vars: Additional environment variables to include during execution.
            These will override any inherited ones.
        shell: Whether to run the command using the shell.
        username: The target system user to impersonate.
        timeout: Maximum time in seconds to wait for the command to complete.
        check: If True, raise a RuntimeError if the command returns a non-zero exit code.
        text: If True, decode stdout and stderr as text instead of bytes.

    Returns:
        subprocess.CompletedProcess: The result of the command execution.

    Raises:
        RuntimeError: If the user switch fails or the command fails.
        CommandTimeout: If the command execution exceeds the timeout.
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
        cmd_str = command if isinstance(command, str) else " ".join(command)
        print(f"Executing command: {cmd_str}")

    # If timeout is specified, use the select-based approach for better timeout handling
    if timeout is not None:
        return _run_with_timeout(
            command=command,
            timeout=timeout,
            env=user_env,
            preexec_fn=preexec_fn,
            shell=shell,
            text=text,
            check=check,
        )

    # Otherwise, use the simpler subprocess.run approach
    try:
        return subprocess.run(
            command,
            preexec_fn=preexec_fn,
            env=user_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
            shell=shell,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        if check:
            stderr = exc.stderr.strip() if text else exc.stderr
            stdout = exc.stdout.strip() if text else exc.stdout
            raise RuntimeError(
                f"Command failed with return code {exc.returncode}.\n"
                f"STDOUT: {stdout}\n"
                f"STDERR: {stderr}"
            ) from exc
        return exc


def _run_with_timeout(
    command: Union[List[str], str],
    timeout: float,
    env: Dict[str, str],
    preexec_fn: Optional[callable] = None,
    shell: bool = False,
    text: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """
    Execute a command with advanced timeout handling using select.

    This implementation monitors stdout and stderr in real-time and
    can capture partial output even if the command times out.

    Args:
        command: The command to execute.
        timeout: Maximum time in seconds to wait for the command to complete.
        env: Environment variables for the command.
        preexec_fn: Function to call in the child process before execution.
        shell: Whether to run the command through the shell.
        text: If True, decode output as text.
        check: If True, raise an exception on non-zero exit codes.

    Returns:
        subprocess.CompletedProcess: Object containing execution results.

    Raises:
        CommandTimeout: If the command execution exceeds the timeout.
        subprocess.CalledProcessError: If the command returns non-zero and check=True.
    """
    # Start the process
    with subprocess.Popen(
        command,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        preexec_fn=preexec_fn,
        text=False,  # We'll handle text conversion ourselves
    ) as process:
        start_time = time.time()

        # Prepare buffers for stdout and stderr
        stdout_chunks = []
        stderr_chunks = []

        # Track if we killed the process due to timeout
        killed = False

        # Monitor stdout and stderr using select
        while True:
            # Check if the process has completed naturally
            if process.poll() is not None:
                break

            # Use select to check for available data with a small timeout
            rlist, _, _ = select.select(
                [process.stdout, process.stderr], [], [], 0.1
            )

            # Read any available data
            for stream in rlist:
                if stream == process.stdout:
                    chunk = process.stdout.read1(1024)
                    if chunk:
                        stdout_chunks.append(chunk)
                elif stream == process.stderr:
                    chunk = process.stderr.read1(1024)
                    if chunk:
                        stderr_chunks.append(chunk)

            # Check if we've exceeded the timeout
            if time.time() - start_time > timeout:
                process.kill()
                killed = True
                break

            # Short sleep to avoid CPU thrashing
            time.sleep(0.01)

        # Read any remaining data after process completion or timeout
        stdout_remainder, stderr_remainder = process.communicate()
        if stdout_remainder:
            stdout_chunks.append(stdout_remainder)
        if stderr_remainder:
            stderr_chunks.append(stderr_remainder)

        # Combine all captured output
        stdout_bytes = b"".join(stdout_chunks)
        stderr_bytes = b"".join(stderr_chunks)

        # Convert to text if requested
        if text:
            stdout_result = stdout_bytes.decode("utf-8", errors="replace")
            stderr_result = stderr_bytes.decode("utf-8", errors="replace")
        else:
            stdout_result = stdout_bytes
            stderr_result = stderr_bytes

        # If process was killed due to timeout, raise exception
        if killed:
            raise CommandTimeout(
                f"Command timed out after {timeout} seconds",
                stdout=stdout_result,
                stderr=stderr_result,
            )

        # Create a CompletedProcess object with the results
        result = subprocess.CompletedProcess(
            args=command,
            returncode=process.returncode,
            stdout=stdout_result,
            stderr=stderr_result,
        )

        # Handle non-zero return code if check is True
        if check and process.returncode != 0:
            exc = subprocess.CalledProcessError(
                process.returncode, command, stdout_result, stderr_result
            )
            raise RuntimeError(
                f"Command failed with return code {exc.returncode}.\n"
                f"STDOUT: {stdout_result.strip() if text else stdout_result}\n"
                f"STDERR: {stderr_result.strip() if text else stderr_result}"
            ) from exc

        return result


# For backward compatibility
run_command_as_user = run_command