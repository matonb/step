#!/usr/bin/env bash
# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
#
# Runs both roles against containers with a real PID 1 systemd, once per
# supported OS family.
#
# The role's design rests on things only systemd can answer: that it skips a
# unit whose ConditionFileNotEmpty is unmet, that systemctl still exits 0 when
# it does, and that systemd_service refuses a unit it cannot find before it
# honours check mode. Reading the ansible-core source got three of those right
# and one wrong, so this runs them instead. Four further defects - a missing
# libcap, a missing procps, an apt cache that --check will not refresh, and a
# unit whose ExecReload had no /bin/kill - were found only by running it.
#
# Requires docker and ansible-playbook, plus the community.docker collection
# for the connection plugin. Everything it creates is removed on exit,
# including on failure; set STEP_TEST_KEEP to leave the containers behind.

set -euo pipefail

CA_PASSWORD="integration-test-password"

# family:dockerfile. Both are exercised in full. The roles install by package
# name from one repository now, but the plumbing around it still diverges - an
# apt sources file and a keyring against a yum_repository stanza, support
# packages on the Debian side only, a verification switch that RedHat honours
# and Debian refuses, and a first --check that mentions the repository on
# RedHat and not on Debian - so testing one proves little about the other.
#
# That last one is intended rather than a gap in either the roles or this
# suite; install_Debian.yml carries the reasoning. Scenario 1 asserts what both
# families must not do, which is write anything, and leaves what they report to
# the family that can report it.
FAMILIES=(
    "debian:Dockerfile.debian"
    "redhat:Dockerfile.redhat"
)

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$REPO_ROOT/tests/integration"
WORK="$(mktemp -d)"
CONTAINERS=()

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
step() { printf '\033[1m    %s\033[0m\n' "$*"; }
die() { echo "$*" >&2; exit 1; }

cleanup() {
    local status=$?
    # The EXIT trap fires again on the explicit exit below, and would otherwise
    # run all of this a second time and print the verdict twice.
    trap - EXIT INT TERM
    if [ -n "${STEP_TEST_KEEP:-}" ]; then
        log "STEP_TEST_KEEP set; leaving ${CONTAINERS[*]:-nothing} and $WORK in place"
        echo "    inventory: $WORK/inventory.yml"
        echo "    remove with: docker rm -f ${CONTAINERS[*]:-}"
    else
        log "Cleaning up"
        if [ ${#CONTAINERS[@]} -gt 0 ]; then
            docker rm -f "${CONTAINERS[@]}" >/dev/null 2>&1 || true
        fi
        rm -rf "$WORK" 2>/dev/null || echo "WARNING: could not remove $WORK" >&2
    fi
    if [ "$status" -eq 0 ]; then log "PASSED"; else log "FAILED (exit $status)"; fi
    exit "$status"
}
# INT/TERM as well as EXIT, so Ctrl-C during a wait still tears the containers
# down rather than leaving them to collide with the next run.
trap cleanup EXIT INT TERM

require() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}
require docker
require ansible-playbook
require python3

ansible-galaxy collection list community.docker >/dev/null 2>&1 ||
    die "community.docker is required for the docker connection plugin"

# Read from the roles rather than restated here, so the suite cannot quietly
# drift from what the roles actually use: the path the unit file's
# ConditionFileNotEmpty names, the repository id both package managers look
# for, and the keyring scenario 1 asserts is absent.
#
# One invocation that does its own checking, because a guard on the result is
# not enough. `VAR="$(cmd)"` adopts cmd's exit status, so under `set -e` a
# missing key aborted at the assignment with a raw traceback and never reached
# the die() written to explain it. A key present but null was worse: python
# prints "None", a guard on emptiness passes, and the suite spends the rest of
# the run testing a path called None.
ROLE_VARS="$(python3 - "$REPO_ROOT" <<'PY'
import sys

import yaml

WANTED = (
    ("roles/ca_server/defaults/main.yml", "ca_server_password_file"),
    ("roles/step_cli/vars/main.yml", "step_cli_repository_name"),
    ("roles/step_cli/vars/main.yml", "step_cli_repository_keyring"),
)

root = sys.argv[1]
for relative, key in WANTED:
    with open(f"{root}/{relative}") as handle:
        defined = yaml.safe_load(handle)
    # An empty or comment-only file loads as None, and `key not in None` is a
    # TypeError - a traceback, which is the thing this block exists to replace.
    if not isinstance(defined, dict):
        sys.exit(f"{relative} did not parse as a mapping")
    if key not in defined:
        sys.exit(f"{relative} no longer defines {key}")
    value = defined[key]
    if not isinstance(value, str) or not value.strip():
        sys.exit(f"{relative} defines {key} as {value!r}, which is not a path")
    print(f"{key}\t{value}")
PY
)" || die "could not read the role variables this suite is written against"

