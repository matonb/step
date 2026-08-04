# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Manage step-ca provisioners.

This Ansible module creates, updates, removes and queries provisioners in a
step-ca certificate authority. It works against both management modes: a CA
that keeps its provisioners in C(ca.json), and one initialised with
C(--remote-management) that keeps them in the CA database and changes them
through the authenticated Admin API.
"""

DOCUMENTATION = r"""
---
module: provisioner
short_description: Interact with step-ca provisioners
version_added: "1.0.0"
description:
  - Creates, updates and removes provisioners in a step-ca certificate authority.
  - >-
    Supports both management modes. A CA initialised with C(--remote-management)
    keeps its provisioners in the CA database and is managed through the Admin
    API, which requires admin credentials and needs the CA to be running. Any
    other CA keeps its provisioners in C(ca.json), which is edited in place and
    requires the service to be restarted or sent SIGHUP.
  - >-
    Supports check mode. Under C(--check) the provisioner list is read and the
    resulting C(changed)/C(restart_required) values are predicted, but no
    provisioner is added, updated or removed and no password is generated.
options:
  admin_cert:
    description:
      - Path to an admin certificate (chain) in PEM format, used to authenticate to the Admin API.
      - Requires I(admin_key). Only used in admin mode.
      - >-
        The admin key must not be encrypted. step loads it without a password
        option and would prompt, so I(admin_password_file) is rejected
        alongside this option.
    required: false
    type: path
    version_added: "1.1.0"
  admin_key:
    description:
      - Path to the private key matching I(admin_cert).
      - Requires I(admin_cert). Only used in admin mode.
    required: false
    type: path
    version_added: "1.1.0"
  admin_password_file:
    description:
      - Path to the file holding the password that decrypts I(admin_provisioner)'s key.
      - Required in admin mode unless I(admin_cert) is used.
    required: false
    type: path
    version_added: "1.1.0"
  admin_provisioner:
    description:
      - Name of the provisioner used to mint admin credentials.
      - Required in admin mode unless I(admin_cert) is used. Without it the step CLI prompts and the task hangs.
    required: false
    type: str
    version_added: "1.1.0"
  admin_subject:
    description:
      - Subject of the CA administrator, as created by C(step ca init --admin-subject) (C(step) by default).
      - Required in admin mode unless I(admin_cert) is used. Without it the step CLI prompts and the task hangs.
    required: false
    type: str
    version_added: "1.1.0"
  ca_config:
    description:
      - Path to the CA configuration file. Defaults to C(ca.json) under I(ca_path).
      - Also used to detect the management mode when I(management_mode) is C(auto).
    required: false
    type: path
    version_added: "1.1.0"
  ca_path:
    description:
      - Optional path to the step CA configuration directory.
      - Sets the STEPPATH environment variable before executing step commands.
    required: false
    type: path
  ca_url:
    description:
      - Optional URL of the step CA.
      - Falls back to the value in the CA's C(defaults.json).
    required: false
    type: str
  context:
    description:
      - Optional step context name to operate in.
    required: false
    type: str
    version_added: "1.1.0"
  debug:
    description:
      - If true, prints the CLI command to stderr before execution for debugging purposes.
    required: false
    type: bool
    default: false
  fingerprint:
    description:
      - Unused and deprecated.
      - >-
        No C(step ca provisioner) subcommand accepts a fingerprint; it applies
        only to C(step ca bootstrap) and C(step ca root). This option is
        accepted for compatibility and has no effect.
      - Deprecated, and will be removed in version 2.0.0. Remove it from your tasks.
    required: false
    type: str
  management_mode:
    description:
      - Which management mode this task expects the CA to be in.
      - >-
        C(auto) reads C(authority.enableAdmin) from the CA configuration.
        C(admin) and C(config) assert a mode rather than force one.
      - >-
        The step CLI always chooses the path itself, based on what the CA
        reports. These values determine whether the module treats the outcome
        as correct and whether it reports I(restart_required); a mismatch
        fails the task.
    required: false
    type: str
    version_added: "1.1.0"
    choices: ['auto', 'admin', 'config']
    default: auto
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
  root:
    description:
      - Path to the PEM file used as the CA root certificate, used to verify I(ca_url).
      - Falls back to the value in the CA's C(defaults.json).
      - >-
        The C(ca_root) alias is deprecated and will be removed in version
        2.0.0; it previously emitted an invalid step flag. Use C(root).
    required: false
    type: path
    version_added: "1.1.0"
    aliases: ['ca_root']
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
      - Provisioner type. Required when creating a provisioner, otherwise acts as a filter.
      - >-
        Creating is supported for C(ACME) and C(JWK) only; other types need
        options this module does not expose and fail with an explanatory
        message. Listing, reconciling and removing work for every type.
    required: false
    type: str
    choices: [JWK, OIDC, AWS, GCP, Azure, ACME, X5C, K8SSA, SSHPOP, SCEP, Nebula]
  x509_min:
    description:
      - Minimum certificate duration for X509 certificates.
      - Valid time units are s = seconds, m = minutes, h = hours.
      - When unset the provisioner inherits the CA's default and the claim is not reconciled.
    required: false
    type: str
  x509_max:
    description:
      - Maximum certificate duration for X509 certificates.
      - Valid time units are s = seconds, m = minutes, h = hours.
      - When unset the provisioner inherits the CA's default and the claim is not reconciled.
    required: false
    type: str
  x509_default:
    description:
      - Default certificate duration for X509 certificates.
      - must be greater than or equal to x509_min.
      - must be less than or equal to x509_max.
      - Valid time units are s = seconds, m = minutes, h = hours.
      - When unset the provisioner inherits the CA's default and the claim is not reconciled.
    required: false
    type: str
