"""
Bootstrap a node with step-ca root certificate.

This Ansible module bootstraps a step-ca node by installing the root certificates
and optionally installing the step-cli tool.
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.matonb.step.plugins.module_utils.utils import (
    read_json_file,
)


def main():
    """Run the Ansible module."""
    module_args = {
        "config_file": {"type": "str", "required": True}
    }

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    config_file = module.params["config_file"]
    config_data, error = read_json_file(config_file)

    if error:
        module.fail_json(msg=error)

    module.exit_json(changed=False, config=config_data)


if __name__ == "__main__":
    main()
