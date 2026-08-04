# Integration tests

Drives `matonb.step.provisioner` against real `step-ca` instances, one in each
management mode. Unit tests cannot prove that a flag is accepted by the real
binary, or that an Admin API change reaches the running CA — these can.

## Running

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

## Two things worth knowing

**`ca_config` has to be explicit against a containerised CA.** The container
writes container-absolute paths into `config/defaults.json`:

```json
{ "ca-config": "/home/step/config/ca.json", "root": "/home/step/certs/root_ca.crt" }
```

The step CLI loads that file as its flag defaults, so a host-side run resolves
paths that do not exist. This affects anyone managing a containerised CA from
outside the container, not just these tests.

**In config mode, `list` and `add` read different sources.** `list` queries the
CA's *loaded* configuration over HTTP, while `add`/`remove` edit `ca.json`. Until
step-ca reloads, the two disagree, so re-running a play before the reload will
try to add a provisioner that is already in the file. This is why the module
reports `restart_required`, and why real plays pair these tasks with
`notify: restart step-ca`. The suite reloads after each change to mirror that.