author:
  - Brett Maton (@matonb)
"""

EXAMPLES = r"""
- name: Add an ACME provisioner to a ca.json-managed CA
  matonb.step.provisioner:
    ca_path: /etc/step-ca
    name: acme
    run_as: step
    type: ACME
  notify: restart step-ca

- name: Add a JWK provisioner with certificate duration claims
  matonb.step.provisioner:
    ca_path: /etc/step-ca
    name: cicd
    run_as: step
    type: JWK
    x509_default: 36h
    x509_max: 72h
    x509_min: 20m
  register: cicd_provisioner

- name: Manage a provisioner on a remote-management (admin mode) CA
  matonb.step.provisioner:
    admin_password_file: /etc/step-ca/secrets/provisioner_password
    admin_provisioner: admin
    admin_subject: step
    ca_path: /etc/step-ca
    ca_url: https://ca.example.com
    name: acme
    run_as: step
    type: ACME

- name: Remove a provisioner
  matonb.step.provisioner:
    ca_path: /etc/step-ca
    name: acme
    run_as: step
    state: absent
"""

RETURN = r"""
changed:
  description: Whether any changes were made.
  returned: success
  type: bool

generated_password:
  description: The automatically generated password when no password was provided.
  returned: when a password is auto-generated
  type: str

management_mode:
  description: The management mode used, either C(admin) or C(config).
  returned: success
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

restart_required:
  description:
    - Whether step-ca must be restarted or sent SIGHUP for the change to take effect.
    - Always false in admin mode, where Admin API changes are applied immediately.
  returned: success
  type: bool

state:
  description: The desired state of the provisioner as requested.
  returned: success
  type: str

type:
  description: The type of the provisioner (if provided as a filter).
  returned: success
  type: str

updated:
  description: Names of the claim parameters that were reconciled on an existing provisioner.
  returned: when an existing provisioner is updated
  type: list
  elements: str
