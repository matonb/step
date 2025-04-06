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
import logging
import os
import pwd
import stat
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Type

from .process import run_command
from .utils import generate_secure_password

logging.basicConfig(level=logging.DEBUG)


@dataclass
class Provisioner(ABC):
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

    @abstractmethod
    def prepare_add_command(
        self, base_command: List[str], context: "StepCAContext", **kwargs
    ) -> Tuple[List[str], Optional[str], Optional[str]]:
        """Prepare command for adding this type of provisioner.

        Args:
            base_command: Base command list to extend
            context: The StepCA context
            **kwargs: Additional provisioner-specific parameters

        Returns:
            Tuple containing:
            - The final command list
            - Generated/provided password (if applicable)
            - Path to temporary password file (if created)
        """


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

    def prepare_add_command(
        self, base_command: List[str], context: "StepCAContext", **kwargs
    ) -> Tuple[List[str], Optional[str], Optional[str]]:
        """Prepare command for adding a JWK provisioner.

        Args:
            base_command: Base command list to extend
            context: The StepCA context
            **kwargs: Additional parameters including optional password

        Returns:
            Tuple containing:
            - The final command list
            - Generated/provided password
            - Path to temporary password file
        """
        password = kwargs.get("password")
        actual_password = (
            password if password is not None else generate_secure_password()
        )

        # Create temporary password file
        fd, password_file = tempfile.mkstemp(text=True)
        os.close(fd)

        # Write password and set permissions
        with open(password_file, "w", encoding="utf-8") as f:
            f.write(actual_password)

        os.chmod(password_file, stat.S_IRUSR | stat.S_IWUSR)

        # Handle user ownership if needed
        if context.run_as:
            try:
                user_info = pwd.getpwnam(context.run_as)
                os.chown(password_file, user_info.pw_uid, user_info.pw_gid)
            except (KeyError, OSError) as e:
                os.chmod(
                    password_file,
                    stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH,
                )
                logging.warning(
                    "Could not change ownership of password file to %s: %s. "
                    "Using less secure permissions as fallback.",
                    context.run_as,
                    e,
                )
        # Add password file option
        command = base_command.copy()
        command.extend(["--password-file", password_file])

        return command, actual_password, password_file


