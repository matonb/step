# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Step CA provisioner models and CRUD operations.

This module defines:

- Data models for provisioners, plus the type-specific arguments each one needs
  when it is created.
- :data:`X509_CLAIMS`, the single mapping between module parameters, step CLI
  flags and the claim keys the CA reports, which drives flag rendering and
  drift detection alike.
- :class:`StepProvisionerClient`, which turns those into step CLI invocations.

Writing is identical in both management modes: the commands are the same and the
connection supplies any admin credentials. Reading is not, and :meth:`list`
takes the mode for that reason - see its docstring. Everything else here is
mode-agnostic; see :mod:`connection` for the mode handling itself.
"""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from subprocess import CompletedProcess
from typing import Optional

from .connection import ManagementMode, StepConnection, read_provisioners
from .utils import generate_secure_password, parse_duration, read_json_file, write_secret_file

# Seconds to allow a step command before assuming it is waiting on input that
# will never arrive. Minting an admin credential involves a round trip to the
# CA, so this is generous.
COMMAND_TIMEOUT = 60


@dataclass(frozen=True)
class ClaimSpec:
    """Links a module parameter to its step flag and reported claim key."""

    param: str
    flag: str
    key: str


# The x509 duration claims this collection manages. Adding a claim here is
# enough for it to be sent on add/update and compared for drift.
X509_CLAIMS = (
    ClaimSpec("x509_default", "--x509-default-dur", "defaultTLSCertDuration"),
    ClaimSpec("x509_max", "--x509-max-dur", "maxTLSCertDuration"),
    ClaimSpec("x509_min", "--x509-min-dur", "minTLSCertDuration"),
)


@dataclass(frozen=True)
class AddArguments:
    """Type-specific arguments for C(step ca provisioner add)."""

    args: list[str] = field(default_factory=list)
    password: Optional[str] = None
    secret_file: Optional[str] = None


def claim_flags(desired: dict[str, Optional[str]]) -> list[str]:
    """Render requested claims as step CLI flags.

    Args:
        desired: Requested claim values keyed by module parameter name.
            Entries that are None are left to the CA's own defaults.

    Returns:
        List[str]: Flag/value pairs for the claims that were requested.
    """
    flags: list[str] = []
    for spec in X509_CLAIMS:
        value = desired.get(spec.param)
        if value:
            flags.extend([spec.flag, value])
    return flags


def claim_drift(desired: dict[str, Optional[str]], claims: dict) -> list[str]:
    """Find requested claims whose value on the CA differs.

    Durations are compared numerically because the CA normalises them when it
    serialises: a claim requested as C(5m) is reported as C(5m0s).

    Args:
        desired: Requested claim values keyed by module parameter name.
        claims: The C(claims) object reported for the existing provisioner.

    Returns:
        List[str]: Parameter names that need updating, in table order.

    Raises:
        ValueError: If a requested or reported duration cannot be parsed.
            Treating it as drift instead would update the provisioner on every
            run without ever settling.
    """
    drifted: list[str] = []
    for spec in X509_CLAIMS:
        wanted = desired.get(spec.param)
        if not wanted:
            # Not managed by this task; whatever the CA has is correct.
            continue

        actual = claims.get(spec.key)
        if actual is None:
            # The claim is unset, so the provisioner inherits the authority
            # default rather than the value asked for.
            drifted.append(spec.param)
            continue

        try:
            wanted_ns = parse_duration(wanted)
        except ValueError as exc:
            raise ValueError(f"Invalid value for '{spec.param}': {exc}") from exc

        try:
            actual_ns = parse_duration(str(actual))
        except ValueError as exc:
            raise ValueError(f"The CA reported an unreadable '{spec.key}' for this provisioner: {exc}") from exc

        if wanted_ns != actual_ns:
            drifted.append(spec.param)

    return drifted


@dataclass
class Provisioner(ABC):
    """Base data model for Step CA provisioners."""

    name: str
    type: str
    claims: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a dictionary representation excluding empty optional fields.

        Returns:
            dict: Serialized dictionary of the provisioner.
        """
        result = {
            "name": self.name,
            "type": self.type,
        }
        if self.claims:
            result["claims"] = self.claims
        if self.options:
            result["options"] = self.options
        return result

    @abstractmethod
    def add_arguments(self, password: Optional[str] = None, run_as: Optional[str] = None) -> AddArguments:
        """Build the arguments this provisioner type needs when created.

        Args:
            password: Password supplied by the user, if any.
            run_as: System user the step command will be demoted to, which
                must be able to read any secret file that gets written.

        Returns:
            AddArguments: Extra arguments, the password used, and any
            temporary file the caller must remove.
        """


