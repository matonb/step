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
  - >-
    The file is only rewritten when a requested setting differs from what it
    already holds, so C(changed) is accurate and a C(notify) handler fires only
    on a real change. Settings this module does not manage are left untouched.
  - >-
    Durations are compared as durations rather than as text, because step
    renormalises them when it rewrites C(ca.json): a claim set here as C(8760h)
    is written back as C(8760h0m0s). The two mean the same thing and are not
    treated as a change.
  - >-
    Supports check mode. Under C(--check) the resulting configuration is
    computed and returned, and C(changed) is predicted, but nothing is written.
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
  description: Whether the file had to be rewritten.
  returned: success
  type: bool

msg:
  description: Whether the file was written or already held the requested settings.
  returned: success
  type: str

new_data:
  description: The full configuration after the requested updates were applied.
  returned: success
  type: dict
"""

import copy
import json
import os

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.matonb.step.plugins.module_utils.utils import parse_duration

ENCODING = "utf-8"

# Options written to the top level of ca.json, unchanged.
TOP_LEVEL_KEYS = ("ca_config", "ca_path", "crt", "db_datasource", "key", "root")

# Options written under authority.claims, where they become the CA-wide
# defaults inherited by provisioners that do not set their own.
CLAIM_KEYS = {
    "default_tls_cert_duration": "defaultTLSCertDuration",
    "max_tls_cert_duration": "maxTLSCertDuration",
    "min_tls_cert_duration": "minTLSCertDuration",
}


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


def _already_expresses(stored, wanted_nanoseconds):
    """Whether a stored claim already means the requested duration.

    Args:
        stored: The value currently in the file.
        wanted_nanoseconds: The requested duration, already parsed.

    Returns:
        bool: True if the two are the same duration. A stored value that
        cannot be parsed is treated as different, so it gets corrected.
    """
    try:
        return parse_duration(str(stored)) == wanted_nanoseconds
    except ValueError:
        return False


def apply_updates(config, params):
    """Apply the requested settings to a copy of the configuration.

    Returning a new object rather than mutating in place is what lets the
    caller compare before and after, and so report C(changed) accurately.

    Args:
        config: The configuration as read from disk.
        params: The module parameters.

    Returns:
        dict: The configuration with the requested settings applied.

    Raises:
        ValueError: If a requested duration cannot be parsed.
    """
    updated = copy.deepcopy(config)
    updated.update({key: params[key] for key in TOP_LEVEL_KEYS if params[key] is not None})

    requested = {key: params[key] for key in CLAIM_KEYS if params[key] is not None}
    if not requested:
        return updated

    claims = updated.setdefault("authority", {}).setdefault("claims", {})
    for key, value in requested.items():
        try:
            wanted = parse_duration(value)
        except ValueError as exc:
            raise ValueError(f"Invalid value for '{key}': {exc}") from exc

        claim = CLAIM_KEYS[key]
        # Durations are compared as durations, not as text. step renormalises
        # what it writes - a claim set here as 8760h comes back as 8760h0m0s
        # once step has rewritten ca.json - and rewriting that to the requested
        # spelling would report changed on every run and restart the CA with
        # it, while meaning exactly the same thing.
        if claim in claims and _already_expresses(claims[claim], wanted):
            continue
        claims[claim] = value

    return updated


def get_argument_spec():
    """Return the argument spec for the configure module.

    Returns:
        dict: The module's argument specification.
    """
    return {
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


def main():
    """Run the Ansible module."""
    module = AnsibleModule(argument_spec=get_argument_spec(), supports_check_mode=True)

    json_path = module.params["json_path"]

    json_data = load_json_file(json_path)

    if "error" in json_data:
        module.fail_json(msg=json_data["error"])

    try:
        new_data = apply_updates(json_data, module.params)
    except ValueError as exc:
        module.fail_json(msg=str(exc))

    # Rewriting a file that already says the right thing would report changed
    # on every run, and any notify handler would restart the CA with it.
    if new_data == json_data:
        module.exit_json(changed=False, msg="Configuration already up to date", new_data=new_data)

    if module.check_mode:
        module.exit_json(changed=True, msg="Configuration would be updated", new_data=new_data)

    result = save_json_file(json_path, new_data)

    if "error" in result:
        module.fail_json(msg=result["error"])

    module.exit_json(changed=True, msg="JSON file updated", new_data=new_data)


if __name__ == "__main__":
    main()
