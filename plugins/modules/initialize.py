# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Initialize a Step CA instance."""

DOCUMENTATION = r"""
---
module: initialize
short_description: Initialize a Step CA instance
version_added: "1.0.0"
description:
  - This module initializes a new Step CA instance with the specified configuration.
  - It can create standalone, linked, or hosted deployments.
  - >-
    Passing C(remote_management) enables the Admin API, which stores
    provisioners in the CA database instead of C(ca.json) and creates a super
    administrator. It requires a database, so it cannot be combined with
    C(no_db), and C(admin_subject) is only valid alongside it.
  - >-
    Running against a CA that is already initialized reports C(ok) and changes
    nothing, so a play containing this task can be re-run. Anything that is
    neither an empty directory nor a working CA fails instead, since
    initializing over it could destroy a PKI. I(force) discards whatever is
    there.
  - >-
    Whether a CA is complete is decided by the CA, not by a list of filenames
    kept in this module: C(config/ca.json) has to parse, and every file it
    names - C(root), C(crt), C(key), C(federatedRoots) and the C(ssh) keys -
    has to be present and non-empty. Relative entries are resolved against
    I(path). Deployments that keep less on disk, such as a registration
    authority or a C(linked) deployment, are therefore recognized without this
    module having to know what they write.
  - >-
    C(config/defaults.json) is not part of that test. step-ca is started with
    C(ca.json) and never reads it, so a CA without it is initialized and
    working. It is not worthless, though - it carries the defaults the step CLI
    and M(matonb.smallstep.provisioner) fall back on for C(ca_url) and C(root) - so
    a CA reported C(ok) without it can still fail a later task that relies on
    those. Restore the file; do not reinitialize the CA for it.
  - >-
    The ways of being unfinished are reported differently. A C(ca.json) that
    cannot be read, or key material this task cannot see, is a reading problem
    rather than a CA problem, so the task says so and does not suggest
    I(force). A CA missing files its configuration names may be half built, and
    there starting again is a legitimate remedy.
  - >-
    I(pki) is the exception, since C(step ca init --pki) writes no C(ca.json)
    to consult. There the certificates and keys a PKI has are checked directly.
  - >-
    I(force) deletes the files C(step ca init) creates, which is not
    necessarily every file a given deployment has. It is a way to start again,
    not a way to clear up after an arbitrary configuration.
options:
  acme:
    description:
      - Create a default ACME provisioner.
      - Requires a database, so it cannot be combined with I(no_db).
    required: false
    type: bool
  address:
    description:
      - The address and port the new CA will listen on, for example C(0.0.0.0:443).
    required: false
    type: str
  admin_subject:
    description:
      - Subject of the first super administrator. Defaults to C(step).
      - Only valid when I(remote_management) is enabled.
    required: false
    type: str
  authority:
    description:
      - The name that will serve as the authority name for the context.
    required: false
    type: str
  context:
    description:
      - The name of the context for the new authority.
    required: false
    type: str
  credentials_file:
    description:
      - Path to the registration authority credentials file.
    required: false
    type: path
  debug:
    description:
      - If true, prints the step command to stderr before execution for debugging purposes.
    required: false
    type: bool
    default: false
  deployment_type:
    description:
      - The deployment type to use.
      - >-
        C(standalone) is an instance of step-ca that does not connect to any
        cloud services; you manage the authority keys and configuration
        yourself.
      - >-
        C(linked) is an instance with locally managed keys that connects to a
        Certificate Manager account for provisioner management, alerting,
        reporting and revocation.
      - C(hosted) is a fully managed instance run by smallstep.
    required: false
    type: str
    choices: ['standalone', 'linked', 'hosted']
    default: standalone
  dns:
    description:
      - The DNS names or IP addresses of the new CA.
    required: false
    type: list
    elements: str
  force:
    description:
      - Replace any existing certificates, secrets and configuration found at I(path).
      - Without this the module fails rather than overwrite an existing CA.
      - >-
        This deletes C(secrets/root_ca_key), which cannot be regenerated:
        everything the old CA issued becomes unverifiable and the trust chain
        has to be rebuilt from scratch. Nothing is backed up. Under C(--check)
        the deletion is reported but not performed.
    required: false
    type: bool
    default: false
  helm:
    description:
      - Generate a Helm values YAML to be used with the step-certificates chart.
      - Not implemented; supplying it fails the task.
    required: false
    type: bool
  issuer:
    description:
      - The registration authority issuer URL, used with I(ra).
    required: false
    type: str
  issuer_fingerprint:
    description:
      - The fingerprint of the registration authority issuer CA certificate.
    required: false
    type: str
  issuer_provisioner:
    description:
      - The name of the provisioner used with the registration authority issuer.
    required: false
    type: str
  key:
    description:
      - Path to an existing private key file for the root certificate authority.
      - Must be supplied together with I(root).
    required: false
    type: path
  key_password_file:
    description:
      - Path to the file containing the password that decrypts the existing root certificate key.
    required: false
    type: path
  kms:
    description:
      - The key management service to use for generating and storing keys.
    required: false
    type: str
    choices: ['azurekms']
  kms_intermediate:
    description:
      - The KMS URI used to generate the intermediate certificate key.
    required: false
    type: str
  kms_root:
    description:
      - The KMS URI used to generate the root certificate key.
    required: false
    type: str
  kms_ssh_host:
    description:
      - The KMS URI used to generate the key that signs SSH host certificates.
    required: false
    type: str
  kms_ssh_user:
    description:
      - The KMS URI used to generate the key that signs SSH user certificates.
    required: false
    type: str
  name:
    description:
      - The name of the new PKI.
    required: true
    type: str
  no_db:
    description:
      - Initialize the CA without a database.
      - Incompatible with I(remote_management) and I(acme), which both require one.
    required: false
    type: bool
  password_file:
    description:
      - Path to the file containing the password used to encrypt the keys.
    required: true
    type: path
  path:
    description:
      - Where step stores its configuration, state and Certificate Authority data.
      - Sets the STEPPATH environment variable for the step command.
    required: true
    type: path
  pki:
    description:
      - Generate only the PKI, without the CA configuration.
    required: false
    type: bool
  profile:
    description:
      - The name that will serve as the profile name for the context.
    required: false
    type: str
  provisioner:
    description:
      - The name of the first provisioner.
    required: false
    type: str
    default: admin
  provisioner_password_file:
    description:
      - Path to the file containing the password used to encrypt the provisioner key.
    required: true
    type: path
  ra:
    description:
      - The type of registration authority to create.
    required: false
    type: str
    choices: ['StepCAS', 'CloudCAS']
  remote_management:
    description:
      - Enable the Admin API so provisioners are managed remotely rather than in C(ca.json).
      - Requires a database, so it cannot be combined with I(no_db).
    required: false
    type: bool
  root:
    description:
      - Path to an existing PEM file to be used as the root certificate authority.
      - Must be supplied together with I(key).
    required: false
    type: path
  ssh:
    description:
      - Create keys for signing SSH certificates.
    required: false
    type: bool
  with_ca_url:
    description:
      - The URI of the Step Certificate Authority to write into C(defaults.json).
    required: false
    type: str
author:
  - Brett Maton (@matonb)
"""