@dataclass
class JWKProvisioner(Provisioner):
    """Provisioner that uses a JSON Web Key (JWK)."""

    key: dict[str, str] = field(default_factory=dict)
    encrypted_key: str = ""

    def to_dict(self) -> dict:
        """Return dictionary including JWK-specific fields.

        Returns:
            dict: Serialized dictionary including JWK fields.
        """
        result = super().to_dict()
        result["key"] = self.key
        result["encryptedKey"] = self.encrypted_key
        return result

    def add_arguments(self, password: Optional[str] = None, run_as: Optional[str] = None) -> AddArguments:
        """Create the JWK key pair and the password file that encrypts it.

        C(--create) and C(--password-file) are consumed only by the JWK branch
        of C(step ca provisioner add), so they belong here rather than in the
        shared command.

        Args:
            password: Password to encrypt the new key with. A secure password
                is generated when none is supplied.
            run_as: System user that must be able to read the password file.

        Returns:
            AddArguments: The JWK creation flags and the password used.
        """
        actual_password = password if password is not None else generate_secure_password()
        password_file = write_secret_file(actual_password, owner=run_as)
        return AddArguments(
            args=["--create", "--password-file", password_file],
            password=actual_password,
            secret_file=password_file,
        )


@dataclass
class ACMEProvisioner(Provisioner):
    """Provisioner that uses the ACME protocol."""

    def add_arguments(self, password: Optional[str] = None, run_as: Optional[str] = None) -> AddArguments:
        """Return the arguments for an ACME provisioner.

        Args:
            password: Unused; ACME provisioners have no key to encrypt.
            run_as: Unused; no secret file is written.

        Returns:
            AddArguments: An empty argument set.
        """
        return AddArguments()


@dataclass
class GenericProvisioner(Provisioner):
    """A provisioner of a type this collection cannot create.

    Modelling these rather than discarding them keeps C(state: absent) and
    claim reconciliation working for every type the CA reports; only creation
    needs type-specific knowledge.
    """

    def add_arguments(self, password: Optional[str] = None, run_as: Optional[str] = None) -> AddArguments:
        """Refuse to build creation arguments for an unsupported type.

        Args:
            password: Unused.
            run_as: Unused.

        Raises:
            ValueError: Always; this type cannot be created by the collection.
        """
        raise ValueError(
            f"Creating a provisioner of type '{self.type}' is not supported. "
            f"Supported types are: {', '.join(sorted(_PROVISIONER_CLASSES))}."
        )


# Provisioner types this collection can create. Any other type is modelled as a
# GenericProvisioner, so it can still be listed, reconciled and removed.
_PROVISIONER_CLASSES: dict[str, type[Provisioner]] = {
    "ACME": ACMEProvisioner,
    "JWK": JWKProvisioner,
}


def build_provisioner(item: dict) -> Provisioner:
    """Build a provisioner model from one entry of the CA's provisioner list.

    Args:
        item: A decoded provisioner object from C(step ca provisioner list).

    Returns:
        Provisioner: The model for the entry.
    """
    provisioner_type = item.get("type")
    provisioner_class = _PROVISIONER_CLASSES.get(provisioner_type, GenericProvisioner)

    init_args = {
        "name": item.get("name"),
        "type": provisioner_type,
        "claims": item.get("claims") or {},
        "options": item.get("options") or {},
    }
    if provisioner_class is JWKProvisioner:
        init_args["key"] = item.get("key", {})
        init_args["encrypted_key"] = item.get("encryptedKey", "")

    return provisioner_class(**init_args)