# Matched on the key rather than read off in order, so adding a fourth entry
# to WANTED without a home here is a named failure instead of three variables
# quietly holding each other's values.
while IFS=$'\t' read -r key value; do
    case "$key" in
        ca_server_password_file) PASSWORD_FILE="$value" ;;
        step_cli_repository_name) REPOSITORY_NAME="$value" ;;
        step_cli_repository_keyring) KEYRING="$value" ;;
        *) die "the suite has no home for the role variable $key" ;;
    esac
done <<<"$ROLE_VARS"
: "${PASSWORD_FILE:?the role variables did not yield ca_server_password_file}"
: "${REPOSITORY_NAME:?the role variables did not yield step_cli_repository_name}"
: "${KEYRING:?the role variables did not yield step_cli_repository_keyring}"
DEB_SOURCES="/etc/apt/sources.list.d/$REPOSITORY_NAME.list"
EL_REPO="/etc/yum.repos.d/$REPOSITORY_NAME.repo"

# The role resolves as matonb.step.ca_server, so the checkout has to be
# reachable under that path. A symlink is enough for Ansible itself.
COLLECTIONS="$WORK/collections"
mkdir -p "$COLLECTIONS/ansible_collections/matonb"
ln -s "$REPO_ROOT" "$COLLECTIONS/ansible_collections/matonb/step"
export ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS"

CONTAINER=""

play() {
    local book=$1
    shift
    ansible-playbook -i "$WORK/inventory.yml" "$HERE/$book" "$@" >"$WORK/last.log" 2>&1 ||
        { cat "$WORK/last.log"; die "playbook $book failed"; }
}

# For the cases where failing is the assertion. Without this, proving that a
# bad input is rejected would need play() not to die on it.
#
# A play has plenty of ways to fail that have nothing to do with the input
# under test - an unreachable container, a role that no longer parses, an
# assert firing somewhere else - so a non-zero exit on its own says only that
# something went wrong. The caller names the message the failure has to carry,
# and a play that fails for any other reason is reported as such rather than
# quietly counted as a pass.
play_expecting_failure() {
    # Checked rather than left to `set -u`, which would report an unbound $3
    # from inside this function and name neither the helper nor the caller.
    # Non-empty as well as present: `grep -qE ""` matches any non-empty file,
    # so an empty pattern is the vacuous assertion this argument exists to
    # prevent, wearing the appearance of a real one.
    if [ $# -lt 3 ] || [ -z "$3" ]; then
        die "play_expecting_failure needs a book, a reason and a non-empty pattern"
    fi
    local book=$1 why=$2 pattern=$3
    shift 3
    if ansible-playbook -i "$WORK/inventory.yml" "$HERE/$book" "$@" \
        >"$WORK/last.log" 2>&1; then
        cat "$WORK/last.log"
        die "$why"
    fi
    # -- because the likely misuse is omitting the pattern, which slides the
    # caller's own -e into its place for grep to read as an option.
    grep -qE -- "$pattern" "$WORK/last.log" || {
        cat "$WORK/last.log"
        die "$why (the play did fail, but not with /$pattern/)"
    }
}

# Ansible's recap is the only place the per-run change count is reported, and
# idempotence is exactly the claim being tested.
assert_unchanged() {
    grep -qE 'changed=0 ' "$WORK/last.log" ||
        { cat "$WORK/last.log"; die "$1: expected no changes"; }
}

assert_changed() {
    grep -qE 'changed=[1-9]' "$WORK/last.log" ||
        { cat "$WORK/last.log"; die "$1: expected changes"; }
}

# The RUNNING HANDLER banner is printed before the handler's `when` is
# evaluated, so a handler that is notified and then skipped produces it too.
# Grepping for the banner alone therefore proves only that something notified -
# which is how the first version of this assertion managed to be vacuous. What
# separates the two is the result line that follows it.
assert_handler_ran() {
    local banner="RUNNING HANDLER \[matonb.step.ca_server : $1\]" outcome
    outcome="$(sed 's/\x1b\[[0-9;]*m//g' "$WORK/last.log" |
        grep -A3 -E "$banner" |
        grep -m1 -oE '^(changed|ok|skipping|fatal):' || true)"
    case "$outcome" in
        changed: | ok:) ;;
        "")
            cat "$WORK/last.log"
            die "the $1 handler was never notified"
            ;;
        *)
            cat "$WORK/last.log"
            die "the $1 handler was notified but reported ${outcome%:} rather than running"
            ;;
    esac
}