EXAMPLES = r"""
- name: Initialize a standalone Step CA
  matonb.smallstep.initialize:
    name: "My CA"
    path: "/etc/step-ca"
    password_file: "/path/to/password"
    provisioner_password_file: "/path/to/provisioner_password"

- name: Initialize a Step CA with remote management (admin mode)
  matonb.smallstep.initialize:
    admin_subject: step
    name: "My CA"
    path: "/etc/step-ca"
    password_file: "/path/to/password"
    provisioner_password_file: "/path/to/provisioner_password"
    remote_management: true
"""

RETURN = r"""
admin_subject:
  description:
    - >-
      Subject of the super administrator, or null for a CA with no Admin API.
      Whichever the task supplied, or C(step) where I(admin_subject) was left
      out and the CA is in admin mode.
    - >-
      Derived the same way whether the CA was just created or was already
      there, so re-running the task reports the same value. It is not read back
      from the host: an existing CA's administrator lives in the CA database
      rather than in C(ca.json).
  returned: success
  type: str

changed:
  description:
    - Whether the CA was initialized.
    - False when it was already initialized and I(force) was not set.
  returned: always
  type: bool

management_mode:
  description:
    - How provisioners will be managed, either C(admin) or C(config).
    - >-
      On an already-initialized CA this is read from C(authority.enableAdmin)
      in the CA's own C(ca.json), so it describes the CA on disk rather than
      what the task asked for. A C(--pki) directory has no C(ca.json), so there
      it is the mode the task asked for.
  returned: success
  type: str

msg:
  description: What was done, or why nothing needed doing.
  returned: success
  type: str
"""

