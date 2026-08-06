# Step CA Ansible Collection

Ansible module for managing [Step CA](https://smallstep.com/docs/step-ca) server configuration and provisioners.

## Description

This module allows you to create, remove, and filter provisioners within a Step CA environment. It provides support for configuring X509 certificate duration parameters and handles service restart requirements when changes are made.

## Requirements

- Ansible 2.9 or higher
- Step CA installed on the target host
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

## Roles

Full role documentation is still outstanding
([#39](https://github.com/matonb/step/issues/39)). The service options
`ca_server` accepts are:

| Variable                     | Default   | Description                                                                       |
| ---------------------------- | --------- | --------------------------------------------------------------------------------- |
| `ca_server_service_enabled`  | `true`    | Whether step-ca comes back after a reboot                                         |
| `ca_server_service_state`    | `started` | `started`, `stopped`, `restarted`, `reloaded`, or null to leave the service alone |

`started` is the idempotent choice. `restarted` and `reloaded` act on every run
by design, so they also report `changed` on every run — that is the option
working, not a bug.

`ca_server_service_state` is applied only once both files the unit's
`ConditionFileNotEmpty` directives name are present and non-empty:
`config/ca.json` and `step_ca_password_file`. Before that there is nothing to
run, and systemd would skip the start with a zero exit while Ansible reported a
change on every run — success on a service that never came up.

Both are checked while the role runs, so a CA initialized later in the same play
is not seen until the next one. On a first run that does not matter: the unit
file is new, so `Restart step-ca` fires at the end of the play and starts the CA.
It only shows up when the unit is unchanged *and* the CA is initialized in the
same play — a retry after a failed `initialize`, for instance — where the service
comes up one run late.

`step_ca_password_file` is required and has no default; the role has no
`defaults` for it yet ([#39](https://github.com/matonb/step/issues/39)).

The role also provides two handlers. `Restart step-ca` is notified by the unit
file itself, because a changed unit needs the process re-executed — a reload
would leave the running CA on the old `ExecStart`. `Reload step-ca` sends SIGHUP
and is what the `configure` and `provisioner` tasks should notify.

Both handlers, and the two systemd tasks, are skipped under `--check` on a host
with no unit file yet. `systemd_service` refuses a unit it cannot find before it
honours check mode, so the play would otherwise abort rather than report what it
would do. On a host that has already run the role, `--check` reports drift
normally.

## Special Notes

- **Important**: The module should typically be run as the `step` user (using `run_as: step`) to ensure proper access to the CA configuration and keys. When using `run_as`, you must also set `become: true` on the task.
- When a provisioner is added or removed, changes are not visible in the Step CA environment until the service is restarted. The module provides a `restart_required` return value to indicate when this is necessary.
- The `type` parameter is required when creating a new provisioner (`state=present`) but is optional when checking for existence or removing a provisioner.
- X509 duration parameters allow you to control the validity periods of certificates issued by the provisioner.

## License

MIT

## Author Information

Brett Maton (@matonb)
