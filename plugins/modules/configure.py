# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Modify a step-ca configuration JSON file with provided updates."""

DOCUMENTATION = r"""
---
module: configure
short_description: Modify a step-ca ca.json configuration file
version_added: "1.0.0"
description:
  - Applies settings to a step-ca C(ca.json) configuration file.
  - >-
    Most options are written at the top level of the file. The three TLS
    certificate durations are written under C(authority.claims), where they
    become the CA-wide defaults inherited by provisioners that do not set
    their own.
  - step-ca must be restarted or sent SIGHUP for changes to take effect.
notes:
  - >-
    This module always reports C(changed) as true, even when the requested
    settings already match the file.
options:
  ca_config:
    description:
      - Path to the CA configuration file, written to the top level of C(ca.json).
    required: false
    type: path
  ca_path:
    description:
      - Path to the CA directory, written to the top level of C(ca.json).
    required: false
    type: path
  crt:
    description:
      - Path to the intermediate certificate, written to the top level of C(ca.json).
    required: false
    type: path
  db_datasource:
    description:
      - Database datasource, written to the top level of C(ca.json).
    required: false
    type: str
  default_tls_cert_duration:
    description:
      - Default TLS certificate duration, for example C(720h).
      - Written to C(authority.claims.defaultTLSCertDuration).
    required: false
    type: str
  json_path:
    description:
      - Path to the C(ca.json) configuration file to modify.
    required: true
    type: str
  key:
    description:
      - Path to the intermediate private key, written to the top level of C(ca.json).
    required: false
    type: path
  max_tls_cert_duration:
    description:
      - Maximum TLS certificate duration, for example C(8760h).
      - Written to C(authority.claims.maxTLSCertDuration).
    required: false
    type: str
  min_tls_cert_duration:
    description:
      - Minimum TLS certificate duration, for example C(5m).
      - Written to C(authority.claims.minTLSCertDuration).
    required: false
    type: str
  root:
    description:
      - Path to the root certificate, written to the top level of C(ca.json).
    required: false
    type: path
author:
  - Brett Maton (@matonb)
"""

EXAMPLES = r"""
- name: Configure certificate durations
  matonb.step.configure:
    default_tls_cert_duration: "720h"
    json_path: /etc/step-ca/config/ca.json
    max_tls_cert_duration: "8760h"
  notify: restart step-ca

- name: Configure the database datasource
  matonb.step.configure:
    db_datasource: /var/lib/step-ca/db
    json_path: /etc/step-ca/config/ca.json
  notify: restart step-ca

- name: Configure paths and durations together
  matonb.step.configure:
    crt: /etc/step-ca/certs/intermediate_ca.crt
    json_path: /etc/step-ca/config/ca.json
    key: /etc/step-ca/secrets/intermediate_ca_key
    max_tls_cert_duration: "17520h"
    root: /etc/step-ca/certs/root_ca.crt
  notify: restart step-ca
"""

RETURN = r"""
changed:
  description: Always true when the module runs to completion.
  returned: success
  type: bool

msg:
  description: Confirmation that the file was written.
  returned: success
  type: str

new_data:
  description: The full configuration after the requested updates were applied.
  returned: success
  type: dict
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
