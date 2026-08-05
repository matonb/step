# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Utility functions for working with the 'step' command."""

import json
import os
import pwd
import re
import secrets
import stat
import string
import tempfile
from pathlib import Path
from typing import Any, Optional

from .process import run_command

ENCODING = "utf-8"

# Matches the interactive prompts the step CLI emits when a required input is
# missing. A module that sees one of these has hung rather than failed, so the
# text is used to turn a timeout into an actionable error.
PROMPT_PATTERN = re.compile(r"(Please enter|Would you like to|What .*\?|\[y/n\])")

# Nanoseconds per unit suffix accepted by Go's time.ParseDuration, which is what
# step uses for every duration flag and claim. Go accumulates into an int64 of
# nanoseconds and this parser does the same, so two spellings of one duration
# always compare equal.
_DURATION_UNITS = {
    "ns": 1,
    "us": 1_000,
    "µs": 1_000,
    "μs": 1_000,
    "ms": 1_000_000,
    "s": 1_000_000_000,
    "m": 60_000_000_000,
    "h": 3_600_000_000_000,
}
_DURATION_TERM = re.compile(r"(\d+(?:\.\d*)?|\.\d+)(ns|us|µs|μs|ms|s|m|h)")


def get_step_path() -> str:
    """Execute 'step path' command and return its output.

    Raises:
        RuntimeError: If the command execution fails.

    Returns:
        str: The output of the 'step path' command.
    """
    result = run_command(["step", "path"], check=True)
    return result.stdout.strip()


def generate_secure_password(length: int = 32) -> str:
    """Generate a cryptographically secure random password.

    The password includes uppercase and lowercase letters, digits,
    and special characters to ensure high security standards.

    Args:
        length: The length of the password to generate (default: 32).

    Returns:
        str: A secure random password.
    """
    # Define character sets for password complexity
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}|;:,.<>?"

    # Ensure at least one of each character type for complexity requirements
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*()-_=+[]{}|;:,.<>?"),
    ]

    # Fill the rest of the password with random characters
    password.extend(secrets.choice(alphabet) for _position in range(length - 4))

    # Shuffle the password to randomize character positions
    secrets.SystemRandom().shuffle(password)

    return "".join(password)


def parse_duration(value: str) -> int:
    """Parse a Go duration string into a whole number of nanoseconds.

    The CA normalises durations when it serialises them, so a claim requested
    as C(5m) is returned by C(step ca provisioner list) as C(5m0s). Comparing
    the parsed values avoids treating that as a change.

    The result is an exact integer count of nanoseconds, mirroring how Go
    accumulates durations. The arithmetic stays in ints throughout because the
    results are compared for equality, and the format permits fractions on
    either side: a claim set to C(1.5h) is reported back as C(1h30m0s), and
    C(Duration.String()) emits forms like C(1.5s) directly.

    Args:
        value: A duration such as "36h", "2h45m", "500ms" or "1.5h".

    Returns:
        int: The duration expressed in nanoseconds.

    Raises:
        ValueError: If the value is not a valid duration.
    """
    text = value.strip()
    if not text:
        raise ValueError("Duration must not be empty.")

    sign = -1 if text.startswith("-") else 1
    if text[0] in "+-":
        text = text[1:]

    # Go accepts a bare "0" with no unit; every other value needs a suffix.
    if text == "0":
        return 0

    total = 0
    position = 0
    for term in _DURATION_TERM.finditer(text):
        if term.start() != position:
            break

        whole, _separator, fraction = term.group(1).partition(".")
        nanoseconds = _DURATION_UNITS[term.group(2)]
        total += int(whole or 0) * nanoseconds
        if fraction:
            # Scale the fractional digits as an integer rather than a float, so
            # that e.g. 1.1h is exactly 3960000000000ns and not a value that
            # differs from the 1h6m0s the CA reports back.
            total += int(fraction) * nanoseconds // 10 ** len(fraction)

        position = term.end()

    # A bare sign leaves nothing to parse, so require that something matched
    # and that the whole string was consumed.
    if position == 0 or position != len(text):
        raise ValueError(f"Invalid duration: {value!r}")

    return sign * total