# A task silently skipped and a task that ran and found nothing to do both
# leave the play green, which is exactly the difference some of these gates
# turn on. Same shape as assert_handler_ran: the banner alone proves only that
# Ansible reached the task.
assert_task_ran() {
    local task=$1 outcome
    outcome="$(sed 's/\x1b\[[0-9;]*m//g' "$WORK/last.log" |
        grep -A3 -E "TASK \[matonb\.step\.[a-z_]+ : $task\]" |
        grep -m1 -oE '^(changed|ok|skipping|fatal):' || true)"
    case "$outcome" in
        changed: | ok:) ;;
        "")
            cat "$WORK/last.log"
            die "the '$task' task never appeared"
            ;;
        *)
            cat "$WORK/last.log"
            die "the '$task' task reported ${outcome%:} rather than running"
            ;;
    esac
}

in_container() { docker exec "$CONTAINER" "$@"; }

unit_property() {
    in_container systemctl show step-ca -p "$1" --value | tr -d '\r' ||
        die "could not read $1 from systemd - is the container still up?"
}

assert_property() {
    local property=$1 expected=$2 message=$3 actual
    actual="$(unit_property "$property")"
    [ "$actual" = "$expected" ] ||
        die "$message (systemd reports $property=$actual, expected $expected)"
}

start_host() {
    local family=$1 dockerfile=$2
    local image="matonb-step-role-$family"
    CONTAINER="matonb-step-it-role-$family"
    CONTAINERS+=("$CONTAINER")

    step "building the $family image"
    docker build -q -f "$HERE/$dockerfile" -t "$image" "$HERE" >/dev/null

    step "starting $CONTAINER"
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    # --privileged and the cgroup mount are what let systemd boot as PID 1.
    docker run -d --name "$CONTAINER" --privileged --cgroupns=host \
        -v /sys/fs/cgroup:/sys/fs/cgroup:rw "$image" >/dev/null

    # "degraded" as well as "running": a container has no hardware to speak of,
    # so a couple of units routinely fail and that is not this suite's problem.
    local boot_state=""
    for _ in $(seq 1 60); do
        boot_state="$(in_container systemctl is-system-running 2>/dev/null || true)"
        case "$boot_state" in
            running | degraded) break ;;
        esac
        sleep 1
    done
    case "$boot_state" in
        running | degraded) ;;
        *) die "systemd did not come up in $CONTAINER (state: ${boot_state:-none})" ;;
    esac

    cat >"$WORK/inventory.yml" <<EOF
all:
  hosts:
    $CONTAINER:
      ansible_connection: community.docker.docker
      ansible_user: root
      ansible_python_interpreter: /usr/bin/python3
  vars:
    step_role_ca_password: $CA_PASSWORD
step_role:
  hosts:
    $CONTAINER:
EOF
}

