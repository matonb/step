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
import os
import pwd
import stat
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type

from .process import run_command
from .utils import generate_secure_password


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
            result = run_command(
                command,
                username=self.run_as,
                env_vars=self._build_env(),
                debug=self.debug,
            )
            raw_data = json.loads(result.stdout)
        except json.JSONDecodeError as err:
            raise RuntimeError("Failed to parse JSON from step output.") from err

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
            name (str): The name for the new provisioner.
            provisioner_type (str): The type of provisioner to create.
            x509_min (Optional[str]): Minimum certificate duration for X509 certificates.
            x509_max (Optional[str]): Maximum certificate duration for X509 certificates.
            x509_default (Optional[str]): Default certificate duration for X509 certificates.
            password (Optional[str]): Password for the provisioner. If not provided,
                                    a secure password will be generated.
                                    Not used for ACME provisioners.

        Returns:
            Optional[str]: The password used for the provisioner (generated or provided),
                        or None if the provisioner type doesn't require a password (e.g., ACME).

        Raises:
            RuntimeError: If the CLI command fails.
        """

        command = self._extend_command(
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

        # ACME provisioners don't need passwords
        actual_password = None
        password_file = None

        try:
            if provisioner_type != "ACME":
                # Generate a secure password if none is provided
                actual_password = (
                    password if password is not None else generate_secure_password()
                )

                # Create a temporary file to store the password
                fd, password_file = tempfile.mkstemp(text=True)
                os.close(fd)

                # Write the password to the file
                with open(password_file, "w") as f:
                    f.write(actual_password)

                # Set file permissions to 0600 (readable/writable only by owner)
                os.chmod(password_file, stat.S_IRUSR | stat.S_IWUSR)

                # If run_as is specified, change ownership of the file to that user
                if self.run_as:
                    try:
                        # Get user information to obtain UID/GID
                        user_info = pwd.getpwnam(self.run_as)
                        # Change ownership of the password file
                        os.chown(password_file, user_info.pw_uid, user_info.pw_gid)
                    except (KeyError, OSError) as e:
                        # In case of failure, set world-readable as fallback, but log a warning
                        os.chmod(
                            password_file,
                            stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH,
                        )
                        import sys

                        print(
                            f"Warning: Could not change ownership of password file to {self.run_as}: {e}. "
                            f"Using less secure permissions as fallback.",
                            file=sys.stderr,
                        )

                # Use --password-file option with the temporary file
                command.extend(["--password-file", password_file])

            # Add specific X509 duration parameters if provided
            # These parameters override any set in the StepCAContext
            if x509_min:
                command.extend(["--x509-min-dur", x509_min])
            if x509_max:
                command.extend(["--x509-max-dur", x509_max])
            if x509_default:
                command.extend(["--x509-default-dur", x509_default])

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
                    # Log the error but don't raise an exception
                    import sys

                    print(
                        f"Warning: Failed to remove temporary password file: {password_file}",
                        file=sys.stderr,
                    )


_PROVISIONER_CLASSES: Dict[str, Type[Provisioner]] = {
    "JWK": JWKProvisioner,
    "ACME": ACMEProvisioner,
}
