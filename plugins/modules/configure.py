"""Modify a step-ca configuration JSON file with provided updates.

This module takes a JSON file path and a dictionary of updates,
modifies the JSON file, and saves the changes.
Note: Step CA usually needs restarting after configuration changes.

Options:
    ca_config: Path to CA config file (top-level)
    ca_path: Path to CA directory (top-level)
    crt: Path to certificate file (top-level)
    db_datasource: Database datasource string (top-level)
    default_tls_cert_duration: Default TLS cert duration (e.g., "720h") (authority.claims)
    json_path: Path to the ca.json configuration file (required)
    key: Path to key file (top-level)
    max_tls_cert_duration: Maximum TLS cert duration (e.g., "8760h") (authority.claims)
    min_tls_cert_duration: Minimum TLS cert duration (e.g., "5m") (authority.claims)
    root: Path to root certificate (top-level)
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
        with open(json_path, encoding=ENCODING) as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        return {"error": f"Failed to load JSON file: {str(error)}"}


def save_json_file(json_path, data):
    """Save JSON data to a file."""
    try:
        with open(json_path, "w", encoding=ENCODING) as file:
            json.dump(data, file, indent=4)
    except OSError as error:
        return {"error": f"Failed to write JSON file: {str(error)}"}
    return {"success": True}


def main():
    """Run the Ansible module."""
    module_args = {
        "ca_config": {"type": "path", "required": False, "default": None},
        "ca_path": {"type": "path", "required": False, "default": None},
        "crt": {"type": "path", "required": False, "default": None},
        "db_datasource": {"type": "str", "required": False, "default": None},
        "default_tls_cert_duration": {"type": "str", "required": False, "default": None},
        "json_path": {"type": "str", "required": True},
        "key": {"type": "path", "required": False, "default": None},
        "max_tls_cert_duration": {"type": "str", "required": False, "default": None},
        "min_tls_cert_duration": {"type": "str", "required": False, "default": None},
        "root": {"type": "path", "required": False, "default": None},
    }

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    json_path = module.params["json_path"]

    # Top-level parameters
    top_level_keys = ["ca_config", "ca_path", "crt", "db_datasource", "key", "root"]
    updates = {key: module.params[key] for key in top_level_keys if module.params[key] is not None}

    # Claims parameters (nested under authority.claims)
    claims_map = {
        "max_tls_cert_duration": "maxTLSCertDuration",
        "default_tls_cert_duration": "defaultTLSCertDuration",
        "min_tls_cert_duration": "minTLSCertDuration",
    }
    claims_updates = {claims_map[key]: module.params[key] for key in claims_map if module.params[key] is not None}

    json_data = load_json_file(json_path)

    if "error" in json_data:
        module.fail_json(msg=json_data["error"])

    # Apply top-level updates
    json_data.update(updates)

    # Apply claims updates under authority.claims
    if claims_updates:
        if "authority" not in json_data:
            json_data["authority"] = {}
        if "claims" not in json_data["authority"]:
            json_data["authority"]["claims"] = {}
        json_data["authority"]["claims"].update(claims_updates)

    if module.check_mode:
        module.exit_json(changed=True, new_data=json_data)

    result = save_json_file(json_path, json_data)

    if "error" in result:
        module.fail_json(msg=result["error"])

    module.exit_json(changed=True, msg="JSON file updated", new_data=json_data)


if __name__ == "__main__":
    main()
