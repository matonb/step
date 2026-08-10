# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Read a step-ca JSON configuration file."""

DOCUMENTATION = r"""
---
module: config_info
short_description: Read a step-ca JSON configuration file
version_added: "1.4.2"
description:
  - Reads a step-ca JSON configuration file, such as C(defaults.json), and returns its contents.
  - >-
    This module only reads; it never writes. It always reports C(changed) as
    false and is safe to run in check mode.
options:
  config_file:
    description:
      - Path to the JSON configuration file to read.
    required: true
    type: str
author:
  - Brett Maton (@matonb)
"""

EXAMPLES = r"""
- name: Read the CA defaults
  matonb.smallstep.config_info:
    config_file: /etc/step-ca/config/defaults.json
  register: ca_defaults

- name: Use the CA URL from the defaults file
  ansible.builtin.debug:
    msg: "CA URL is {{ ca_defaults.config['ca-url'] }}"
"""

RETURN = r"""
changed:
  description: Always false; this module only reads.
  returned: success
  type: bool

config:
  description: The parsed contents of the configuration file.
  returned: success
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.matonb.smallstep.plugins.module_utils.utils import (
    read_json_file,
)


def main():
    """Run the Ansible module."""
    module_args = {"config_file": {"type": "str", "required": True}}

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    config_file = module.params["config_file"]
    config_data, error = read_json_file(config_file)

    if error:
        module.fail_json(msg=error)

    module.exit_json(changed=False, config=config_data)


if __name__ == "__main__":
    main()
