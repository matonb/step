"""
Utility functions for working with the 'step' command.
"""
import json
import subprocess
from pathlib import Path

ENCODING = "utf-8"


def get_step_path():
    """Execute 'step path' command and return its output.

    Raises:
        RuntimeError: If the command execution fails.

    Returns:
        str: The output of the 'step path' command.
    """
    try:
        result = subprocess.run(
            ["step", "path"], check=True, capture_output=True, text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Failed to execute 'step path': {error.stderr.strip()}")


def read_json_file(json_file):
    """Reads and parses a JSON configuration file."""
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


def save_json_file(json_path, data):
    """Save JSON data to a file."""
    try:
        with open(json_path, "w", encoding=ENCODING) as file:
            json.dump(data, file, indent=4)
    except IOError as error:
        return {"error": f"Failed to write JSON file: {str(error)}"}
    return {"success": True}
