"""Process utilities for executing commands.

This module provides functions to run shell commands, optionally as another
user (e.g., the Step CA system user), without requiring that user
to have a login shell. It is intended for use in Ansible modules
and other automation environments.

Note:
    To switch to another user, the calling process must run as root.
"""

import os
import pwd
import re
import subprocess
from typing import Optional, Union


class CommandTimeoutError(TimeoutError):
    """Exception raised when a command execution exceeds the timeout."""

    def __init__(self, message: str, stdout: Optional[str] = None, stderr: Optional[str] = None):
        """Initialize CommandTimeoutError with message and captured output.

        Args:
            message: The error message
            stdout: The captured standard output
            stderr: The captured standard error
        """
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def strip_ansi_sequences(text):
    """Remove ANSI escape sequences used for terminal colors and formatting."""
    # This pattern matches all ANSI escape sequences
    ansi_pattern = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_pattern.sub("", text) if text else text


def sanitize_output(text: Optional[str], strip_ansi: bool = True) -> Optional[str]:
    """Sanitize command output.

    Sanitize command output by optionally stripping ANSI sequences
    and performing additional safety checks.

    Args:
        text: The text to sanitize
        strip_ansi: Whether to remove ANSI escape sequences

    Returns:
        Sanitized text or None
    """
    if text is None:
        return None

    # Optional ANSI sequence stripping
    if strip_ansi:
        text = strip_ansi_sequences(text)

    # Remove or replace any potentially dangerous control characters
    text = "".join(char for char in text if char.isprintable() or char in "\n\r\t")

    return text


def demote_user(username: str):
    """Demote the current process to the specified user's privileges.

    Args:
        username: The target system user to impersonate.

    Raises:
        RuntimeError: If the user cannot be found or privileges cannot be dropped.
    """
    try:
        pw_record = pwd.getpwnam(username)
    except KeyError as exc:
        raise RuntimeError(f"User '{username}' not found on the system.") from exc

    try:
        # First change GID, then UID to prevent permission issues
        os.setgid(pw_record.pw_gid)
        os.setuid(pw_record.pw_uid)
    except OSError as exc:
        raise RuntimeError(f"Failed to switch to user '{username}': {exc}") from exc

    # Update environment variables to reflect the new user
    os.environ.update(
        {
            "HOME": pw_record.pw_dir,
            "USER": username,
            "LOGNAME": username,
        }
    )


def _validate_user_switch(username: Optional[str]) -> None:
    """Validate that we can switch to the specified user.

    Args:
        username: The target system user to impersonate.

    Raises:
        RuntimeError: If the user switch cannot be performed.
    """
    if username and os.geteuid() != 0:
        raise RuntimeError(
            f"Unable to switch to user '{username}'. This operation "
            "requires root privileges (use 'become: true' in your "
            "playbook)."
        )


def _create_completed_process(
    command: Union[list[str], str],
    returncode: int,
    stdout: Optional[str],
    stderr: Optional[str],
    text: bool,
    strip_ansi: bool,
) -> subprocess.CompletedProcess:
    """Create a CompletedProcess object with sanitized output.

    Args:
        command: The command that was executed.
        returncode: The return code from the command.
        stdout: The standard output from the command.
        stderr: The standard error from the command.
        text: Whether output was captured as text.
        strip_ansi: Whether to strip ANSI sequences.

    Returns:
        A CompletedProcess object with sanitized outputs.
    """
    # Sanitize output if text is True
    if text:
        stdout = sanitize_output(stdout, strip_ansi)
        stderr = sanitize_output(stderr, strip_ansi)

    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _handle_command_failure(result: subprocess.CompletedProcess, check: bool, text: bool) -> None:
    """Handle command failure based on check flag.

    Args:
        result: The CompletedProcess object.
        check: Whether to raise an exception on failure.
        text: Whether output was captured as text.

    Raises:
        RuntimeError: If check is True and the command failed.
    """
    if check and result.returncode != 0:
        stdout = result.stdout.strip() if text and result.stdout else result.stdout
        stderr = result.stderr.strip() if text and result.stderr else result.stderr

        raise RuntimeError(f"Command failed with return code {result.returncode}.\nSTDOUT: {stdout}\nSTDERR: {stderr}")


