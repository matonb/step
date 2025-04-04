from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.matonb.step.plugins.module_utils.provisioner import (
    StepCAContext,
)

VALID_TYPES = [
    "JWK",
    "OIDC",
    "AWS",
    "GCP",
    "Azure",
    "ACME",
    "X5C",
    "K8SSA",
    "SSHPOP",
    "SCEP",
    "Nebula",
]

DOCUMENTATION = r"""
---
module: provisioner
short_description: Interact with step-ca provisioners
description:
  - Loads and filters provisioners from `step ca provisioner list`.
options:
  ca_path:
    description:
      - Optional path to the step CA configuration directory.
    required: false
    type: path
  ca_url:
    description:
      - Optional URL of the step CA.
    required: false
    type: str
  debug:
    description:
      - If true, prints the CLI command before execution for debugging purposes.
    required: false
    type: bool
    default: false
  fingerprint:
    description:
      - Optional fingerprint for CA root.
    required: false
    type: str
  name:
    description:
      - Name of the provisioner.
    required: true
    type: str
  run_as:
    description:
      - Optional system user to run Step CLI commands as.
      - This should usually be the user that owns the Step CA instance (commonly C(step)).
    required: false
    type: str
  state:
    description:
      - Desired state.
    required: false
    type: str
    choices: ['present', 'absent']
    default: present
  type:
    description:
      - Optional filter by type.
    required: false
    type: str
    choices: [JWK, OIDC, AWS, GCP, Azure, ACME, X5C, K8SSA, SSHPOP, SCEP, Nebula]
author: you
"""

RETURN = r"""
provisioners:
  description: List of provisioners that matched the specified name and (optional) type.
  returned: success
  type: list
  elements: dict

provisioners_after:
  description: Full list of provisioners after any state changes (e.g., removal).
  returned: success
  type: list
  elements: dict

provisioners_before:
  description: Full list of provisioners before any changes.
  returned: success
  type: list
  elements: dict

state:
  description: The desired state of the provisioner as requested.
  returned: success
  type: str

type:
  description: The type of the provisioner (if provided as a filter).
  returned: success
  type: str

name:
  description: The name of the provisioner being managed.
  returned: success
  type: str

changed:
  description: Whether any changes were made (e.g., provisioner removed).
  returned: success
  type: bool
"""


def get_argument_spec() -> dict:
    """Return the argument spec for the provisioner module."""
    return {
        "ca_path": {
            "type": "path",
            "required": False,
            "description": "Sets the STEPPATH environment variable before executing step commands.",
        },
        "ca_root": {"type": "path", "required": False},
        "ca_url": {"type": "str", "required": False},
        "debug": {
            "type": "bool",
            "required": False,
            "default": False,
            "description": "Prints the step command before execution for debugging.",
        },
        "fingerprint": {"type": "str", "required": False},
        "name": {"type": "str", "required": True},
        "run_as": {
            "type": "str",
            "required": False,
            "default": None,
            "description": (
                "Optional system user to run Step CLI commands as. "
                "This should usually be the user that owns the Step CA instance (commonly 'step')."
            ),
        },
        "state": {
            "type": "str",
            "choices": ["present", "absent"],
            "default": "present",
        },
        "type": {"type": "str", "choices": VALID_TYPES, "required": False},
    }


def main() -> None:
    """Main entry point for the provisioner Ansible module."""
    module = AnsibleModule(argument_spec=get_argument_spec(), supports_check_mode=True)

    name = module.params["name"]
    ca_path = module.params.get("ca_path")
    ca_root = module.params.get("ca_root")
    ca_url = module.params.get("ca_url")
    debug = module.params.get("debug", False)
    fingerprint = module.params.get("fingerprint")
    provisioner_type = module.params.get("type")
    state = module.params["state"]
    run_as = module.params.get("run_as")

    try:
        context = StepCAContext(
            ca_path=ca_path,
            ca_root=ca_root,
            ca_url=ca_url,
            debug=debug,
            fingerprint=fingerprint,
            run_as=run_as,
        )
        provisioners_before = context.load_provisioners()

        changed = False
        provisioners_after = provisioners_before
        matched = [
            p
            for p in provisioners_before
            if p.name == name and (not provisioner_type or p.type == provisioner_type)
        ]

        if state == "absent" and matched:
            context.remove_provisioner(name)
            changed = True
            provisioners_after = context.load_provisioners()
            matched = []

        module.exit_json(
            changed=changed,
            name=name,
            provisioners_after=[p.to_dict() for p in provisioners_after],
            provisioners_before=[p.to_dict() for p in provisioners_before],
            provisioners=[p.to_dict() for p in matched],
            state=state,
            type=provisioner_type,
        )
    except Exception as e:
        module.fail_json(msg=str(e))


if __name__ == "__main__":
    main()
