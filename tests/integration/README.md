# Integration tests

Two suites, for the two halves of the collection.

`run.sh` drives `matonb.step.provisioner` against real `step-ca` instances, one
in each management mode. `role.sh` drives the `ca_server` role against
containers running a real PID 1 systemd. Unit tests cannot prove that a flag is
accepted by the real binary, that an Admin API change reaches the running CA, or
that systemd does what a `when` clause assumed — these can.

## `run.sh` — the provisioner module

```bash
bash tests/integration/run.sh
```

Requires `docker`, the `step` CLI and `ansible-playbook`. Two containers are
started on ports 9101 and 9102 and removed on exit, including on failure.
Override with `STEP_TEST_ADMIN_PORT`, `STEP_TEST_CONFIG_PORT` and
`STEP_TEST_IMAGE`.

Not run in CI: it pulls an image and needs a Docker daemon, so it should not
gate a pull request until it has proven stable. Run it before a release, and
whenever command construction or mode handling changes.

## What each suite asserts

### `admin_mode.yml` — CA started with `--remote-management`

- Incomplete admin credentials fail immediately rather than hanging on a prompt.
- The mode auto-detects as `admin` from `authority.enableAdmin`.
- `restart_required` is **false**, and the change is readable from the running
  CA over HTTPS with no restart.
- A JWK provisioner is created through the Admin API and the password the module
  generated genuinely unlocks the key — proven by using it to have the CA sign a
  certificate.
- Claim drift updates only the claim that changed.

### `config_mode.yml` — CA with provisioners in `ca.json`

The CA directory is bind-mounted, so the module edits the same file the running
CA loaded. That is what makes `restart_required` observable rather than merely
asserted: the test checks the change is in `ca.json`, is **not** yet visible
from the CA, and becomes visible after `SIGHUP`.

Every task runs **without reloading first**, which is the point. Add, re-add,
reconcile a claim and remove all happen against a CA whose loaded configuration
is stale, proving the module compares against `ca.json` — the file it writes —
rather than against the CA. This is the regression test for
[#31](https://github.com/matonb/step/issues/31); before the fix the second add
failed with `provisioner with name acme already exists`. A single `SIGHUP` at
the end confirms the CA converges on exactly what `ca.json` holds.

## `role.sh` — the ca_server role

```bash
bash tests/integration/role.sh
```

Nine scenarios, run once per OS family — Debian and Rocky 9 — because the two
install paths diverge: apt's `deb` option against dnf's URL-as-name, different
support packages, and a GPG decision on one side only. Requires `docker`,
`ansible-playbook` and the `community.docker` collection. A full run takes
around seven minutes; `STEP_TEST_FAMILIES=debian` halves it while iterating, and
`STEP_TEST_KEEP` leaves the containers up for inspection.

| # | Scenario | What it pins |
| --- | --- | --- |
| 1 | Check mode on an untouched host | Nothing installed and no unit written; the three guards that make `--check` survive a host with no step-ca binary |
| 2 | Fresh host | Unit written and enabled, `ConditionResult=no`, the `Restart` handler fires without failing the play |
| 3 | Second run | No changes |
| 4 | Check mode, provisioned | Reports drift instead of aborting |
| 5 | Check mode, package but no unit | Completes; without the guard this aborts with `Could not find the requested service step-ca` |
| 6 | CA initialized | The service-state gate opens and the CA serves |
| 7 | Hand-edited unit | Restored **and** the process re-executed — MainPID must change |
| 8 | Empty password file | The gate closes again; the run reports no change |
| 9 | Reload | The handler fires **and** MainPID is unchanged |

7 and 9 are the ones that matter most: they distinguish restart from reload,
which is the error the role's first design made. 9 asserts the handler ran
before comparing PIDs, because an unchanged PID is also what a handler that
never fired would produce.

Four defects were found by running this rather than by reading anything: a
missing `libcap2-bin`, a missing `procps`, an apt cache `--check` will not
refresh, and a unit whose `ExecReload` had no `/bin/kill`.

## One thing worth knowing

**`ca_config` has to be explicit against a containerised CA.** The container
writes container-absolute paths into `config/defaults.json`:

```json
{ "ca-config": "/home/step/config/ca.json", "root": "/home/step/certs/root_ca.crt" }
```

The step CLI loads that file as its flag defaults, so a host-side run resolves
paths that do not exist. This affects anyone managing a containerised CA from
outside the container, not just these tests.