import os
import pathlib
import re
import stat
from typing import Any, Optional

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.matonb.smallstep.plugins.module_utils.connection import read_authority
from ansible_collections.matonb.smallstep.plugins.module_utils.process import (
    CommandTimeoutError,
    run_command,
)
from ansible_collections.matonb.smallstep.plugins.module_utils.utils import read_json_file

# The files `step ca init` creates. Two jobs only: telling an empty directory
# from one holding something, and naming what `force` deletes. Whether a CA is
# *complete* is a question for its own ca.json - see assess_ca().
CA_FILE_NAMES = (
    "certs/intermediate_ca.crt",
    "certs/root_ca.crt",
    "config/ca.json",
    "config/defaults.json",
    "secrets/intermediate_ca_key",
    "secrets/root_ca_key",
)

# Keys in ca.json naming a file step-ca opens at startup. Both `root` and
# `federatedRoots` are multiString upstream, accepting a bare string or a list,
# so both are read either way.
#
# `db.dataSource` is deliberately absent: step-ca creates the database on first
# start, so a config-mode CA that has never run does not have one and requiring
# it would fail a working CA.
#
# The `templates` block `--ssh` writes is deliberately absent too. Those files
# are real, but leaving them out errs towards calling a CA complete, and erring
# the other way is what made this module unusable for RA and linked deployments
# in the first place.
CONFIG_PATH_KEYS = ("crt", "federatedRoots", "key", "root")
SSH_PATH_KEYS = ("hostKey", "userKey")
AUTHORITY_PATH_KEYS = ("credentialsFile",)

# A value carrying a URI scheme is not a path on this host. `--kms` and friends
# put things like "azurekms:name=intermediate;vault=my-vault" in `key` and in
# the ssh keys, and joining that onto the CA directory produced a filename that
# could never exist - so a perfectly healthy KMS-backed CA was reported broken
# and its operator advised to delete the root key. An absolute path starts with
# a separator and a relative one cannot reach a colon without passing one, so
# nothing legitimate matches.
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

# What assess_ca() found at the CA path.
CA_ABSENT = "absent"
CA_COMPLETE = "complete"
CA_INCOMPLETE = "incomplete"
CA_UNREADABLE = "unreadable"

# Offered as the way out, so it has to say what taking it costs.
# remove_ca_files deletes secrets/root_ca_key, which cannot be regenerated, and
# the refusal reaches operators of CAs that may be perfectly healthy.
FORCE_ADVICE = (
    "Use force: true to discard what is there and start again. That deletes the root key, "
    "which cannot be recovered, and invalidates every certificate this CA has ever issued."
)


def get_argument_spec() -> dict[str, dict[str, Any]]:
    """Return the argument specification for the initialize module.

    Option descriptions live in DOCUMENTATION, which is the only place Ansible
    surfaces them to users.

    Returns:
        Dict[str, Dict[str, Any]]: The module's argument specification
    """
    return {
        "acme": {"type": "bool"},
        "address": {"type": "str"},
        "admin_subject": {"type": "str"},
        "authority": {"type": "str"},
        "context": {"type": "str"},
        "credentials_file": {"type": "path"},
        "debug": {"type": "bool", "default": False},
        "deployment_type": {
            "type": "str",
            "choices": ["standalone", "linked", "hosted"],
            "default": "standalone",
        },
        "dns": {"type": "list", "elements": "str"},
        "force": {"type": "bool", "default": False},
        "helm": {"type": "bool"},
        "issuer": {"type": "str"},
        "issuer_fingerprint": {"type": "str"},
        "issuer_provisioner": {"type": "str"},
        "key": {"type": "path"},
        "key_password_file": {"type": "path", "no_log": False},
        "kms": {"type": "str", "choices": ["azurekms"]},
        "kms_intermediate": {"type": "str"},
        "kms_root": {"type": "str"},
        "kms_ssh_host": {"type": "str"},
        "kms_ssh_user": {"type": "str"},
        "name": {"type": "str", "required": True},
        "no_db": {"type": "bool"},
        # The *_password_file options name a file rather than hold a secret;
        # no_log is set explicitly so Ansible's name-based heuristic does not
        # flag them.
        "password_file": {"type": "path", "required": True, "no_log": False},
        "path": {"type": "path", "required": True},
        "pki": {"type": "bool"},
        "profile": {"type": "str"},
        "provisioner": {"type": "str", "default": "admin"},
        "provisioner_password_file": {"type": "path", "required": True, "no_log": False},
        "ra": {"type": "str", "choices": ["StepCAS", "CloudCAS"]},
        "remote_management": {"type": "bool"},
        "root": {"type": "path"},
        "ssh": {"type": "bool"},
        "with_ca_url": {"type": "str"},
    }