@dataclass(frozen=True)
class StepProvisionerClient:
    """Create, read, update and remove provisioners through the step CLI."""

    connection: StepConnection

    # The two readers are defined before list(), which shadows the built-in
    # `list` for the remainder of the class body: a `list[Provisioner]`
    # annotation below it would be evaluated against the method, not the type.
    def _list_from_ca(self) -> list[Provisioner]:
        """Read the provisioners the running CA reports.

        Returns:
            List[Provisioner]: Every provisioner the CA reports.

        Raises:
            RuntimeError: If the command fails or its output is not JSON.
        """
        argv = self.connection.command("ca provisioner list")
        result = self.connection.run(argv, timeout=COMMAND_TIMEOUT)

        try:
            raw_data = json.loads(result.stdout)
        except json.JSONDecodeError as err:
            raise RuntimeError("Failed to parse JSON from step output.") from err

        return [build_provisioner(item) for item in raw_data]

    def _list_from_config(self) -> list[Provisioner]:
        """Read the provisioners recorded in the CA's C(ca.json).

        An unreadable file is an error rather than a fall back to the CA:
        falling back would silently reintroduce the read/write split this
        exists to close.

        Returns:
            List[Provisioner]: Every provisioner in C(authority.provisioners).

        Raises:
            RuntimeError: If C(ca.json) cannot be located, read or understood.
        """
        config_file = self.connection.config_file()
        if not config_file:
            raise RuntimeError(
                "Cannot read provisioners in config mode without knowing where ca.json is. "
                "Set 'ca_path' or 'ca_config' to name the file directly. If this CA is actually "
                "in admin mode, set 'management_mode' to 'admin' and neither is needed."
            )

        config, error = read_json_file(config_file)
        if error:
            raise RuntimeError(f"Cannot read provisioners from '{config_file}': {error}")

        entries, error = read_provisioners(config, config_file)
        if error:
            raise RuntimeError(f"Cannot read provisioners: {error}.")

        return [build_provisioner(item) for item in entries]

    def list(self, mode: ManagementMode) -> list[Provisioner]:
        """Load the current provisioners from wherever this mode stores them.

        The read has to come from the same place the write goes, or the two
        disagree and the module never converges:

        - **Admin mode** keeps provisioners in the CA database and changes them
          through the Admin API, so the CA is the source of truth and
          C(step ca provisioner list) reads it.
        - **Config mode** edits C(ca.json), which the CA only picks up on SIGHUP.
          Reading the CA there would report its *loaded* configuration, so a
          re-run before the reload would not see a provisioner that had just
          been written and would try to create it again.

        Reading the file also means config-mode tasks need no running CA.

        Args:
            mode: The resolved management mode.

        Returns:
            List[Provisioner]: Every provisioner in the relevant source.

        Raises:
            RuntimeError: If the source cannot be read or parsed.
        """
        if mode is ManagementMode.CONFIG:
            return self._list_from_config()
        return self._list_from_ca()

    def add(
        self,
        name: str,
        provisioner_type: str,
        claims: dict[str, Optional[str]],
        password: Optional[str] = None,
    ) -> tuple[CompletedProcess, Optional[str]]:
        """Create a provisioner.

        Args:
            name: Name for the new provisioner.
            provisioner_type: The provisioner type to create.
            claims: Requested claim values keyed by module parameter name.
            password: Password for the provisioner key. Generated when omitted
                and the type needs one.

        Returns:
            Tuple of the completed command and the password used, which is
            None for types that have no key.

        Raises:
            ValueError: If the provisioner type cannot be created.
        """
        provisioner_class = _PROVISIONER_CLASSES.get(provisioner_type, GenericProvisioner)
        provisioner = provisioner_class(name=name, type=provisioner_type)
        # GenericProvisioner raises here, before anything is written.
        extra = provisioner.add_arguments(password=password, run_as=self.connection.run_as)

        try:
            argv = self.connection.command(
                "ca provisioner add",
                name,
                "--type",
                provisioner_type,
                *extra.args,
                *claim_flags(claims),
            )
            result = self.connection.run(argv, timeout=COMMAND_TIMEOUT)
        finally:
            _remove_file(extra.secret_file)

        return result, extra.password

    def update(self, name: str, claims: dict[str, Optional[str]]) -> CompletedProcess:
        """Apply requested claims to an existing provisioner.

        Args:
            name: Name of the provisioner to update.
            claims: Requested claim values keyed by module parameter name.

        Returns:
            subprocess.CompletedProcess: The completed command.
        """
        argv = self.connection.command("ca provisioner update", name, *claim_flags(claims))
        return self.connection.run(argv, timeout=COMMAND_TIMEOUT)

    def remove(self, name: str) -> CompletedProcess:
        """Remove a provisioner.

        Args:
            name: Name of the provisioner to remove.

        Returns:
            subprocess.CompletedProcess: The completed command.
        """
        argv = self.connection.command("ca provisioner remove", name)
        return self.connection.run(argv, timeout=COMMAND_TIMEOUT)


def _remove_file(path: Optional[str]) -> None:
    """Remove a temporary file, ignoring one that has already gone.

    Args:
        path: Path to remove, or None.
    """
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass
