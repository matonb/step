"""
Ansible module for loading and modifying a JSON file.

This module takes a JSON file path and a dictionary of updates,
modifies the JSON file, and saves the changes.
"""

import json
import os

from ansible.module_utils.basic import AnsibleModule

ENCODING = "utf-8"


def load_json_file(json_path):
    """Load JSON data from a file."""
    if not os.path.exists(json_path):
        return {}

    try:
        with open(json_path, "r", encoding=ENCODING) as file:
            return json.load(file)
    except (json.JSONDecodeError, IOError) as error:
        return {"error": f"Failed to load JSON file: {str(error)}"}


def save_json_file(json_path, data):
    """Save JSON data to a file."""
    try:
        with open(json_path, "w", encoding=ENCODING) as file:
            json.dump(data, file, indent=4)
    except IOError as error:
        return {"error": f"Failed to write JSON file: {str(error)}"}
    return {"success": True}


def main():
    """Main function to execute the Ansible module logic."""
    module_args = {
        "ca_config": {"type": "path", "required": False, "default": None},
        "ca_path": {"type": "path", "required": False, "default": None},
        "crt": {"type": "path", "required": False, "default": None},
        "db_datasource": {"type": "str", "required": False, "default": None},
        "json_path": {"type": "str", "required": True},
        "key": {"type": "path", "required": False, "default": None},
        "root": {"type": "path", "required": False, "default": None},
    }

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    json_path = module.params["json_path"]

    # Construct updates dictionary from provided parameters
    updates = {
        key: module.params[key]
        for key in module_args.keys()
        if key != "json_path" and module.params[key] is not None
    }

    # Load existing JSON data
    json_data = load_json_file(json_path)

    # Handle JSON loading errors
    if "error" in json_data:
        module.fail_json(msg=json_data["error"])

    # Apply updates
    json_data.update(updates)

    if module.check_mode:
        module.exit_json(changed=True, new_data=json_data)

    # Save updated JSON data
    result = save_json_file(json_path, json_data)

    if "error" in result:
        module.fail_json(msg=result["error"])

    module.exit_json(changed=True, msg="JSON file updated", new_data=json_data)


if __name__ == "__main__":
    main()
