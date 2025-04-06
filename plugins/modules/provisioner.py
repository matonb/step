"""
Ansible module for managing step-ca provisioners.

This module allows creating, removing, and querying provisioners
in a step-ca certificate authority. It supports different provisioner
types including JWK and ACME.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.matonb.step.plugins.module_utils.provisioner import (
    ACMEProvisioner,
    JWKProvisioner,
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
      - Sets the STEPPATH environment variable before executing step commands.
    required: false
    type: path
  ca_root:
    description:
      - Optional path to the CA root certificate.
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
  password:
    description:
      - Optional password for the provisioner.
      - If not provided when adding a non-ACME provisioner, a secure password will be generated automatically.
      - Not used for ACME provisioners.
    required: false
    type: str
  run_as:
    description:
      - Optional system user to run Step CLI commands as.
      - This should usually be the user that owns the Step CA instance (commonly C(step)).
    required: false
    type: str
    default: null
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
  x509_min:
    description:
      - Minimum certificate duration for X509 certificates.
      - Valid time units are s = seconds, m = minutes, h = hours.
    required: false
    type: str
  x509_max:
    description:
      - Maximum certificate duration for X509 certificates.
      - Valid time units are s = seconds, m = minutes, h = hours.
    required: false
    type: str
  x509_default:
    description:
      - Default certificate duration for X509 certificates.
      - must be greater than or equal to x509_min.
      - must be less than or equal to x509_max.
      - Valid time units are s = seconds, m = minutes, h = hours.
    required: false
    type: str
    default: 36h
author:
  - Brett Maton (@matonb)
"""

RETURN = r"""
changed:
  description: Whether any changes were made (e.g., provisioner removed).
  returned: success
  type: bool

generated_password:
  description: The automatically generated password when no password was provided.
  returned: when a password is auto-generated
  type: str

name:
  description: The name of the provisioner being managed.
  returned: success
  type: str

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
        "password": {
            "type": "str",
            "required": False,
            "no_log": True,
            "description": (
                "Optional password for the provisioner. If not provided when adding a "
                "non-ACME provisioner, a secure password will be generated automatically. "
                "Not used for ACME provisioners."
            ),
        },
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
        "x509_min": {
            "type": "str",
            "required": False,
            "description": "Minimum certificate duration for X509 certificates.",
        },
        "x509_max": {
            "type": "str",
            "required": False,
            "description": "Maximum certificate duration for X509 certificates.",
        },
        "x509_default": {
            "type": "str",
            "required": False,
            "description": "Default certificate duration for X509 certificates.",
        },
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
    password = module.params.get("password")
    provisioner_type = module.params.get("type")
    state = module.params["state"]
    run_as = module.params.get("run_as")
    x509_min = module.params.get("x509_min")
    x509_max = module.params.get("x509_max")
    x509_default = module.params.get("x509_default")

    try:
        context = StepCAContext(
            ca_path=ca_path,
            ca_root=ca_root,
            ca_url=ca_url,
            debug=debug,
            fingerprint=fingerprint,
            run_as=run_as,
            x509_min=x509_min,
            x509_max=x509_max,
            x509_default=x509_default,
        )
        provisioners = context.load_provisioners()

        changed = False
        restart_required = False
        matched = [
            p
            for p in provisioners
            if p.name == name and (not provisioner_type or p.type == provisioner_type)
        ]

        # Store the password used (if generated)
        used_password = None

        if state == "absent" and matched:
            # Remove the provisioner if it exists and state is "absent"
            context.remove_provisioner(name)
            changed = True
            restart_required = True
            # After restart, this provisioner will be gone
            matched = []
        elif state == "present" and not matched and provisioner_type:
            # Create the provisioner if it doesn't exist, state is "present",
            # and provisioner_type is specified
            used_password = context.add_provisioner(
                name=name,
                password=password,
                provisioner_type=provisioner_type,
                x509_min=x509_min,
                x509_max=x509_max,
                x509_default=x509_default,
            )
            changed = True
            restart_required = True

            # After restart, this provisioner will be available
            # Choose the proper concrete class based on the provisioner type
            if provisioner_type == "JWK":
                matched = [JWKProvisioner(name=name, type=provisioner_type)]
            elif provisioner_type == "ACME":
                matched = [ACMEProvisioner(name=name, type=provisioner_type)]
            else:
                module.fail_json(
                    msg=f"Unsupported provisioner type: {provisioner_type}"
                )
        elif state == "present" and not provisioner_type:
            module.fail_json(
                msg="Parameter 'type' is required when state is 'present' and the provisioner doesn't exist."
            )

        result = {
            "changed": changed,
            "restart_required": restart_required,
            "name": name,
            "provisioners": [p.to_dict() for p in matched],
            "state": state,
            "type": provisioner_type,
        }

        # Only include the password in the result if it was generated and not None
        if used_password and password is None:
            result["generated_password"] = used_password

        module.exit_json(**result)
    except Exception as e:
        module.fail_json(msg=str(e))


if __name__ == "__main__":
    main()