"""

import traceback
from dataclasses import replace
from subprocess import CompletedProcess
from typing import Optional

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.matonb.step.plugins.module_utils.connection import (
    AdminCredentials,
    ManagementMode,
    StepConnection,
    configured_mode,
    observed_mode,
)
from ansible_collections.matonb.step.plugins.module_utils.process import (
    CommandTimeoutError,
)
from ansible_collections.matonb.step.plugins.module_utils.provisioner import (
    X509_CLAIMS,
    StepProvisionerClient,
    claim_drift,
)
from ansible_collections.matonb.step.plugins.module_utils.utils import PROMPT_PATTERN

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

DEPRECATION_VERSION = "2.0.0"
COLLECTION_NAME = "matonb.step"


def get_argument_spec() -> dict:
    """Return the argument spec for the provisioner module.

    Returns:
        dict: The module's argument specification.
    """
    return {
        "admin_cert": {"type": "path", "required": False},
        # no_log is set explicitly on the admin options: they name files rather
        # than hold secrets, and without this Ansible's heuristic flags the
        # "key" and "password" in their names.
        "admin_key": {"type": "path", "required": False, "no_log": False},
        "admin_password_file": {"type": "path", "required": False, "no_log": False},
        "admin_provisioner": {"type": "str", "required": False},
        "admin_subject": {"type": "str", "required": False},
        "ca_config": {"type": "path", "required": False},
        "ca_path": {"type": "path", "required": False},
        "ca_url": {"type": "str", "required": False},
        "context": {"type": "str", "required": False},
        "debug": {"type": "bool", "required": False, "default": False},
        "fingerprint": {
            "type": "str",
            "required": False,
            "removed_in_version": DEPRECATION_VERSION,
            "removed_from_collection": COLLECTION_NAME,
        },
        "management_mode": {
            "type": "str",
            "choices": ["auto", "admin", "config"],
            "default": "auto",
        },
        "name": {"type": "str", "required": True},
        "password": {"type": "str", "required": False, "no_log": True},
        "root": {
            "type": "path",
            "required": False,
            "aliases": ["ca_root"],
            "deprecated_aliases": [
                {
                    "name": "ca_root",
                    "version": DEPRECATION_VERSION,
                    "collection_name": COLLECTION_NAME,
                }
            ],
        },
        "run_as": {"type": "str", "required": False, "default": None},
        "state": {
            "type": "str",
            "choices": ["present", "absent"],
            "default": "present",
        },
        "type": {"type": "str", "choices": VALID_TYPES, "required": False},
        "x509_min": {"type": "str", "required": False},
        "x509_max": {"type": "str", "required": False},
        "x509_default": {"type": "str", "required": False},
    }


def build_connection(module: AnsibleModule) -> StepConnection:
    """Build the CA connection from module parameters.

    Args:
        module: The Ansible module instance.

    Returns:
        StepConnection: The connection, without admin credentials attached.
    """
    return StepConnection(
        ca_config=module.params.get("ca_config"),
        ca_path=module.params.get("ca_path"),
        ca_url=module.params.get("ca_url"),
        context=module.params.get("context"),
        # Route debug output to the Ansible log; a module must never write to
        # stdout, which Ansible parses as its JSON result.
        logger=module.log if module.params.get("debug") else None,
        root=module.params.get("root"),
        run_as=module.params.get("run_as"),
    )


def build_credentials(module: AnsibleModule) -> AdminCredentials:
    """Build the Admin API credentials from module parameters.

    Args:
        module: The Ansible module instance.

    Returns:
        AdminCredentials: The credentials as supplied, unvalidated.
    """
    return AdminCredentials(
        cert=module.params.get("admin_cert"),
        key=module.params.get("admin_key"),
        password_file=module.params.get("admin_password_file"),
        provisioner=module.params.get("admin_provisioner"),
        subject=module.params.get("admin_subject"),
    )


def resolve_mode(module: AnsibleModule, connection: StepConnection) -> ManagementMode:
    """Decide which management mode to use.

    Args:
        module: The Ansible module instance.
        connection: The connection identifying the CA.

    Returns:
        ManagementMode: The resolved mode.
    """
    requested = module.params["management_mode"]
    if requested != "auto":
        return ManagementMode(requested)

    mode, error = configured_mode(connection)
    if mode is None:
        module.warn(f"Assuming '{ManagementMode.CONFIG.value}' management mode: {error}")
        return ManagementMode.CONFIG

    return mode


def guard_mode(module: AnsibleModule, expected: ManagementMode, result: CompletedProcess) -> ManagementMode:
    """Verify a mutating command took the management path that was expected.

    The step CLI picks the path itself: it uses the Admin API when the CA
    reports it as enabled, and otherwise edits C(ca.json). A mismatch means the
    change did not land where the task assumed it would.

    Args:
        module: The Ansible module instance.
        expected: The mode the module resolved.
        result: The completed step command.

    Returns:
        ManagementMode: The mode step actually used.
    """
    actual = observed_mode(result)
    if actual is expected:
        return actual

    if expected is ManagementMode.ADMIN:
        module.fail_json(
            changed=True,
            msg=(
                f"Expected to manage provisioner '{module.params['name']}' through the Admin API, but step "
                "wrote the change to ca.json instead. The running CA has NOT picked it up, and ca.json has "
                "already been modified on disk, so it may need reverting. step falls back to editing "
                "ca.json when the CA's Admin API reports itself disabled or the CA cannot be reached: "
                "check that step-ca is running and reachable at "
                f"'{module.params.get('ca_url') or 'the configured ca-url'}', that remote management is "
                "enabled on it, and that it has been restarted since ca.json enabled it."
            ),
        )
    else:
        module.warn(
            "step used the Admin API rather than editing ca.json, so this change is already live. "
            "Reporting restart_required as false."
        )

    return actual


def desired_claims(module: AnsibleModule) -> dict:
    """Collect the claim values requested by the task.

    Args:
        module: The Ansible module instance.

    Returns:
        dict: Requested claim values keyed by module parameter name.
    """
    return {spec.param: module.params.get(spec.param) for spec in X509_CLAIMS}


def match_provisioners(provisioners: list, name: str, provisioner_type: Optional[str]) -> list:
    """Select the provisioners a task is addressing.

    Args:
        provisioners: Every provisioner the CA reports.
        name: The requested provisioner name.
        provisioner_type: Optional type filter.

    Returns:
        list: The matching provisioners.
    """
    return [p for p in provisioners if p.name == name and (not provisioner_type or p.type == provisioner_type)]


def apply_absent(
    module: AnsibleModule,
    client: StepProvisionerClient,
    mode: ManagementMode,
    matched: list,
) -> tuple[dict, ManagementMode]:
    """Ensure the provisioner does not exist.

    Args:
        module: The Ansible module instance.
        client: The provisioner client.
        mode: The resolved management mode.
        matched: Provisioners matching the requested name and type.

    Returns:
        Tuple of the result fragment and the mode step actually used.
    """
    if not matched:
        return {"changed": False}, mode

    if module.check_mode:
        return {"changed": True}, mode

    result = client.remove(module.params["name"])
    return {"changed": True}, guard_mode(module, mode, result)


def apply_present(
    module: AnsibleModule,
    client: StepProvisionerClient,
    mode: ManagementMode,
    matched: list,
) -> tuple[dict, ManagementMode]:
    """Ensure the provisioner exists and its managed claims are correct.

    Args:
        module: The Ansible module instance.
        client: The provisioner client.
        mode: The resolved management mode.
        matched: Provisioners matching the requested name and type.

    Returns:
        Tuple of the result fragment and the mode step actually used.
    """
    name = module.params["name"]
    provisioner_type = module.params.get("type")
    claims = desired_claims(module)

    if matched:
        drifted = claim_drift(claims, matched[0].claims)
        if not drifted:
            return {"changed": False}, mode

        fragment = {"changed": True, "updated": drifted}
        if module.check_mode:
            return fragment, mode

        result = client.update(name, claims)
        return fragment, guard_mode(module, mode, result)

    # Only a provisioner that has to be created needs a type; an existing one
    # is already at the desired state and is a no-op.
    if not provisioner_type:
        module.fail_json(msg="Parameter 'type' is required when state is 'present' and the provisioner doesn't exist.")

    if module.check_mode:
        return {"changed": True}, mode

    result, used_password = client.add(
        name=name,
        provisioner_type=provisioner_type,
        claims=claims,
        password=module.params.get("password"),
    )
    fragment = {"changed": True}
    # Only report a password the module invented; echoing one the user supplied
    # would leak it into the play recap for no reason.
    if used_password and module.params.get("password") is None:
        fragment["generated_password"] = used_password

    return fragment, guard_mode(module, mode, result)


def main() -> None:
    """Run the Ansible module."""
    module = AnsibleModule(
        argument_spec=get_argument_spec(),
        required_together=[("admin_cert", "admin_key")],
        supports_check_mode=True,
    )

    name = module.params["name"]
    provisioner_type = module.params.get("type")
    state = module.params["state"]

    if name.startswith("-"):
        module.fail_json(msg=f"Provisioner name '{name}' is invalid: it would be parsed as a step CLI flag.")

    try:
        connection = build_connection(module)
        mode = resolve_mode(module, connection)

        # Attach credentials whenever any were supplied, not only when admin
        # mode was resolved: step chooses the Admin API itself based on what
        # the CA reports, so withholding them on a mismatch makes it prompt.
        credentials = build_credentials(module)
        if mode is ManagementMode.ADMIN or credentials != AdminCredentials():
            credentials.validate()
            connection = replace(connection, admin=credentials)

        client = StepProvisionerClient(connection)
        matched = match_provisioners(client.list(), name, provisioner_type)

        apply = apply_absent if state == "absent" else apply_present
        fragment, effective_mode = apply(module, client, mode, matched)

        # Report the state after the change rather than before it.
        if fragment["changed"] and not module.check_mode:
            matched = match_provisioners(client.list(), name, provisioner_type)

        result = {
            "management_mode": effective_mode.value,
            "name": name,
            "provisioners": [p.to_dict() for p in matched],
            "restart_required": fragment["changed"] and effective_mode is ManagementMode.CONFIG,
            "state": state,
            "type": provisioner_type,
            **fragment,
        }
        module.exit_json(**result)

    except CommandTimeoutError as exc:
        if PROMPT_PATTERN.search(exc.stdout or "") or PROMPT_PATTERN.search(exc.stderr or ""):
            module.fail_json(
                msg=(
                    "The step CLI asked for input, which means a required option is missing. "
                    "In admin mode 'admin_subject', 'admin_provisioner' and 'admin_password_file' "
                    "are all required."
                )
            )
        module.fail_json(msg=str(exc))
    except Exception as exc:
        module.fail_json(msg=str(exc), exception=traceback.format_exc())


if __name__ == "__main__":
    main()