@dataclass
class ACMEProvisioner(Provisioner):
    """Provisioner that uses the ACME protocol."""

    def prepare_add_command(
        self, base_command: List[str], context: "StepCAContext", **kwargs
    ) -> Tuple[List[str], Optional[str], Optional[str]]:
        """Prepare command for adding an ACME provisioner.

        Args:
            base_command: Base command list to extend
            context: The StepCA context
            **kwargs: Additional parameters (not used for ACME)

        Returns:
            Tuple containing:
            - The final command list
            - None for password (not needed)
            - None for password file (not needed)
        """
        # ACME doesn't need any special handling
        return base_command.copy(), None, None


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
    x509_min: Optional[str] = None
    x509_max: Optional[str] = None
    x509_default: Optional[str] = None

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

        # Add X509 duration parameters if provided
        if self.x509_min:
            command.extend(["--x509-min-dur", self.x509_min])
        if self.x509_max:
            command.extend(["--x509-max-dur", self.x509_max])
        if self.x509_default:
            command.extend(["--x509-default-dur", self.x509_default])

        return command

    def load_provisioners(self) -> List[Provisioner]:
        """Load the current list of provisioners via the Step CLI.

        Returns:
            List[Provisioner]: A list of provisioner objects.

        Raises:
            RuntimeError: If the command or JSON parsing fails.

        """
        command = self._extend_command(["step", "ca", "provisioner", "list"])
        try:
            logging.debug("Executing command: %s", command)
            result = run_command(
                command,
                username=self.run_as,
                env_vars=self._build_env(),
                debug=self.debug,
            )
            logging.debug(
                "Command stdout: %s",
                (
                    result.stdout[:100] + "..."
                    if len(result.stdout) > 100
                    else result.stdout
                ),
            )
            raw_data = json.loads(result.stdout)
            logging.debug("Parsed %d provisioners from output", len(raw_data))
        except json.JSONDecodeError as err:
            raise RuntimeError("Failed to parse JSON from step output.") from err

        provisioners: List[Provisioner] = []
        for i, item in enumerate(raw_data):
            ptype = item.get("type")
            logging.debug("Processing provisioner %d of type: %s", i, ptype)
            logging.debug("Raw provisioner data: %s", json.dumps(item, indent=2)[:200])
            logging.debug(
                "Available provisioner types: %s", list(_PROVISIONER_CLASSES.keys())
            )

            cls = _PROVISIONER_CLASSES.get(ptype)
            if cls is None:
                logging.warning("Unknown provisioner type: %s, skipping", ptype)
                continue

            init_args = {
                "name": item.get("name"),
                "type": ptype,
                "claims": item.get("claims", {}),
                "options": item.get("options", {}),
            }
            if cls is JWKProvisioner:
                init_args["key"] = item.get("key", {})
                init_args["encryptedKey"] = item.get("encryptedKey", "")

            logging.debug(
                "Creating provisioner with args: %s",
                {k: "..." if k == "key" else v for k, v in init_args.items()},
            )
            try:
                provisioner = cls(**init_args)
                provisioners.append(provisioner)
                logging.debug("Successfully added provisioner of type %s", ptype)
            except Exception as e:
                logging.error(
                    "Failed to create provisioner of type %s: %s", ptype, str(e)
                )
                raise

        return provisioners

    def remove_provisioner(self, name: str) -> None:
        """Remove a specific provisioner via the Step CLI.

        Args:
            name (str): The name of the provisioner to remove.

        Raises:
            RuntimeError: If the CLI command fails.
        """
        command = self._extend_command(["step", "ca", "provisioner", "remove", name])
        run_command(
            command,
            username=self.run_as,
            env_vars=self._build_env(),
            debug=self.debug,
        )

    def add_provisioner(
        self,
        name: str,
        provisioner_type: str,
        x509_min: Optional[str] = None,
        x509_max: Optional[str] = None,
        x509_default: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Optional[str]:
        """Add a new provisioner via the Step CLI.

        Args:
            name: The name for the new provisioner.
            provisioner_type: The type of provisioner to create.
            x509_min: Minimum certificate duration for X509 certificates.
            x509_max: Maximum certificate duration for X509 certificates.
            x509_default: Default certificate duration for X509 certificates.
            password: Password for the provisioner. If not provided,
                    a secure password will be generated.
                    Not used for ACME provisioners.

        Returns:
            Optional[str]: The password used for the provisioner (generated or provided),
                        or None if the provisioner type doesn't require a password.

        Raises:
            RuntimeError: If the CLI command fails.
            ValueError: If the provisioner type is not supported.
        """

        logging.debug("Adding provisioner of type: %s", provisioner_type)
        logging.debug(
            "Available provisioner types: %s", list(_PROVISIONER_CLASSES.keys())
        )

        provisioner_class = _PROVISIONER_CLASSES.get(provisioner_type)
        if provisioner_class is None:
            logging.error(
                "Unsupported provisioner type: %s. Available types: %s",
                provisioner_type,
                list(_PROVISIONER_CLASSES.keys()),
            )
            raise ValueError(f"Unsupported provisioner type: {provisioner_type}")

        logging.debug(
            "Using class %s for provisioner type %s",
            provisioner_class.__name__,
            provisioner_type,
        )
        # Create base command
        base_command = self._extend_command(
            [
                "step",
                "ca",
                "provisioner",
                "add",
                name,
                "--type",
                provisioner_type,
                "--create",
            ]
        )

        # Add duration parameters if provided
        if x509_min:
            base_command.extend(["--x509-min-dur", x509_min])
        if x509_max:
            base_command.extend(["--x509-max-dur", x509_max])
        if x509_default:
            base_command.extend(["--x509-default-dur", x509_default])

        # Create the provisioner instance
        try:
            provisioner = provisioner_class(name=name, type=provisioner_type)
            logging.debug(
                "Successfully created provisioner instance of class %s",
                provisioner_class.__name__,
            )
        except Exception as e:
            logging.error("Failed to create provisioner instance: %s", str(e))
            raise

        password_file = None
        try:
            # Let the provisioner prepare its specific command
            command, actual_password, password_file = provisioner.prepare_add_command(
                base_command, self, password=password
            )

            # Execute the command
            run_command(
                command,
                username=self.run_as,
                env_vars=self._build_env(),
                debug=self.debug,
            )

            return actual_password
        finally:
            # Clean up the temporary file if it was created
            if password_file and os.path.exists(password_file):
                try:
                    os.remove(password_file)
                except OSError:
                    logging.warning(
                        "Failed to remove temporary password file: %s", password_file
                    )


# Fixed the protected class access warning by elevating the classes to the module level
_PROVISIONER_CLASSES: Dict[str, Type[Provisioner]] = {
    "JWK": JWKProvisioner,
    "ACME": ACMEProvisioner,
}