def run_command(
    command: Union[list[str], str],
    debug: bool = False,
    env_vars: Optional[dict[str, str]] = None,
    shell: bool = False,
    username: Optional[str] = None,
    timeout: Optional[float] = None,
    check: bool = True,
    text: bool = True,
    strip_ansi: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command optionally as another system user with timeout support and output sanitization.

    Args:
        command: The command to execute as a list of args or a string.
        debug: If True, print the command before executing.
        env_vars: Additional environment variables to include during execution.
        shell: Whether to run the command using the shell.
        username: The target system user to impersonate.
        timeout: Maximum time in seconds to wait for the command to complete.
        check: If True, raise a RuntimeError if the command returns a non-zero exit code.
        text: If True, decode stdout and stderr as text instead of bytes.
        strip_ansi: If True, remove ANSI escape sequences from output.

    Returns:
        subprocess.CompletedProcess: The result of the command execution.

    Raises:
        RuntimeError: If the user switch fails or the command fails.
        CommandTimeoutError: If the command execution exceeds the timeout.
    """
    # Validate user switch
    _validate_user_switch(username)

    # Prepare environment
    user_env = os.environ.copy()
    if env_vars:
        user_env.update(env_vars)

    # Debug output
    if debug:
        cmd_str = command if isinstance(command, str) else " ".join(command)
        print(f"Executing command: {cmd_str}")

    # If timeout is specified, use the select-based approach
    if timeout is not None:
        return _run_with_timeout(
            command=command,
            timeout=timeout,
            env=user_env,
            username=username,
            shell=shell,
            text=text,
            check=check,
            strip_ansi=strip_ansi,
        )

    # Otherwise, use the simpler subprocess approach
    try:
        # Use subprocess.Popen for more controlled execution
        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=user_env,
            text=text,
            shell=shell,
            preexec_fn=lambda: demote_user(username) if username else None,
        ) as process:
            # Wait for the process to complete
            stdout, stderr = process.communicate()

            # Create CompletedProcess with results
            result = _create_completed_process(command, process.returncode, stdout, stderr, text, strip_ansi)

            # Check return code if required
            _handle_command_failure(result, check, text)

            return result

    except subprocess.CalledProcessError as exc:
        if check:
            # Sanitize stdout and stderr
            stderr = sanitize_output(exc.stderr, strip_ansi) if text else exc.stderr
            stdout = sanitize_output(exc.stdout, strip_ansi) if text else exc.stdout

            raise RuntimeError(
                f"Command failed with return code {exc.returncode}.\nSTDOUT: {stdout}\nSTDERR: {stderr}"
            ) from exc

        # Sanitize stdout and stderr for the exception case
        if text:
            exc.stdout = sanitize_output(exc.stdout, strip_ansi)
            exc.stderr = sanitize_output(exc.stderr, strip_ansi)

        return exc


def _run_with_timeout(
    command: Union[list[str], str],
    timeout: float,
    env: dict[str, str],
    username: Optional[str] = None,
    shell: bool = False,
    text: bool = True,
    check: bool = True,
    strip_ansi: bool = True,
) -> subprocess.CompletedProcess:
    """Execute a command with advanced timeout handling.

    Args:
        command: The command to execute.
        timeout: Maximum time in seconds to wait for the command to complete.
        env: Environment variables for the command.
        username: Optional user to run the command as.
        shell: Whether to run the command through the shell.
        text: If True, decode output as text.
        check: If True, raise an exception on non-zero exit codes.
        strip_ansi: If True, remove ANSI escape sequences from output.

    Returns:
        subprocess.CompletedProcess: Object containing execution results.

    Raises:
        CommandTimeoutError: If the command execution exceeds the timeout.
        subprocess.CalledProcessError: If the command returns non-zero and check=True.
    """
    # Start the process
    process = subprocess.Popen(
        command,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=text,
        preexec_fn=lambda: demote_user(username) if username else None,
    )

    try:
        # Wait for the process to complete or timeout
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as timeout_err:
            # Kill the process and get any remaining output
            process.kill()
            stdout, stderr = process.communicate()

            # Create timeout exception with sanitized output
            sanitized_stdout = sanitize_output(stdout, strip_ansi) if text else stdout
            sanitized_stderr = sanitize_output(stderr, strip_ansi) if text else stderr

            raise CommandTimeoutError(
                f"Command timed out after {timeout} seconds",
                stdout=sanitized_stdout,
                stderr=sanitized_stderr,
            ) from timeout_err

        # Create a CompletedProcess object with the results
        result = _create_completed_process(command, process.returncode, stdout, stderr, text, strip_ansi)

        # Handle non-zero return code if check is True
        _handle_command_failure(result, check, text)

        return result

    finally:
        # Ensure the process is terminated
        try:
            process.terminate()
        except ProcessLookupError:
            pass


# For backward compatibility
run_command_as_user = run_command
