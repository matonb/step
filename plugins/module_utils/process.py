# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
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
from collections.abc import Callable
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


def _resolve_demotion(username: str) -> tuple[pwd.struct_passwd, list[int]]:
    """Look up everything the switch needs, before any fork.

    Both lookups go to NSS, which on a host using SSSD or LDAP means network
    I/O and a lock. Done here, in the parent, that is ordinary. Done between
    fork and exec it is the classic preexec_fn hazard: the child holds a copy
    of whatever locks were held at fork time and can deadlock against them.

    Args:
        username: The target system user to impersonate.

    Returns:
        The user's passwd record and the group ids they belong to.

    Raises:
        RuntimeError: If the user cannot be found or their groups cannot be read.
    """
    try:
        pw_record = pwd.getpwnam(username)
    except KeyError as exc:
        raise RuntimeError(f"User '{username}' not found on the system.") from exc

    try:
        groups = os.getgrouplist(username, pw_record.pw_gid)
    except OSError as exc:
        raise RuntimeError(f"Could not read the groups for user '{username}': {exc}") from exc

    return pw_record, groups


def _apply_demotion(username: str, pw_record: pwd.struct_passwd, groups: list[int]) -> None:
    """Drop to the given user's ids. Syscalls only, safe after a fork.

    Args:
        username: The target system user, for the environment and messages.
        pw_record: The user's passwd record, from _resolve_demotion.
        groups: The user's group ids, from _resolve_demotion.

    Raises:
        RuntimeError: If privileges cannot be dropped.
    """
    try:
        # Supplementary groups first. setgid and setuid leave the calling
        # process's own group memberships in place, and the caller here is
        # root, so without this the command keeps root's groups after the
        # switch and holds access the target user was never granted.
        #
        # Then GID, then UID. Once the UID is no longer root none of the three
        # is permitted, so this order is what makes the drop stick.
        os.setgroups(groups)
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


def demote_user(username: str):
    """Demote the current process to the specified user's privileges.

    Args:
        username: The target system user to impersonate.

    Raises:
        RuntimeError: If the user cannot be found or privileges cannot be dropped.
    """
    pw_record, groups = _resolve_demotion(username)
    _apply_demotion(username, pw_record, groups)


def _demotion_hook(username: Optional[str]) -> Optional[Callable[[], None]]:
    """Build the post-fork hook that drops privileges, or nothing to run.

    Returning None rather than a callable that does nothing matters: preexec_fn
    runs arbitrary Python between fork and exec and is not thread-safe, so a
    command with no user to switch to should not carry one at all.

    The lookup happens here rather than in the hook. subprocess reports any
    exception from a preexec_fn as a generic SubprocessError - "Exception
    occurred in preexec_fn." - so a misspelled username raised in the child
    reaches the operator as that and nothing else. Raised here it is the
    RuntimeError naming the user, before anything forks.

    Args:
        username: The target system user, or None to run as the current user.

    Returns:
        A callable for subprocess's preexec_fn, or None when nothing is to be
        demoted.

    Raises:
        RuntimeError: If the user cannot be found or their groups cannot be read.
    """
    if not username:
        return None

    pw_record, groups = _resolve_demotion(username)

    return lambda: _apply_demotion(username, pw_record, groups)


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
    *,
    logger: Optional[Callable[[str], None]] = None,
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
        logger: Optional callable that records the command before it runs.
            Modules should pass C(module.log). A module must never write to
            stdout, which Ansible parses as the module's JSON result.
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

    if logger:
        cmd_str = command if isinstance(command, str) else " ".join(command)
        logger(f"Executing command: {cmd_str}")

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
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=user_env,
        text=text,
        shell=shell,
        preexec_fn=_demotion_hook(username),
    ) as process:
        # Wait for the process to complete
        stdout, stderr = process.communicate()

        # Create CompletedProcess with results
        result = _create_completed_process(command, process.returncode, stdout, stderr, text, strip_ansi)

        # Check return code if required
        _handle_command_failure(result, check, text)

        return result


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
        RuntimeError: If the command returns non-zero and check=True.
    """
    # Start the process
    process = subprocess.Popen(
        command,
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=text,
        preexec_fn=_demotion_hook(username),
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
        # A no-op on every path above, where communicate() has already set
        # returncode and terminate() skips a process known to have died. It
        # earns its place for the paths not above: communicate() raising
        # anything other than TimeoutExpired - a UnicodeDecodeError on invalid
        # UTF-8 from the child, with text=True - leaves that child running and
        # this is what reaps it.
        #
        # No handler around it. Popen.send_signal polls first, returns early
        # once returncode is set, and catches ProcessLookupError itself for the
        # race after that (bpo-40550), so there is nothing left here to catch.
        process.terminate()


# For backward compatibility
run_command_as_user = run_command
