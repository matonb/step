# matonb.smallstep.ca_server

Installs [step-ca](https://smallstep.com/docs/step-ca/), creates the `step`
user, grants the binary `CAP_NET_BIND_SERVICE` so it can bind 443 without
running as root, templates a sandboxed systemd unit, and manages the service.

**It depends on `matonb.smallstep.step_cli`**, which Ansible runs first. That
role owns the smallstep package repository and the step CLI, so including
`ca_server` alone still gives you a host that can initialize and manage its own
CA — `matonb.smallstep.initialize` shells out to `step ca init`. Configure the
repository through `step_cli`'s variables; there is deliberately only one set.

## Requirements

- ansible-core 2.14 or later. The role uses `ansible.builtin.systemd_service`
  for the enable and state tasks and for both handlers, which does not exist
  before 2.14.
- `community.general`, for `community.general.capabilities`.
- Debian bookworm, Ubuntu jammy or noble, or EL 9.

## Role variables

| Variable                    | Default                     | Description                                                                       |
| --------------------------- | --------------------------- | --------------------------------------------------------------------------------- |
| `ca_server_ca_version`      | `""` (unpinned)             | step-ca version, as the package manager spells it                                 |
| `ca_server_packages`        | built from the version      | Package names. Replace outright to install from your own repository               |
| `ca_server_password_file`   | `/etc/step-ca/password.txt` | File holding the password that decrypts the CA's keys                             |
| `ca_server_service_enabled` | `true`                      | Whether step-ca comes back after a reboot                                         |
| `ca_server_service_state`   | `started`                   | `started`, `stopped`, `restarted`, `reloaded`, or null to leave the service alone |

Leave `ca_server_ca_version` empty for whatever the repository currently holds,
or pin it as the package manager spells it: Debian needs the upstream version
and the Debian revision together (`0.30.2-1`), RedHat takes the version on its
own (`0.30.2`) and accepts version-release too.

Empty is not "track the latest". The install is `state: present`, so an
unpinned version is whatever the repository held when the package first
arrived. Lowering a version is also not a downgrade — apt refuses one unless
asked, and dnf treats an older package as already satisfied. Set
`ca_server_packages` outright to pin backwards.

## The password file is yours to place

**The role does not create it.** That file is the key to the CA. Until it
exists and is non-empty the service will not start, and it must be readable by
the `step` user, since that is who step-ca runs as.

## Service state

`started` is the idempotent choice. `restarted` and `reloaded` act on every run
by design, so they also report `changed` on every run — that is the option
working, not a bug.

The state is applied only once both files the unit's `ConditionFileNotEmpty`
directives name are present and non-empty: `config/ca.json` and
`ca_server_password_file`. Before that there is nothing to run, and systemd
would skip the start with a zero exit while Ansible reported a change on every
run — success on a service that never came up.

Both are checked while the role runs, so a CA initialized later in the same
play is not seen until the next one. On a first run that does not matter: the
unit file is new, so `Restart step-ca` fires at the end of the play and starts
the CA. It only shows up when the unit is unchanged *and* the CA is initialized
in the same play — a retry after a failed `initialize`, for instance — where
the service would otherwise come up one run late.

## Handlers

| Handler           | Notified by                                    |
| ----------------- | ---------------------------------------------- |
| `Restart step-ca` | The unit file, which needs the process re-executed |
| `Reload step-ca`  | What `configure` and `provisioner` tasks should notify |

`Reload step-ca` sends SIGHUP via the unit's `ExecReload`, which is cheaper
than a restart and does not drop in-flight requests.

Both handlers, and the two systemd tasks, are skipped under `--check` on a host
with no unit file yet: `systemd_service` refuses a unit it cannot find before
it honours check mode, so the play would otherwise abort rather than report
what it would do.

## Dependencies

- `matonb.smallstep.step_cli`

## Example playbook

```yaml
- name: Build a CA
  hosts: ca
  roles:
    - matonb.smallstep.ca_server

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
      matonb.smallstep.initialize:
        name: Example CA
        path: /etc/step-ca
        dns: [ca.example.com]
        address: ":443"
        password_file: "{{ ca_server_password_file }}"
        provisioner_password_file: "{{ ca_server_password_file }}"

    # The role's service task ran before the CA existed, so it skipped. On a
    # first run this is redundant - the unit file is new, so the role's own
    # handler starts the CA at the end of the play. It is what starts the CA on
    # a rerun where the unit is unchanged and no handler fires.
    - name: Start the CA now that it has a configuration
      become: true
      ansible.builtin.systemd_service:
        name: step-ca
        state: started
```

The two `password_file` values reference the role's own variable rather than
repeating the path, so changing `ca_server_password_file` moves both the unit's
`ConditionFileNotEmpty` and the file the module reads together.

## More

Full documentation, including the collection's modules, is in the
[collection README](https://github.com/matonb/smallstep/blob/main/README.md).

## License

GPL-3.0-or-later

## Author

Brett Maton
