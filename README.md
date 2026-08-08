# Step CA Ansible Collection

Ansible collection for installing and managing a [Step CA](https://smallstep.com/docs/step-ca) certificate authority.

## Description

Four modules and two roles. The roles install step-ca and the step CLI and run
the CA under systemd; the modules initialize it, edit its configuration, and
create, update and remove provisioners — in both of step-ca's management modes,
including against a CA that is not running.

| Content | What it is for |
| ------------------------------ | ---------------------------------------------------------------------- |
| role `ca_server`               | Install step-ca and run the CA under systemd; pulls in `step_cli`      |
| role `step_cli`                | Install the step CLI, and own the smallstep package repository        |
| module `initialize`            | Create the CA, idempotently                                            |
| module `configure`             | Edit `ca.json` — paths, database, certificate duration claims          |
| module `provisioner`           | Create, update and remove provisioners                                 |
| module `bootstrap`             | Read a step-ca JSON configuration file, such as `defaults.json`        |

## Requirements

- ansible-core 2.14 or higher — the roles use `ansible.builtin.systemd_service`,
  which does not exist before it
- `community.general`, for the `capabilities` module the `ca_server` role uses
- A Debian- or RedHat-family target, for the roles. The modules work anywhere
  step-ca does
- Appropriate permissions to manage Step CA

---

## matonb.step.configure

Modify Step CA configuration JSON file (ca.json). Supports top-level parameters and certificate duration claims.

**Note**: Step CA must be restarted after configuration changes.

The file is only rewritten when a requested setting differs from what it already
holds, so `changed` is accurate and a `notify` handler fires only on a real
change. Durations are compared as durations rather than as text — step
renormalizes `8760h` to `8760h0m0s` when it rewrites `ca.json`, and that is not
treated as a change. Settings this module does not manage are left untouched.

The file is replaced atomically — written alongside, flushed, and moved into
place in one step — so a failed or interrupted write leaves the original intact
rather than truncated. An existing file keeps its mode and ownership; a file
created by `create: true` takes the running user's umask, since this module sets
neither. A symlinked `json_path` is followed rather than replaced. Set
`backup: true` to keep a timestamped copy of what was there before.

### Parameters

| Parameter                   | Type    | Required | Default | Description                                         |
| --------------------------- | ------- | -------- | ------- | --------------------------------------------------- |
| `backup`                    | boolean | no       | `false` | Copy the file before overwriting; see `backup_file` |
| `ca_config`                 | path    | no       |         | Path to CA config file                              |
| `ca_path`                   | path    | no       |         | Path to CA directory                                |
| `create`                    | boolean | no       | `false` | Write a new file when `json_path` does not exist    |
| `crt`                       | path    | no       |         | Path to certificate file                            |
| `db_datasource`             | string  | no       |         | Database datasource string                          |
| `default_tls_cert_duration` | string  | no       |         | Default TLS cert duration (e.g., "720h")            |
| `json_path`                 | path    | yes      |         | Path to the ca.json configuration file              |
| `key`                       | path    | no       |         | Path to key file                                    |
| `max_tls_cert_duration`     | string  | no       |         | Maximum TLS cert duration (e.g., "8760h")           |
| `min_tls_cert_duration`     | string  | no       |         | Minimum TLS cert duration (e.g., "5m")              |
| `root`                      | path    | no       |         | Path to root certificate                            |

`json_path` must already exist unless `create: true`. A path that is not there
is far more often a typo than a request to build a CA configuration from
nothing, and the old behavior — writing a new, nearly empty file and reporting
success — left the real CA untouched with the play still green.

### Examples

The `ca_server` role ships the `Reload step-ca` handler these tasks notify, so a
play that includes the role needs no handler of its own; a play using the
modules alone still does, as the [examples](examples/) show. It sends SIGHUP via
the unit's `ExecReload`, which is what a `ca.json` change needs. When the service
is not running it starts it instead — though systemd will skip that start until
both `config/ca.json` and the password file exist, which the unit requires.

```yaml
# Set certificate duration limits
- name: Configure certificate durations
  matonb.step.configure:
    default_tls_cert_duration: "720h" # 30 days
    json_path: /etc/step-ca/config/ca.json
    max_tls_cert_duration: "8760h" # 1 year
  notify: Reload step-ca

# Update database path
- name: Configure database
  matonb.step.configure:
    db_datasource: /var/lib/step-ca/db
    json_path: /etc/step-ca/config/ca.json

# Configure multiple settings
- name: Configure paths and durations
  matonb.step.configure:
    crt: /etc/step-ca/certs/intermediate_ca.crt
    json_path: /etc/step-ca/config/ca.json
    key: /etc/step-ca/secrets/intermediate_ca_key
    max_tls_cert_duration: "17520h" # 2 years
    root: /etc/step-ca/certs/root_ca.crt
```

---

## matonb.step.provisioner

Creates, updates and removes provisioners. Works against both management modes —
see [Management modes](#management-modes) below.

> **Admin mode needs a running CA; config mode does not.** In admin mode every
> operation goes through the CA, so it must be reachable. In config mode the
> module reads and writes `ca.json` directly, so provisioners can be configured
> before step-ca is ever started — but `ca_path` or `ca_config` must be set so
> the file can be found.

### Parameters

| Parameter             | Type    | Required | Default   | Description                                                                                             |
| --------------------- | ------- | -------- | --------- | ------------------------------------------------------------------------------------------------------- |
| `admin_cert`          | path    | no       |           | Admin certificate (chain) in PEM format. Requires `admin_key`. Admin mode only                          |
| `admin_key`           | path    | no       |           | Private key matching `admin_cert`. Requires `admin_cert`. Admin mode only                               |
| `admin_password_file` | path    | no       |           | File holding the password that decrypts `admin_provisioner`'s key. Required in admin mode               |
| `admin_provisioner`   | string  | no       |           | Provisioner used to mint admin credentials. Required in admin mode                                      |
| `admin_subject`       | string  | no       |           | Subject of the CA administrator (`step` by default). Required in admin mode                             |
| `ca_config`           | path    | no\*     |           | Path to `ca.json`. Defaults to `config/ca.json` under `ca_path`                                         |
| `ca_path`             | path    | no\*     |           | Path to the step CA configuration directory (sets STEPPATH)                                             |
| `ca_url`              | string  | no       |           | Optional URL of the step CA. Falls back to the CA's `defaults.json`                                     |
| `context`             | string  | no       |           | Optional step context name to operate in                                                                |
| `debug`               | boolean | no       | `false`   | If true, prints CLI commands to stderr before execution                                                 |
| `fingerprint`         | string  | no       |           | **Deprecated, unused.** Removed in 2.0.0 — see [Deprecations](#deprecations)                             |
| `management_mode`     | string  | no       | `auto`    | `auto`, `admin` or `config` — see [Management modes](#management-modes)                                  |
| `name`                | string  | yes      |           | Name of the provisioner to manage                                                                       |
| `password`            | string  | no       |           | Password for the provisioner key. Generated when omitted. Not used for ACME                             |
| `root`                | path    | no       |           | Path to the CA root certificate, used to verify `ca_url`. Alias: `ca_root` (deprecated)                  |
| `run_as`              | string  | no       |           | System user to run Step CLI commands as (typically should be set to `step` for proper access to the CA) |
| `state`               | string  | no       | `present` | Desired state: `present` or `absent`                                                                    |
| `type`                | string  | no       |           | Type of provisioner (required when creating a new provisioner)                                          |
| `x509_default`        | string  | no       |           | Default certificate duration for X509 certificates                                                      |
| `x509_max`            | string  | no       |           | Maximum certificate duration for X509 certificates                                                      |
| `x509_min`            | string  | no       |           | Minimum certificate duration for X509 certificates                                                      |

\* One of `ca_path` or `ca_config` is required, unless `management_mode` is set
to `admin`. They locate `ca.json`, which is both how the management mode is
detected and, in config mode, where the existing provisioners are read from.

The `x509_*` options have no default. A claim that is left unset is inherited
from the CA's own defaults and is not reconciled; a claim that is set is kept at
that value on every run.

### Management modes

step-ca stores provisioners in one of two places, and the step CLI decides which
by probing the CA rather than by taking a flag.

| Mode     | Provisioners live in | Changed via     | `restart_required` |
| -------- | -------------------- | --------------- | ------------------ |
| `config` | `ca.json`            | editing the file | `true`             |
| `admin`  | the CA database      | the Admin API    | `false`            |

A CA is in admin mode when it was initialized with `remote_management: true`,
which sets `authority.enableAdmin` in `ca.json`. With `management_mode: auto`
(the default) the module reads that setting and follows it — the same field
step-ca itself reads, so this detects the mode rather than inferring it. If
`ca.json` cannot be found or read, the mode is genuinely unknown and the task
fails rather than picking one; set `management_mode` explicitly in that case.

Admin API changes take effect immediately, so `restart_required` is `false` in
admin mode. In config mode the file is edited in place and step-ca must be
restarted or sent SIGHUP, so it is `true`.

`management_mode: admin` and `management_mode: config` **assert** a mode rather
than force one — the step CLI always picks the path itself from what the CA
reports. The setting controls whether the module accepts the outcome: if step
takes the other path the task fails rather than reporting a change that did not
land where you expected.

### Admin mode authentication

Admin mode needs credentials. There are two ways to supply them, and **every
value the step CLI is not given it prompts for, which hangs the task** — so the
module validates the combination up front and fails immediately instead.

**Just-in-time credentials** — what `step ca init --remote-management` sets up.
The CLI signs a short-lived admin certificate on demand. All three options are
required:

```yaml
- name: Manage a provisioner on an admin-mode CA
  matonb.step.provisioner:
    admin_password_file: /etc/step-ca/secrets/provisioner_password
    admin_provisioner: admin        # a JWK provisioner the admin is bound to
    admin_subject: step             # the super admin created at init time
    ca_path: /etc/step-ca
    ca_url: https://ca.example.com
    name: acme
    run_as: step
    type: ACME
```

**An existing admin certificate** — supply both halves:

```yaml
- name: Manage a provisioner with an admin certificate
  matonb.step.provisioner:
    admin_cert: /etc/step-ca/admin.crt
    admin_key: /etc/step-ca/admin.key
    ca_path: /etc/step-ca
    ca_url: https://ca.example.com
    name: acme
    run_as: step
    type: ACME
```

The admin key must be unencrypted. step loads it without a password option and
would prompt for one, so `admin_password_file` is rejected alongside
`admin_cert`.

### Upgrading from 1.0.x

Three behaviors changed for existing config-mode users:

- **Existing provisioners are now reconciled.** Previously `state: present` on a
  provisioner that already existed was a no-op. It now compares the `x509_*`
  claims you set and runs `step ca provisioner update` when they differ, so the
  first run after upgrading may report `changed` on provisioners you last
  touched by hand. Claims you do not set are still left alone.
- **`restart_required` is no longer always `true` on change.** It is `false` in
  admin mode, where the change is already live.
- **A JWK add now fails if the password file cannot be handed to `run_as`.**
  The old code fell back to making that file world-readable.

`generated_password` is returned in plaintext, so it lands in the play recap and
callback logs. Set `no_log: true` on the task, or supply `password` yourself, if
that matters to you.

### Upgrading from 1.1.x

Two changes to `matonb.step.configure`, both closing
[#37](https://github.com/matonb/step/issues/37):

- **A missing `json_path` now fails** rather than creating a new file. Set
  `create: true` if a task genuinely builds a configuration from nothing.
- **`json_path` expands `~`**, having previously been typed `str` while
  `ca_path` and `ca_config` beside it were `path`. The two combined badly: a
  `~/step-ca/config/ca.json` produced a literal `~` directory.

Then, for `matonb.step.provisioner`:

**`ca_path` or `ca_config` is now required, unless you set
`management_mode: admin`.** Two things that used to work by reaching the CA over
HTTP now need `ca.json`: detecting the management mode, and reading the existing
provisioners in config mode. A task that set neither previously carried on with
a warning and an assumed mode; it now fails with a message naming both remedies.
So does a task whose `ca_path` does not actually contain `config/ca.json` — the
containerised case, where `defaults.json` points `ca-config` somewhere else — or
whose `ca.json` the module cannot read because it runs without `become`.

This closes a real bug ([#31](https://github.com/matonb/step/issues/31)): in
config mode the module read provisioners from the CA's *loaded* configuration
while writing them to `ca.json`, so re-running a play before step-ca had been
reloaded failed with `provisioner with name acme already exists`. Reading the
file it writes makes a single run converge — and means config-mode tasks no
longer need the CA to be running at all.

Add `ca_path: /etc/step-ca` to affected tasks, or `management_mode: admin` if
the CA is reached only by `ca_url`.

### Deprecations

| Option        | Status                                                                                             |
| ------------- | -------------------------------------------------------------------------------------------------- |
| `ca_root`     | Renamed to `root` to match the step CLI flag. Kept as an alias, removed in 2.0.0                   |
| `fingerprint` | Never had any effect. No `step ca provisioner` subcommand accepts a fingerprint. Removed in 2.0.0  |

`fingerprint` applies to `step ca bootstrap` and `step ca root`, which establish
trust in a CA; it has no meaning once you are managing provisioners.

### Provisioner Types

**Creating** a provisioner is supported for `ACME` and `JWK` only. Any other
type fails with a clear message rather than producing something half-configured,
because each type needs its own options (`--client-id`, `--x5c-roots`,
`--nebula-root` and so on) that this module does not yet expose.

**Listing, reconciling and removing** work for every type the CA reports, so
`state: absent` and the `x509_*` claims can be used against provisioners of any
type — including ones created by hand with the step CLI.

`type` accepts all of the following. When creating, it must be `ACME` or `JWK`;
otherwise it acts as a filter alongside `name`.

- `ACME`
- `AWS`
- `Azure`
- `GCP`
- `JWK`
- `K8SSA`
- `Nebula`
- `OIDC`
- `SCEP`
- `SSHPOP`
- `X5C`

### Duration Format

X509 duration parameters accept time units as follows:

- `s` - seconds
- `m` - minutes
- `h` - hours

## Return Values

| Key                  | Type    | Description                                                                                    |
| -------------------- | ------- | ---------------------------------------------------------------------------------------------- |
| `changed`            | boolean | Whether any changes were made                                                                  |
| `generated_password` | string  | Returned if the provisioner password was generated, not provided                               |
| `management_mode`    | string  | The mode used, `admin` or `config`                                                             |
| `name`               | string  | The name of the provisioner being managed                                                      |
| `provisioners`       | list    | List of provisioners that matched the specified name and (optional) type                       |
| `restart_required`   | boolean | Whether step-ca must be restarted for the change to take effect. Always `false` in admin mode  |
| `state`              | string  | The desired state as requested                                                                 |
| `type`               | string  | The type of the provisioner (if provided as a filter)                                          |
| `updated`            | list    | Claim parameters reconciled on an existing provisioner                                         |

## Examples

Complete, runnable playbooks live in [`examples/`](examples/).

### Create a new JWK provisioner

```yaml
- name: Create JWK provisioner
  matonb.step.provisioner:
    ca_path: /etc/step-ca
    name: my-jwk-provisioner
    run_as: step # Run as step user for proper CA access
    state: present
    type: JWK
    x509_default: 24h
    x509_max: 48h
    x509_min: 30m
  become: true # Required when using run_as
  register: provisioner_result

- name: Restart step-ca service if needed
  ansible.builtin.service:
    name: step-ca
    state: restarted
  become: true
  when: provisioner_result.restart_required | bool
```

Prefer `notify:` and a handler over a `when:` guard on every task — a play that
adds several provisioners then reloads once, at the end.

### Remove a provisioner

```yaml
- name: Remove provisioner
  matonb.step.provisioner:
    ca_path: /etc/step-ca
    name: old-provisioner
    run_as: step
    state: absent
  become: true # Required when using run_as
  register: provisioner_result

- name: Restart step-ca service if needed
  ansible.builtin.service:
    name: step-ca
    state: restarted
  become: true
  when: provisioner_result.restart_required | bool
```

`state: absent` works for provisioners of any type, including ones this module
cannot create.

### Check whether a provisioner exists

There is no read-only mode: `state: present` needs `type` so it knows what to
create if the provisioner is missing. Use check mode, which predicts the change
without making it — `changed` is `false` when the provisioner already matches.

```yaml
- name: Check whether the provisioner exists
  matonb.step.provisioner:
    ca_path: /etc/step-ca
    name: my-provisioner
    run_as: step
    type: JWK
  become: true # Required when using run_as
  check_mode: true
  register: provisioner_check

- name: Display result
  ansible.builtin.debug:
    msg: "Provisioner {{ 'is missing' if provisioner_check.changed else 'exists' }}"
```

`provisioner_check.provisioners` carries the matching provisioner's full
configuration when one was found.

`type` also narrows the match, so this asks whether a **JWK** named
`my-provisioner` exists. A provisioner of that name but another type reports as
missing — and a non-check run of the same task would then try to create it, which
step refuses.

---

## matonb.step.initialize

Running against a CA that is already there reports `ok` and changes nothing, so
a play containing the task can be re-run.

What counts as "already there" is decided by the CA, not by a list of filenames
in the module. `config/ca.json` has to parse, and every file it names — `root`,
`crt`, `key`, `federatedRoots`, the `ssh` host and user keys, and an RA's
`credentialsFile` — has to be present and non-empty. Relative entries are
resolved against `path`; entries carrying a URI scheme are not paths on this
host and are skipped, so a KMS-backed CA whose `key` is
`azurekms:name=…;vault=…` is judged on the files it does name.

That matters because there is no one file set. A registration authority proxies
signing upstream and owns no root key; a `linked` deployment keeps its keys with
Certificate Manager. Both are complete CAs with a fraction of a standalone CA's
files, and both are now recognized without the module having to know what they
write. It also means a CA whose **root key is kept offline** — best practice,
since step-ca signs with the intermediate — reports `ok` rather than looking
half-built.

`config/defaults.json` is deliberately not part of the test. step-ca itself is
started with `ca.json` and never reads it, so a CA without it is initialized and
working. It is not worthless though — it carries the `ca_url` and `root`
defaults the `step` CLI and `matonb.step.provisioner` fall back on — so a CA
reported `ok` without it can still fail a later task that relies on those.
Restore the file; do not reinitialize the CA for it.

The `templates` block written by `ssh: true` is also excluded. Those files are
real, but leaving them out errs towards calling a CA complete, and erring the
other way is what made this module unusable for RA and linked deployments.

The ways of being unfinished are reported differently:

| Situation | Behavior |
| --- | --- |
| `ca.json` will not parse, or a file it names cannot be read | Fails, and points at the file and at `become`/`run_as`. A reading problem is not a CA problem, so `force` is **not** suggested |
| Files the config names are missing or empty | Fails, naming them. Restore them, or `force` to start again |

That distinction matters in practice: running the task as the wrong user makes
key material unreadable, and answering that with `force` would delete a healthy
root key over a file mode.

`pki: true` is the exception. `step ca init --pki` writes no `ca.json` to
consult, so there the certificates and keys a PKI has are checked directly.

`force: true` deletes the files `step ca init` creates — which is not
necessarily every file a given deployment has. It is a way to start again, not a
way to clear up after an arbitrary configuration, and it destroys the root key
irrecoverably.

---

## Roles

### matonb.step.ca_server

Installs step-ca, creates the `step` user, grants the binary
`CAP_NET_BIND_SERVICE` so it can bind 443 without running as root, templates a
sandboxed systemd unit, and manages the service.

**It depends on `matonb.step.step_cli`**, which Ansible runs first. That role
owns the smallstep repository and the step CLI, so including `ca_server` alone
still gives you a host that can initialize and manage its own CA —
`matonb.step.initialize` shells out to `step ca init`. Configure the repository
through `step_cli`'s variables, below; there is deliberately only one set.

| Variable                    | Default                     | Description                                                                       |
| --------------------------- | --------------------------- | --------------------------------------------------------------------------------- |
| `ca_server_ca_version`      | `""` (unpinned)             | step-ca version, as the package manager spells it                                 |
| `ca_server_packages`        | built from the version      | Package names. Replace outright to install from your own repository               |
| `ca_server_password_file`   | `/etc/step-ca/password.txt` | File holding the password that decrypts the CA's keys                             |
| `ca_server_service_enabled` | `true`                      | Whether step-ca comes back after a reboot                                         |
| `ca_server_service_state`   | `started`                   | `started`, `stopped`, `restarted`, `reloaded`, or null to leave the service alone |

**The role does not create the password file.** That is yours to place — it is
the key to the CA. Until it exists and is non-empty, the service will not start,
and it must be readable by the `step` user, since that is who step-ca runs as.

### matonb.step.step_cli

Installs the step CLI, and owns the smallstep repository both roles install
from. Use it directly on hosts that talk to a CA rather than run one;
`ca_server` pulls it in for you.

| Variable                        | Default                | Description                                                          |
| ------------------------------- | ---------------------- | -------------------------------------------------------------------- |
| `step_cli_version`              | `""` (unpinned)        | Version, as the package manager spells it                            |
| `step_cli_packages`             | built from the version | Package names. Replace outright for your own repository              |
| `step_cli_manage_repository`    | `true`                 | Add smallstep's repository. False if you mirror it or define it yourself |
| `step_cli_repository_gpg_check` | `true`                 | Verify repository metadata signatures. RedHat only — see below       |
| `step_cli_package_gpg_check`    | `true`                 | Verify package signatures. RedHat only — see below                   |

Packages come from [smallstep's own repositories](https://packages.smallstep.com),
which carry both `step-ca` and `step-cli` up to the current upstream release and
cover every architecture upstream builds for. Installing by name rather than by
release-asset URL is what lets apt and dnf resolve the architecture, the
dependencies and the upgrade path themselves.

Leave a version empty for whatever the repository currently holds, or pin it as
the package manager spells it. Debian needs the upstream version and the Debian
revision together (`0.30.2-1`); RedHat takes the version on its own (`0.30.2`)
and will accept version-release (`0.30.2-1`) too. Note that lowering a version is not a
downgrade: apt refuses one unless explicitly asked, and dnf treats an older
package as already satisfied. Set the `*_packages` list outright to pin
backwards.

Left empty, each role installs whatever the repository holds at the time and
then leaves it alone: the install is `state: present`, not `latest`, so an
unpinned version is "newest at first install" rather than a version that
tracks upstream. Upgrading is a matter of raising the pin, or removing it and
upgrading the package by other means.

### Signature checking

Two things are signed, by two different keys, and both are checked by default.

`step_cli_repository_gpg_check` covers the repository **metadata** — apt's
`Release`, dnf's `repomd.xml` — which is signed by the key smallstep hosts its
packages behind.

`step_cli_package_gpg_check` covers the **packages**, which are signed by
Smallstep Ops, `889B19391F774443`, published at
`https://packages.smallstep.com/keys/smallstep-0x889B19391F774443.gpg`. The key
ID in an RPM header is that key's signing subkey, ending `1E43859CB855223C`, so
the two look unrelated until you import the primary key.

**Both switches are RedHat-only**, and setting either to `false` on a Debian
host fails the play rather than being quietly ignored.

There is no per-package check on Debian to turn off: apt verifies the signed
`Release` file against the `signed-by` keyring and trusts the checksums it
carries, which covers the packages transitively. And repository verification
cannot be disabled either — `trusted=yes` leaves apt warning `NO_PUBKEY`, and
the apt module's cache update treats that as a fetch failure where `apt-get`
merely warns.

Accepting a request for less verification and silently giving more would be the
wrong way round, so the Debian path asserts and points at
`step_cli_manage_repository: false`, which leaves repository configuration to
you entirely.

### Service state

`started` is the idempotent choice. `restarted` and `reloaded` act on every run
by design, so they also report `changed` on every run — that is the option
working, not a bug.

`ca_server_service_state` is applied only once both files the unit's
`ConditionFileNotEmpty` directives name are present and non-empty:
`config/ca.json` and `ca_server_password_file`. Before that there is nothing to
run, and systemd would skip the start with a zero exit while Ansible reported a
change on every run — success on a service that never came up.

Both are checked while the role runs, so a CA initialized later in the same play
is not seen until the next one. On a first run that does not matter: the unit
file is new, so `Restart step-ca` fires at the end of the play and starts the CA.
It only shows up when the unit is unchanged *and* the CA is initialized in the
same play — a retry after a failed `initialize`, for instance — where the service
comes up one run late.

### Handlers

`Restart step-ca` is notified by the unit file itself, because a changed unit
needs the process re-executed — a reload would leave the running CA on the old
`ExecStart`. `Reload step-ca` sends SIGHUP via the unit's `ExecReload` and is
what the `configure` and `provisioner` tasks should notify.

Both handlers, and the two systemd tasks, are skipped under `--check` on a host
with no unit file yet. `systemd_service` refuses a unit it cannot find before it
honours check mode, so the play would otherwise abort rather than report what it
would do. On a host that has already run the role, `--check` reports drift
normally.

A first `--check` against a host that has never run these roles is worth
reading with that in mind. Neither family can report on `step-ca` or `step-cli`,
because the repository they come from does not exist yet and the package manager
has nothing to answer with — the alternative is failing outright, which says
less. The two differ in one detail: RedHat reports that it would write the
repository file, Debian does not, because installing the signing key means a
network fetch that check mode cannot honestly simulate against a trust store the
same run has only pretended to install. Run once for real, and `--check`
reports drift on everything thereafter.

### Example

```yaml
- name: Build a CA
  hosts: ca
  roles:
    - matonb.step.ca_server

  tasks:
    - name: Install the CA password
      become: true
      ansible.builtin.copy:
        content: "{{ vaulted_ca_password }}\n"
        dest: "{{ ca_server_password_file }}"
        owner: step
        group: step
        mode: '0600'

    - name: Initialize the CA
      become: true
      become_user: step
      matonb.step.initialize:
        name: Example CA
        path: /etc/step-ca
        dns: [ca.example.com]
        address: ":443"
        password_file: "{{ ca_server_password_file }}"
        provisioner_password_file: "{{ ca_server_password_file }}"

    # The role's service task ran before the CA existed, so it skipped. Without
    # this the CA is only started by the next run of the play.
    - name: Start the CA now that it has a configuration
      become: true
      ansible.builtin.systemd_service:
        name: step-ca
        state: started
```

The two `password_file` values reference the role's own variable rather than
repeating the path, so changing `ca_server_password_file` moves both the unit's
`ConditionFileNotEmpty` and the file the module reads together.

Both roles are covered by `tests/integration/role.sh`, which drives them against
containers running a real systemd — once on Debian and once on Rocky 9. Like the
module suite it needs docker, so it does not run on every pull request: add the
`integration` label to a PR to run both suites against it, or start them from
the Actions tab. Neither gates a merge.

## Special Notes

- **Important**: The module should typically be run as the `step` user (using `run_as: step`) to ensure proper access to the CA configuration and keys. When using `run_as`, you must also set `become: true` on the task.
- When a provisioner is added or removed, changes are not visible in the Step CA environment until the service is restarted. The module provides a `restart_required` return value to indicate when this is necessary.
- The `type` parameter is required when creating a new provisioner (`state=present`) but is optional when checking for existence or removing a provisioner.
- X509 duration parameters allow you to control the validity periods of certificates issued by the provisioner.

## License

MIT

## Author Information

Brett Maton (@matonb)