def build_initialize_command(params: dict[str, Any]) -> list[str]:
    """Build the step CA initialize command from module parameters.

    Args:
        params: The module parameters

    Returns:
        List[str]: The command as a list of arguments
    """
    cmd = ["step", "ca", "init"]

    # Process string parameters with values
    param_keys = [
        "address",
        "admin_subject",
        "authority",
        "context",
        "credentials_file",
        "deployment_type",
        "issuer",
        "issuer_fingerprint",
        "issuer_provisioner",
        "key",
        "key_password_file",
        "kms",
        "kms_intermediate",
        "kms_root",
        "kms_ssh_host",
        "kms_ssh_user",
        "name",
        "password_file",
        "profile",
        "provisioner",
        "provisioner_password_file",
        "ra",
        "root",
        "with_ca_url",
    ]

    # Add parameters with values
    for key in param_keys:
        if params.get(key):
            value = str(params[key]).strip()
            if value:
                cmd.extend([f"--{key.replace('_', '-')}", value])

    # Add boolean flag parameters
    boolean_flags = {
        "acme": "--acme",
        "no_db": "--no-db",
        "pki": "--pki",
        "remote_management": "--remote-management",
        "ssh": "--ssh",
    }

    for param, flag in boolean_flags.items():
        if params.get(param):
            cmd.append(flag)

    # Process DNS entries
    if params.get("dns"):
        for dns_entry in params["dns"]:
            cmd.extend(["--dns", dns_entry])

    return cmd


def ca_file_paths(step_path: str) -> list[str]:
    """Return the full paths of the files C(step ca init) creates.

    Args:
        step_path: The path to the Step CA directory.

    Returns:
        List[str]: The paths, in a stable order.
    """
    return [os.path.join(step_path, name) for name in CA_FILE_NAMES]


def pki_file_paths(step_path: str) -> list[str]:
    """Return the files C(step ca init --pki) creates.

    C(--pki) writes the PKI and stops there, leaving no C(ca.json) or
    C(defaults.json) (C(certificates/pki/pki.go), guarded by C(pkiOnly)). It is
    the one case with no configuration to consult, so it is judged against a
    fixed list - justified here by there being nothing to ask, not by
    convenience.

    Args:
        step_path: The path to the Step CA directory.

    Returns:
        List[str]: The paths, in a stable order.
    """
    return [os.path.join(step_path, name) for name in CA_FILE_NAMES if not name.startswith("config/")]