run_scenarios() {
    local family=$1

    # --- 1: check mode against a host that has nothing --------------------
    # The hardest case, and the one four separate guards exist for. The
    # package is not installed, so there is no binary for setcap to read and
    # no unit for systemd_service to find; the repository is not configured,
    # so neither role's install task can ask the package manager anything and
    # both sit behind a stat. Nothing may be written either - not the binary,
    # not the unit, and not the repository or the key that signs it.
    log "[$family] 1. Check mode on an untouched host"
    play role_ca_server.yml --check
    in_container test ! -e /usr/bin/step-ca ||
        die "check mode installed step-ca"
    in_container test ! -e /etc/systemd/system/step-ca.service ||
        die "check mode wrote the unit file"

    # The repository too, which "nothing may be written" was silent about even
    # though it is the harder half.
    #
    # Each of the three was checked by reinstating the defect it is meant to
    # catch, because an assertion here that cannot fail is worse than none -
    # it reads as cover. What it took differs, and the recipes are recorded
    # so the next person can reproduce them rather than assume they are dead:
    #
    #   RedHat repo    one edit. check_mode: false on yum_repository, which
    #                  nothing gates, and the file appears.
    #   Debian keyring three. The block gate skips the whole block on an
    #                  untouched host, so forcing the get_url alone does
    #                  nothing: the gate has to be widened, and the
    #                  ca-certificates install forced, before the fetch can
    #                  even reach an HTTPS host.
    #   Debian repo    six - the whole "configure the repository for real so
    #                  --check can report on packages" change. Writing the
    #                  file without also refreshing the cache does not test
    #                  this: apt then has a repository it has never read, and
    #                  the play dies at ca_server with "No package matching
    #                  'step-ca' is available" before reaching here. Forcing
    #                  the refresh as well - which needs check_mode: false of
    #                  its own, since the apt module makes update_cache a
    #                  no-op under --check whatever its `when` says - leaves
    #                  the play green and this the only thing that catches it.
    #
    # RedHat does not cascade that way because dnf resolves against metadata
    # it fetches on demand, where apt resolves against lists it refreshes only
    # when told.
    if [ "$family" = debian ]; then
        in_container test ! -e "$DEB_SOURCES" ||
            die "check mode wrote the apt sources file"
        in_container test ! -e "$KEYRING" ||
            die "check mode installed the repository signing key"
    else
        in_container test ! -e "$EL_REPO" ||
            die "check mode wrote the yum repository"
    fi

    # --- 2: a fresh host, through ca_server alone -------------------------
    # ca_server is applied to a host that has had nothing, so the smallstep
    # repository and the CLI can only arrive through its dependency on
    # step_cli. Asserting the CLI here is what makes that dependency load
    # bearing: with step_cli run first, as this suite used to, removing the
    # dependency altogether changed nothing and every scenario still passed.
    #
    # The unit is written and enabled, but nothing starts: no CA and no
    # password file, so systemd's conditions are unmet. The Restart handler
    # still fires and must not fail the play.
    log "[$family] 2. Fresh host, ca_server alone"
    play role_ca_server.yml
    assert_changed "fresh run"
    in_container step version >/dev/null 2>&1 ||
        die "ca_server did not bring in the step CLI - is the step_cli dependency still declared?"
    if [ "$family" = debian ]; then
        in_container test -f "$DEB_SOURCES" ||
            die "the smallstep repository was never configured"
    else
        in_container test -f "$EL_REPO" ||
            die "the smallstep repository was never configured"
    fi
    assert_handler_ran "Restart step-ca"
    in_container test -f /etc/systemd/system/step-ca.service ||
        die "the unit file was not written"
    assert_property UnitFileState enabled "the service was not enabled, so the CA would not survive a reboot"
    assert_property ConditionResult no "systemd should have refused to start an uninitialized CA"
    assert_property ActiveState inactive "the CA started without a configuration"

    # --- 3: step_cli on its own, over the top -----------------------------
    # Its own assertions - that the CLI runs and that the package manager says
    # it came from smallstep's repository - plus the case nothing covered while
    # both roles defined the repository themselves. Each was idempotent against
    # itself, so the suite stayed green while the file could ping-pong between
    # them on alternating runs. Only running step_cli after ca_server shows it.
    log "[$family] 3. step_cli after ca_server changes nothing"
    play role_step_cli.yml
    assert_unchanged "step_cli after ca_server"
    local lines refresh
    if [ "$family" = debian ]; then
        # `|| true` because grep -c exits 1 on no matches and 2 on a missing
        # file, and a bare assignment adopts that status - so under `set -e`
        # the suite would abort on docker's stderr and never reach the die
        # below. Nought and "file gone" are exactly what this is looking for.
        lines="$(in_container grep -c '^deb ' "$DEB_SOURCES" || true)"
        [ "$lines" = "1" ] ||
            die "expected one deb line in the smallstep sources file, found '${lines:-none}'"
        refresh="$(in_container apt-get update -qq 2>&1)" ||
            die "apt could not read its sources: $refresh"
    else
        refresh="$(in_container dnf -q --refresh makecache 2>&1)" ||
            die "dnf could not read its repositories: $refresh"
    fi

    # --- 4: version pinning -----------------------------------------------
    # Both version variables default to empty, so nothing else in this suite
    # renders the separator at all - apt wants name=version, dnf wants
    # name-version, and getting it the wrong way round produces "unable to
    # locate package" rather than anything subtle.
    #
    # Pinned to the version already installed, because by this point it is,
    # and apt refuses a downgrade unless explicitly asked. That still
    # exercises the thing that can break: the spec has to be one the package
    # manager understands. The version is read off the host rather than
    # written here, so this does not need editing when upstream moves.
    log "[$family] 4. A pinned version is accepted"
    local installed
    if [ "$family" = debian ]; then
        # shellcheck disable=SC2016  # ${Version} is dpkg-query's syntax, not the shell's
        installed="$(in_container dpkg-query -W -f='${Version}' step-cli)" || installed=""
    else
        # %{VERSION} alone, which is the form the docs describe for RedHat.
        # dnf takes the revision too, so asking for it here would have left
        # the documented spelling untested.
        installed="$(in_container rpm -q --qf '%{VERSION}' step-cli)" || installed=""
    fi
    [ -n "$installed" ] || die "could not read the installed step-cli version"
    play role_step_cli.yml -e "step_cli_version=$installed"
    assert_unchanged "pinned to the version already installed"

    # And the pin has to actually reach the package manager. Without this, a
    # separator that rendered into nothing at all would satisfy the assertion
    # above by installing the latest version and reporting no change.
    #
    # Both strings are ansible-core's rather than the package manager's own -
    # apt itself says "Version '0.0.1-nonesuch' for 'step-cli' was not found"
    # and dnf says "No match for argument", and the modules restate both. So
    # it is ansible-core, not apt or dnf, that these track: if one of them
    # stops matching, that is where the wording moved.
    #
    # What earns the match is that each restatement quotes the spec back with
    # the separator in it, so this covers how the pin rendered rather than
    # merely that something went wrong.
    #
    # Where they appear differs. The apt module fails with its string as msg;
    # the dnf module puts its own in the failures list and leaves msg as the
    # generic "Failed to install some of the specified packages". Both land in
    # the log, which is what this greps, but neither is reliably the msg.
    local cli_rejected ca_rejected
    if [ "$family" = debian ]; then
        cli_rejected='no available installation candidate for step-cli=0\.0\.1-nonesuch'
        ca_rejected='no available installation candidate for step-ca=0\.0\.1-nonesuch'
    else
        cli_rejected='No package step-cli-0\.0\.1-nonesuch available'
        ca_rejected='No package step-ca-0\.0\.1-nonesuch available'
    fi
    play_expecting_failure role_step_cli.yml \
        "a version that does not exist was accepted - is the pin reaching the package manager?" \
        "$cli_rejected" \
        -e step_cli_version=0.0.1-nonesuch

    # ca_server builds its own package name, from the same separator. Both
    # roles being pinned here is what stops that construction going untested:
    # ca_server_ca_version is empty everywhere else, so a broken name would
    # render to a bare "step-ca" and every scenario would still pass.
    local installed_ca
    if [ "$family" = debian ]; then
        # shellcheck disable=SC2016  # ${Version} is dpkg-query's syntax, not the shell's
        installed_ca="$(in_container dpkg-query -W -f='${Version}' step-ca)" || installed_ca=""
    else
        installed_ca="$(in_container rpm -q --qf '%{VERSION}' step-ca)" || installed_ca=""
    fi
    [ -n "$installed_ca" ] || die "could not read the installed step-ca version"
    play role_ca_server.yml -e "ca_server_ca_version=$installed_ca"
    assert_unchanged "ca_server pinned to the version already installed"
    play_expecting_failure role_ca_server.yml \
        "a nonexistent step-ca version was accepted - is ca_server's pin reaching the package manager?" \
        "$ca_rejected" \
        -e ca_server_ca_version=0.0.1-nonesuch

    # --- 5: a repository this role does not manage ------------------------
    # step_cli_manage_repository: false means "mine is configured elsewhere".
    # Both install gates stat the path the role would have written, so without
    # a clause for the unmanaged case --check answered such a play two ways:
    # step_cli reporting on the CLI it would install, ca_server silently
    # skipping step-ca. "Nothing to do" for an absent package is wrong rather
    # than cautious, and nothing exercised it until this existed.
    #
    # The repository is moved rather than removed, so it is still there to
    # install from - which is the whole point of the setting - and moved back
    # afterwards so the scenarios below see the host they expect.
    log "[$family] 5. --check reports on step-ca with an unmanaged repository"
    local owned
    if [ "$family" = debian ]; then
        owned=/etc/apt/sources.list.d/operator-owned.list
        in_container mv "$DEB_SOURCES" "$owned"
    else
        owned=/etc/yum.repos.d/operator-owned.repo
        in_container mv "$EL_REPO" "$owned"
    fi
    play role_ca_server.yml --check -e step_cli_manage_repository=false
    assert_task_ran "Install step-ca"
    if [ "$family" = debian ]; then
        in_container mv "$owned" "$DEB_SOURCES"
    else
        in_container mv "$owned" "$EL_REPO"
    fi

    # --- 6: idempotence ---------------------------------------------------
    log "[$family] 6. Second run changes nothing"
    play role_ca_server.yml
    assert_unchanged "second run"

    # --- 7: check mode on a provisioned host ------------------------------
    # The systemd tasks are gated on the unit file existing rather than on
    # ansible_check_mode alone, so here they run and report drift.
    log "[$family] 7. Check mode against a provisioned host"
    play role_ca_server.yml --check
    assert_unchanged "check mode, provisioned"

    # --- 8: check mode with the package installed but no unit -------------
    # Remove the guard and this aborts with "Could not find the requested
    # service step-ca: host".
    log "[$family] 8. Check mode with no unit file"
    in_container rm -f /etc/systemd/system/step-ca.service
    in_container systemctl daemon-reload
    play role_ca_server.yml --check
    in_container test ! -f /etc/systemd/system/step-ca.service ||
        die "check mode wrote the unit file"
    play role_ca_server.yml

    # --- 9: the gate opens once the CA exists -----------------------------
    log "[$family] 9. Service starts once the CA is initialized"
    play role_initialize.yml
    play role_ca_server.yml
    assert_changed "run after initialization"
    assert_property ActiveState active "the CA did not start once its configuration existed"
    in_container step ca health --ca-url https://localhost:8443 \
        --root /etc/step-ca/certs/root_ca.crt >/dev/null 2>&1 ||
        die "the CA is running but not serving"

    # --- 10: a changed unit re-executes the process ------------------------
    # The original design used a reload handler here, which leaves a running
    # CA on the old ExecStart. Comparing MainPID is what catches that.
    log "[$family] 10. A changed unit file restarts the service"
    local pid_before pid_after
    pid_before="$(unit_property MainPID)"
    in_container bash -c 'echo "# hand-edited" >> /etc/systemd/system/step-ca.service'
    play role_ca_server.yml
    assert_changed "unit file restored"
    assert_handler_ran "Restart step-ca"
    in_container grep -q 'hand-edited' /etc/systemd/system/step-ca.service &&
        die "the hand-edited unit file was not restored"
    pid_after="$(unit_property MainPID)"
    [ "$pid_before" != "$pid_after" ] ||
        die "a changed unit file did not re-execute step-ca (MainPID stayed $pid_before)"

    # --- 11: the password half of the gate ---------------------------------
    # systemctl exits 0 when it skips a unit, so without this half the role
    # would report a change every run while the CA never came up.
    log "[$family] 11. An empty password file closes the gate"
    in_container systemctl stop step-ca
    in_container bash -c ": > $PASSWORD_FILE"
    play role_ca_server.yml
    assert_unchanged "empty password file"
    assert_property ActiveState inactive "the CA started without a password file"
    in_container bash -c "printf '%s\n' '$CA_PASSWORD' > $PASSWORD_FILE"
    in_container systemctl start step-ca
    sleep 2

    # --- 12: reload keeps the process --------------------------------------
    log "[$family] 12. Reload sends SIGHUP without restarting"
    pid_before="$(unit_property MainPID)"
    play role_reload.yml
    # Asserted before the PID comparison: an unchanged PID is also what a
    # handler that never ran would produce.
    assert_handler_ran "Reload step-ca"
    pid_after="$(unit_property MainPID)"
    [ "$pid_before" = "$pid_after" ] ||
        die "Reload restarted step-ca instead of signalling it (MainPID $pid_before -> $pid_after)"
    assert_property ActiveState active "the CA did not survive a reload"
}

# STEP_TEST_FAMILIES narrows the run while iterating on one path; unset it, and
# both are exercised. A change to anything outside install_<family>.yml wants
# both before it is believed.
for entry in "${FAMILIES[@]}"; do
    family="${entry%%:*}"
    dockerfile="${entry#*:}"
    if [ -n "${STEP_TEST_FAMILIES:-}" ] && [[ " ${STEP_TEST_FAMILIES} " != *" ${family} "* ]]; then
        log "$family (skipped by STEP_TEST_FAMILIES)"
        continue
    fi
    log "$family"
    start_host "$family" "$dockerfile"
    run_scenarios "$family"
done
