"""
This module defines dataclasses and helper classes for managing
Step CA provisioners.

It includes:
- Data models for general provisioners and specific types like JWK and ACME.
- A StepCAContext class to execute step CLI commands with CA-specific
  configuration.
- CLI interactions that support user impersonation, environment overrides,
  and debugging.

Designed for use in Ansible modules to automate provisioning in Step CA
environments.
"""

import json
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type

from .process import run_command_as_user


@dataclass
class Provisioner:
    """Base data model for Step CA provisioners."""

    name: str
    type: str
    claims: Dict = field(default_factory=dict)
    options: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
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


@dataclass
class JWKProvisioner(Provisioner):
    """Provisioner that uses a JSON Web Key (JWK)."""

    key: Dict[str, str] = field(default_factory=dict)
    encryptedKey: str = ""

    def to_dict(self) -> Dict:
        """Return dictionary including JWK-specific fields.

        Returns:
            dict: Serialized dictionary including JWK fields.
        """
        result = super().to_dict()
        result["key"] = self.key
        result["encryptedKey"] = self.encryptedKey
        return result


@dataclass
class ACMEProvisioner(Provisioner):
    """Provisioner that uses the ACME protocol."""


@dataclass
class StepCAContext:
    """Configuration context for Step CLI interactions.

    Provides helper methods to load and remove provisioners using the
    Step CLI, with support for switching users, injecting environment
    variables, and toggling debug output.
    """

    ca_path: Optional[str] = None
    ca_root: Optional[str] = None
    ca_url: Optional[str] = None
    debug: bool = False
    fingerprint: Optional[str] = None
    run_as: Optional[str] = None

    def _build_env(self) -> Optional[Dict[str, str]]:
        """Construct environment variables for CLI execution.

        Returns:
            dict or None: Dictionary of environment variables.
        """
        return {"STEPPATH": self.ca_path} if self.ca_path else None

    def _extend_command(self, command: List[str]) -> List[str]:
        """Append CA-related CLI flags to the base command.

        Args:
            command (List[str]): Base command as a list of arguments.

        Returns:
            List[str]: Command list with extended options.
        """
        if self.ca_root:
            command.extend(["--ca-root", self.ca_root])
        if self.ca_url:
            command.extend(["--ca-url", self.ca_url])
        if self.fingerprint:
            command.extend(["--fingerprint", self.fingerprint])
        return command

    def load_provisioners(self) -> List[Provisioner]:
        """Load the current list of provisioners via the Step CLI.

        Returns:
            List[Provisioner]: A list of provisioner objects.

        Raises:
            RuntimeError: If the command or JSON parsing fails.
        """
        command = self._extend_command(
            ["step", "ca", "provisioner", "list"]
        )
        try:
            result = run_command_as_user(
                command,
                username=self.run_as,
                env_vars=self._build_env(),
                debug=self.debug,
            )
            raw_data = json.loads(result.stdout)
        except subprocess.CalledProcessError as err:
            raise RuntimeError(
                "'step ca provisioner list' failed: "
                f"{err.stderr.strip()}"
            ) from err
        except json.JSONDecodeError as err:
            raise RuntimeError(
                "Failed to parse JSON from step output."
            ) from err

        provisioners: List[Provisioner] = []
        for item in raw_data:
            ptype = item.get("type")
            cls = _PROVISIONER_CLASSES.get(ptype, Provisioner)
            init_args = {
                "name": item.get("name"),
                "type": ptype,
                "claims": item.get("claims", {}),
                "options": item.get("options", {}),
            }
            if cls is JWKProvisioner:
                init_args["key"] = item.get("key", {})
                init_args["encryptedKey"] = item.get("encryptedKey", "")
            provisioners.append(cls(**init_args))  # type: ignore[arg-type]
        return provisioners

    def remove_provisioner(self, name: str) -> None:
        """Remove a specific provisioner via the Step CLI.

        Args:
            name (str): The name of the provisioner to remove.

        Raises:
            RuntimeError: If the CLI command fails.
        """
        command = self._extend_command(
            ["step", "ca", "provisioner", "remove", name]
        )
        try:
            run_command_as_user(
                command,
                username=self.run_as,
                env_vars=self._build_env(),
                debug=self.debug,
            )
        except subprocess.CalledProcessError as err:
            raise RuntimeError(
                f"Failed to remove provisioner '{name}': "
                f"{err.stderr.strip()}"
            ) from err


_PROVISIONER_CLASSES: Dict[str, Type[Provisioner]] = {
    "JWK": JWKProvisioner,
    "ACME": ACMEProvisioner,
}