def configured_paths(config: dict[str, Any], step_path: str) -> list[str]:
    """Return every file path a C(ca.json) names, resolved against C(step_path).

    This is what makes completeness a question for the CA rather than for this
    module. A registration authority owns no root key, and a linked deployment
    keeps its keys elsewhere, so any fixed list of filenames is wrong for
    somebody. What a CA cannot do without is whatever its own configuration
    tells step-ca to open.

    Deliberately not C(db.dataSource): step-ca creates the database itself on
    first start, so a valid new CA has none and requiring it would fail a CA
    that works.

    Args:
        config: A parsed C(ca.json).
        step_path: The path to the Step CA directory, used to resolve relative
            entries.

    Returns:
        List[str]: Absolute paths, deduplicated, in a stable order.
    """
    named: list[str] = []

    for key in CONFIG_PATH_KEYS:
        named.extend(_path_values(config.get(key)))

    for block, keys in ((config.get("ssh"), SSH_PATH_KEYS), (config.get("authority"), AUTHORITY_PATH_KEYS)):
        if isinstance(block, dict):
            for key in keys:
                named.extend(_path_values(block.get(key)))

    # step-ca runs with WorkingDirectory set to STEPPATH and is handed a
    # relative config path (roles/ca_server/templates/unit.j2), so a relative
    # entry here means relative to the CA directory, not to wherever Ansible
    # happens to be.
    resolved = [path if os.path.isabs(path) else os.path.join(step_path, path) for path in named]
    return list(dict.fromkeys(resolved))


def _path_values(value: Any) -> list[str]:
    """Return the filesystem paths in one ca.json entry.

    Upstream types several of these as multiString, which unmarshals from a
    bare string or from a list of them, so both shapes are read. Anything that
    is not a path on this host - a KMS URI, a number, a nested object - is
    dropped rather than guessed at.

    Args:
        value: Whatever the key held.

    Returns:
        List[str]: The paths, unresolved.
    """
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, str) and item and not _URI_SCHEME.match(item)]


def unusable_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    """Return those of C(paths) step-ca could not open, split by why.

    The two want opposite advice, so they are kept apart. A file that is not
    there may mean a half-built CA, where starting again is reasonable. A file
    this task cannot see - C(secrets/) traversed as the wrong user, most often -
    says nothing about the CA at all, and answering it with C(force) would
    delete a healthy root key over a permission problem.

    Empty counts as missing, for the reason the unit file uses
    C(ConditionFileNotEmpty): a truncated key is not a key, and a CA whose root
    certificate is zero bytes does not start.

    Args:
        paths: Absolute paths to check.

    Returns:
        Tuple of the missing or empty paths and the unreadable ones, each in
        the order given.
    """
    missing: list[str] = []
    unreadable: list[str] = []

    for path in paths:
        try:
            # os.path.isfile() reports False for a permission error exactly as
            # it does for a file that is not there, and stat'ing once avoids a
            # file disappearing between the check and the size.
            info = os.stat(path)
        except FileNotFoundError:
            missing.append(path)
        except OSError:
            unreadable.append(path)
        else:
            if not (stat.S_ISREG(info.st_mode) and info.st_size > 0):
                missing.append(path)

    return missing, unreadable


def _assess_pki(step_path: str) -> tuple[str, Optional[str], Optional[str]]:
    """Assess a directory C(step ca init --pki) wrote.

    The one case with no configuration to consult, so a fixed list is all there
    is. There is no C(ca.json), and so no management mode to report either.

    Args:
        step_path: The path to the Step CA directory.

    Returns:
        Tuple shaped as :func:`assess_ca` returns.
    """
    missing, unreadable = unusable_paths(pki_file_paths(step_path))
    if unreadable:
        return CA_UNREADABLE, None, ("a --pki directory holds files this task cannot read: " + ", ".join(unreadable))
    if missing:
        return CA_INCOMPLETE, None, ("a --pki directory is missing " + ", ".join(missing))
    return CA_COMPLETE, None, None


def assess_ca(step_path: str, params: dict[str, Any]) -> tuple[str, Optional[str], Optional[str]]:
    """Decide whether C(step_path) already holds a CA, and whether it works.

    Four answers, because the ways of being unfinished want opposite advice. A
    C(ca.json) that cannot be read, or key material this task cannot see, is
    repairable and no reason to touch the CA. A CA missing the files its
    configuration names may be half built, and starting again is a legitimate
    remedy there.

    Args:
        step_path: The path to the Step CA directory.
        params: The module parameters.

    Returns:
        Tuple of the state (one of C(CA_ABSENT), C(CA_COMPLETE),
        C(CA_UNREADABLE), C(CA_INCOMPLETE)), the management mode when that can
        be read, and what is wrong when it cannot.
    """
    if not find_existing_ca_files(step_path):
        return CA_ABSENT, None, None

    config_file = os.path.join(step_path, "config", "ca.json")

    # Keyed on there being no configuration rather than on the request. A
    # directory holding a full CA gets read like one even when the task asked
    # for --pki, so no single option can switch every integrity check off.
    if params.get("pki") and not os.path.exists(config_file):
        return _assess_pki(step_path)

    config, error = read_json_file(config_file)
    if error:
        # Missing entirely is a different thing from unreadable: files are here
        # but the configuration that describes them is not, which is what a run
        # interrupted part-way through looks like.
        state = CA_INCOMPLETE if not os.path.exists(config_file) else CA_UNREADABLE
        return state, None, error

    authority, error = read_authority(config, config_file)
    if error:
        return CA_UNREADABLE, None, error

    missing, unreadable = unusable_paths(configured_paths(config, step_path))
    if unreadable:
        return CA_UNREADABLE, None, ("config/ca.json names files this task cannot read: " + ", ".join(unreadable))
    if missing:
        return CA_INCOMPLETE, None, ("config/ca.json names files that are missing or empty: " + ", ".join(missing))

    return CA_COMPLETE, ("admin" if authority.get("enableAdmin", False) else "config"), None


def default_admin_subject(params: dict[str, Any], mode: str) -> Optional[str]:
    """Return the subject of the super administrator for a CA in C(mode).

    Both the initializing and the already-initialized paths report this, and
    they have to agree: a value that changed between the first and second run
    of the same task would break any play that registers the result.

    The mode decides first, not the request. Only a CA with the Admin API has a
    super administrator to name, so asking for one against a config-mode CA
    reports None rather than echoing back a subject that does not exist there.
    On the initializing path the two cannot disagree - validate_admin_options
    rejects I(admin_subject) without I(remote_management) - so this only bites
    on the already-initialized path, which is where it matters.

    Args:
        params: The module parameters.
        mode: The management mode the CA is in, "admin" or "config".

    Returns:
        Optional[str]: The subject, or None for a CA with no Admin API.
    """
    if mode != "admin":
        return None
    return params.get("admin_subject") or "step"


def find_existing_ca_files(step_path: str) -> list[str]:
    """Report which of the CA's files are already present.

    Detection only. Deletion is :func:`remove_ca_files`, kept separate so that
    the caller can decide - the two used to be one function, which meant asking
    whether a CA existed destroyed it.

    Args:
        step_path: The path to the Step CA directory.

    Returns:
        List[str]: The paths that exist, empty if the directory holds no CA.
    """
    return [path for path in ca_file_paths(step_path) if os.path.exists(path)]


def remove_ca_files(step_path: str) -> None:
    """Delete the files C(step ca init) creates.

    Irreversible: C(secrets/root_ca_key) cannot be regenerated, and everything
    the CA ever issued becomes unverifiable without it. Only ever call this
    when C(force) was asked for and the module is not in check mode.

    Args:
        step_path: The path to the Step CA directory.
    """
    for path in ca_file_paths(step_path):
        pathlib.Path(path).unlink(missing_ok=True)


def validate_admin_options(module: AnsibleModule) -> None:
    """Reject option combinations that step itself rejects.

    Checking here means the task fails with a clear message instead of
    spawning step only to have it exit non-zero.

    Args:
        module: The Ansible module instance
    """
    if module.params.get("remote_management") and module.params.get("no_db"):
        module.fail_json(msg="'remote_management' requires a database and cannot be combined with 'no_db'.")

    if module.params.get("admin_subject") and not module.params.get("remote_management"):
        module.fail_json(msg="'admin_subject' is only supported when 'remote_management' is enabled.")


def run_step_ca_initialize(module: AnsibleModule) -> None:
    """Run the step CA initialize command with provided parameters.

    Args:
        module: The Ansible module instance

    Raises:
        RuntimeError: If the initialization fails
    """
    timeout = 15
    command = build_initialize_command(module.params)
    module.log("Executing: " + " ".join(command))

    try:
        result = run_command(
            command=command,
            timeout=timeout,
            logger=module.log if module.params.get("debug") else None,
            env_vars={"STEPPATH": module.params["path"]},
            check=False,  # We'll handle the return code ourselves
        )

        if result.returncode != 0:
            module.fail_json(msg=f"Step CA initialization failed: {result.stderr}")

        return

    except CommandTimeoutError as exc:
        # Handle timeout with potential prompt detection
        prompt_pattern = r"(Please enter|Would you like to|\[y/n\])"
        if re.search(prompt_pattern, exc.stdout or ""):
            module.fail_json(msg="Detected user input prompt")
        module.fail_json(msg=f"Step CA initialization timed out after {timeout} seconds.")

    except FileNotFoundError as exc:
        module.fail_json(msg=f"Command not found: {str(exc)}")

    except OSError as exc:
        # Handle OS-related errors
        module.fail_json(msg=f"OS error occurred: {str(exc)}")


