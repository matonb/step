"""Utility functions for working with the 'step' command."""

import json
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

from .process import run_command

ENCODING = "utf-8"


def get_step_path() -> str:
    """Execute 'step path' command and return its output.

    Raises:
        RuntimeError: If the command execution fails.

    Returns:
        str: The output of the 'step path' command.
    """
    result = run_command(["step", "path"], check=True)
    return result.stdout.strip()


def read_json_file(json_file: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Reads and parses a JSON configuration file.

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


def save_json_file(json_path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Save JSON data to a file.

    Args:
        json_path: The file path where the data will be saved.
        data: The JSON-serializable data to write.

    Returns:
        dict: Success or error information.
    """
    try:
        with open(json_path, "w", encoding=ENCODING) as file:
            json.dump(data, file, indent=4)
    except IOError as error:
        return {"error": f"Failed to write JSON file: {str(error)}"}
    return {"success": True}