def write_secret_file(content: str, owner: Optional[str] = None) -> str:
    """Write a secret to a private temporary file.

    Args:
        content: The secret to write.
        owner: Optional system user that must be able to read the file. This
            should match the user the step command will be demoted to.

    Returns:
        str: Path to the file. The caller is responsible for removing it.

    Raises:
        RuntimeError: If the file cannot be handed to C(owner).
    """
    handle, path = tempfile.mkstemp(text=True)
    try:
        with os.fdopen(handle, "w", encoding=ENCODING) as secret_file:
            secret_file.write(content)

        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

        if owner:
            try:
                account = pwd.getpwnam(owner)
                os.chown(path, account.pw_uid, account.pw_gid)
            except (KeyError, OSError) as exc:
                # Widening the mode instead would expose the secret to every
                # user on the host, so fail rather than leak it.
                raise RuntimeError(f"Unable to grant user '{owner}' access to a temporary secret file: {exc}") from exc
    except Exception:
        # Never leave a file containing a secret behind.
        try:
            os.remove(path)
        except OSError:
            pass
        raise

    return path


def read_json_file(json_file: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Read and parses a JSON configuration file.

    Args:
        json_file: Path to the JSON file.

    Returns:
        Tuple containing the parsed data (or None) and an error message (or None).
    """
    path = Path(json_file)

    if not path.exists():
        return None, f"File not found: {json_file}"

    try:
        with path.open("r", encoding=ENCODING) as file:
            data = json.load(file)
        return data, None
    except FileNotFoundError:
        return None, f"File '{json_file}' does not exist."
    except json.JSONDecodeError as json_error:
        return None, f"Invalid JSON format: {json_error}"
    except PermissionError:
        return None, f"Permission denied when accessing '{json_file}'."
    except OSError as os_error:
        return None, f"OS error: {os_error}"
    except ValueError as value_error:
        return None, f"Invalid data in file: {value_error}"


def save_json_file(module, json_path: str, data: dict[str, Any]) -> Optional[str]:
    """Write JSON to a file atomically, replacing it in one step.

    Writing in place would empty the file before the new contents were
    complete, so an interruption or a serialisation error would leave a CA
    configuration that step-ca cannot load. Serialising to a temporary file
    first means the original survives every failure: either the replacement
    succeeds whole, or nothing happened at all.

    The temporary file goes in the target's own directory because a rename is
    only atomic within a single filesystem, and the move is delegated to
    C(AnsibleModule.atomic_move), which preserves an existing destination's
    mode, ownership and SELinux context. A destination that does not exist yet
    is created with the running user's umask.

    A symlink is followed rather than replaced, so a C(ca.json) that points
    elsewhere keeps pointing there and the file it names is what gets updated.

    Args:
        module: The Ansible module instance, used for the atomic move.
        json_path: The file path where the data will be saved.
        data: The JSON-serializable data to write.

    Returns:
        str or None: An error message, or None on success.
    """
    target = os.path.realpath(json_path)
    directory = os.path.dirname(target) or "."
    try:
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".matonb-step-", suffix=".json")
    except OSError as error:
        return f"Failed to write JSON file '{target}': {error}"

    try:
        with os.fdopen(handle, "w", encoding=ENCODING) as file:
            json.dump(data, file, indent=4)
            file.flush()
            # Without this the rename can be committed before the data behind
            # it, so a power loss leaves an empty file where the CA config was.
            os.fsync(file.fileno())
        # atomic_move raises a bare Exception on failure, and older cores call
        # fail_json instead, which is a SystemExit. Catching only OSError left
        # the temporary file behind and lost the error - and a bind-mounted
        # ca.json gives EBUSY on rename, so this is an ordinary case, not an
        # exotic one.
        module.atomic_move(temporary, target)
    except Exception as error:
        return f"Failed to write JSON file '{target}': {error}"
    finally:
        # The original is untouched whatever happened; take the half-written
        # copy with us. A finally rather than an except branch because older
        # cores fail_json inside atomic_move, and that SystemExit has to keep
        # propagating while still leaving no temporary file behind.
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass

    return None