def main() -> None:
    """Run the Ansible module."""
    module = AnsibleModule(argument_spec=get_argument_spec(), supports_check_mode=True)

    step_path = module.params["path"]

    if module.params["helm"]:
        module.fail_json(msg="Helm support is not yet implemented.")

    validate_admin_options(module)

    # Provisioners of a remote-management CA live in the CA database and are
    # managed through the Admin API; every other CA keeps them in ca.json.
    management_mode = "admin" if module.params.get("remote_management") else "config"
    admin_subject = default_admin_subject(module.params, management_mode)

    state, observed, detail = assess_ca(step_path, module.params)

    if state != CA_ABSENT and not module.params["force"]:
        # A working CA is the desired state already, so say so rather than
        # failing: a play containing this task could otherwise only ever be run
        # once. What "working" means is the CA's own account of itself, not a
        # list of filenames kept here - see assess_ca().
        if state == CA_COMPLETE:
            mode = observed or management_mode
            module.exit_json(
                changed=False,
                msg="Step CA is already initialized.",
                # Derived exactly as it is on the initializing path, so the
                # same task reports the same subject every run. It is the
                # request plus the same default, not a read-back: the CA's real
                # administrator lives in the CA database, not in ca.json.
                admin_subject=default_admin_subject(module.params, mode),
                management_mode=mode,
            )

        if state == CA_UNREADABLE:
            # Deliberately not FORCE_ADVICE. Every way of reaching this - a
            # truncated write, a bad hand-edit, the wrong user - is a problem
            # with reading, not with the CA, and answering it by deleting the
            # root key would be advice to destroy a possibly healthy CA to
            # clear a syntax error or a permission bit.
            #
            # It does not claim the CA is otherwise sound: when ca.json will
            # not parse there is nothing to check the key material against, so
            # this says only that the task changed nothing.
            module.fail_json(
                msg=(
                    f"{step_path} holds a CA this task cannot read: {detail}.\n"
                    "config/ca.json has to be readable JSON holding an 'authority' object, and the "
                    "files it names have to be readable by whoever runs this task - check 'become' "
                    "and 'run_as' before assuming the CA is at fault. Nothing has been changed."
                )
            )

        module.fail_json(
            msg=(
                f"{step_path} holds something that is not a working CA: {detail}.\n"
                "Restore the missing files if you know where they went - that keeps the existing "
                "CA and everything it has issued.\n" + FORCE_ADVICE
            )
        )

    # Nothing above this line modifies anything, and nothing below it may run
    # under check mode: with force: true the next step deletes the CA's private
    # keys. Detection and deletion used to be one call placed above this guard,
    # so a --check run destroyed the CA and then reported what it "would" do.
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg=(
                "Check mode: the existing CA would be deleted and Step CA reinitialized"
                if state != CA_ABSENT
                else "Check mode: Step CA would be initialized"
            ),
            admin_subject=admin_subject,
            management_mode=management_mode,
        )

    # Keyed on force rather than on what was detected: find_existing_ca_files
    # uses os.path.exists, which is False for a symlink whose target is gone,
    # and step would then meet a directory it expected to be empty. Unreachable
    # without force, because the fail_json above has already returned.
    if module.params["force"]:
        remove_ca_files(step_path)

    # Run step CA initialization
    try:
        run_step_ca_initialize(module)
        # Exit with success message
        module.exit_json(
            changed=True,
            msg="Step CA initialization completed successfully.",
            admin_subject=admin_subject,
            management_mode=management_mode,
        )
    except Exception as exc:
        module.fail_json(msg=f"Unexpected error: {str(exc)}")


if __name__ == "__main__":
    main()
