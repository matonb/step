# Examples

Example playbooks for `matonb.smallstep`. They are written to be read, not run
unmodified: every one targets a `step_ca` inventory group and assumes the CA
lives at `/etc/step-ca` owned by the `step` user. Change the `vars` block to
match your deployment.

| Playbook | Shows |
| --- | --- |
| [`provisioner_config_mode.yml`](provisioner_config_mode.yml) | The default CA, which keeps provisioners in `ca.json`. Adding, removing, capturing a generated password, and the `notify` handler that `restart_required` exists to drive. |
| [`provisioner_admin_mode.yml`](provisioner_admin_mode.yml) | A CA initialized with `--remote-management`. Both credential forms, and why changes need no reload. |
| [`provisioner_reconcile.yml`](provisioner_reconcile.yml) | Declaring `x509_*` durations once and letting re-runs put them back if they drift. |

## Which mode am I in?

If the CA was created with `step ca init --remote-management`, it is in admin
mode. Otherwise it is in config mode. You can confirm from the CA itself:

```console
$ jq .authority.enableAdmin /etc/step-ca/config/ca.json
true
```

The module detects this for you and reports what it used as
`management_mode`. Set `management_mode: admin` or `config` explicitly if you
want a task to fail rather than quietly do the other thing.

## The one thing worth knowing up front

In config mode the module edits `ca.json`, and step-ca only picks that up when
it is reloaded. `restart_required: true` is telling you to do something about
it — pair changing tasks with a handler, as the examples do. In admin mode
changes go through the Admin API and are live immediately, so
`restart_required` is always `false`.

Running these needs the collection installed, or a checkout reachable under an
`ansible_collections/matonb/smallstep` path:

```console
$ ansible-galaxy collection install matonb.smallstep
$ ansible-playbook -i inventory.ini examples/provisioner_config_mode.yml
```
