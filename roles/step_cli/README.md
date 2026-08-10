# matonb.smallstep.step_cli

Installs the [step CLI](https://smallstep.com/docs/step-cli/), and owns the
smallstep package repository both roles in this collection install from.

Use it directly on hosts that talk to a CA rather than run one.
`matonb.smallstep.ca_server` pulls it in for you, so a CA host does not need to
name it.

## Requirements

- ansible-core 2.14 or later.
- Debian bookworm, Ubuntu jammy or noble, or EL 9.

## Role variables

| Variable                        | Default                | Description                                                          |
| ------------------------------- | ---------------------- | -------------------------------------------------------------------- |
| `step_cli_version`              | `""` (unpinned)        | Version, as the package manager spells it                            |
| `step_cli_packages`             | built from the version | Package names. Replace outright for your own repository              |
| `step_cli_manage_repository`    | `true`                 | Add smallstep's repository. False if you mirror it or define it yourself |
| `step_cli_repository_gpg_check` | `true`                 | Verify repository metadata signatures. RedHat only — see below       |
| `step_cli_package_gpg_check`    | `true`                 | Verify package signatures. RedHat only — see below                   |

## Packages

Packages come from [smallstep's own repositories](https://packages.smallstep.com),
which carry both `step-ca` and `step-cli` up to the current upstream release
and cover every architecture upstream builds for. Installing by name rather
than by release-asset URL is what lets apt and dnf resolve the architecture,
the dependencies and the upgrade path themselves.

Leave the version empty for whatever the repository currently holds, or pin it
as the package manager spells it: Debian needs the upstream version and the
Debian revision together (`0.30.6-1`), RedHat takes the version on its own
(`0.30.6`) and accepts version-release too.

Empty is not "track the latest". The install is `state: present`, so an
unpinned version is whatever the repository held when the package first
arrived. Lowering a version is also not a downgrade — apt refuses one unless
asked, and dnf treats an older package as already satisfied. Set
`step_cli_packages` outright to pin backwards.

## Signature checking

Two things are signed, by two different keys, and both are checked by default.

`step_cli_repository_gpg_check` covers the repository **metadata** — apt's
`Release`, dnf's `repomd.xml` — which is signed by the key smallstep hosts its
packages behind.

`step_cli_package_gpg_check` covers the **packages**, which are signed by
Smallstep Ops, `889B19391F774443`. The key ID in an RPM header is that key's
signing subkey, ending `1E43859CB855223C`, so the two look unrelated until you
import the primary key.

**Both switches are RedHat-only**, and setting either to `false` on a Debian
host fails the play rather than being quietly ignored — unless
`step_cli_manage_repository` is already `false`, in which case the role
configures no repository at all and neither switch is consulted.

There is no per-package check on Debian to turn off: apt verifies the signed
`Release` file against the `signed-by` keyring and trusts the checksums it
carries, which covers the packages transitively. Repository verification cannot
be disabled either — `trusted=yes` leaves apt warning `NO_PUBKEY`, and the apt
module's cache update treats that as a fetch failure where `apt-get` merely
warns.

Accepting a request for less verification and silently giving more would be the
wrong way round, so the Debian path asserts and points at
`step_cli_manage_repository: false`, which leaves repository configuration to
you entirely.

## Dependencies

None.

## Example playbook

```yaml
- name: Install the step CLI on hosts that talk to the CA
  hosts: clients
  roles:
    - matonb.smallstep.step_cli
```

Pinning a version, and installing from a mirror you manage yourself:

```yaml
- name: Install a pinned step CLI from our own repository
  hosts: clients
  roles:
    - role: matonb.smallstep.step_cli
      vars:
        step_cli_manage_repository: false
        step_cli_version: "0.30.6-1"
```

## More

Full documentation, including the collection's modules, is in the
[collection README](https://github.com/matonb/smallstep/blob/main/README.md).

## License

GPL-3.0-or-later

## Author

Brett Maton
