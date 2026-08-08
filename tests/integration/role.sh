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
# packages on the Debian side only, and a verification switch that RedHat
# honours and Debian refuses - so testing one proves little about the other.
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
        [ ${#CONTAINERS[@]} -gt 0 ] && docker rm -f "${CONTAINERS[@]}" >/dev/null 2>&1 || true
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

# Read from the role rather than restated here, so the suite cannot quietly
# drift from the path the unit file's ConditionFileNotEmpty actually names.
PASSWORD_FILE="$(python3 -c "
import yaml
print(yaml.safe_load(open('$REPO_ROOT/roles/ca_server/defaults/main.yml'))['ca_server_password_file'])
")"
[ -n "$PASSWORD_FILE" ] || die "could not read ca_server_password_file from the role defaults"

# Likewise the repository id. The directories are facts about apt and dnf, but
# the name is the role's, and a suite that hardcoded it would keep passing
# after the role moved the file - which is the drift these paths exist to
# avoid in the first place.
REPOSITORY_NAME="$(python3 -c "
import yaml
print(yaml.safe_load(open('$REPO_ROOT/roles/step_cli/vars/main.yml'))['step_cli_repository_name'])
")"
[ -n "$REPOSITORY_NAME" ] || die "could not read step_cli_repository_name from the role vars"
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
play_expecting_failure() {
    local book=$1 why=$2
    shift 2
    if ansible-playbook -i "$WORK/inventory.yml" "$HERE/$book" "$@" \
        >"$WORK/last.log" 2>&1; then
        cat "$WORK/last.log"
        die "$why"
    fi
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

unit_property() { in_container systemctl show step-ca -p "$1" --value | tr -d '\r'; }

assert_property() {
    local property=$1 expected=$2 message=$3 actual
    actual="$(unit_property "$property")"
    [ "$actual" = "$expected" ] ||
        die "$message (systemd reports $property=$actual, expected $expected)"
}

start_host() {
    local family=$1 dockerfile=$2 image="matonb-step-role-$family"
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
    # The hardest case, and the one three separate guards exist for: the
    # package is not installed, so there is no binary for setcap to read and
    # no unit for systemd_service to find. Nothing may be written either.
    log "[$family] 1. Check mode on an untouched host"
    play role_ca_server.yml --check
    in_container test ! -e /usr/bin/step-ca ||
        die "check mode installed step-ca"
    in_container test ! -e /etc/systemd/system/step-ca.service ||
        die "check mode wrote the unit file"

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
        installed="$(in_container dpkg-query -W -f='${Version}' step-cli)"
    else
        # %{VERSION} alone, which is the form the docs describe for RedHat.
        # dnf takes the revision too, so asking for it here would have left
        # the documented spelling untested.
        installed="$(in_container rpm -q --qf '%{VERSION}' step-cli)"
    fi
    [ -n "$installed" ] || die "could not read the installed step-cli version"
    play role_step_cli.yml -e "step_cli_version=$installed"
    assert_unchanged "pinned to the version already installed"

    # And the pin has to actually reach the package manager. Without this, a
    # separator that rendered into nothing at all would satisfy the assertion
    # above by installing the latest version and reporting no change.
    play_expecting_failure role_step_cli.yml \
        "a version that does not exist was accepted - is the pin reaching the package manager?" \
        -e step_cli_version=0.0.1-nonesuch

    # ca_server builds its own package name, from the same separator. Both
    # roles being pinned here is what stops that construction going untested:
    # ca_server_ca_version is empty everywhere else, so a broken name would
    # render to a bare "step-ca" and every scenario would still pass.
    local installed_ca
    if [ "$family" = debian ]; then
        installed_ca="$(in_container dpkg-query -W -f='${Version}' step-ca)"
    else
        installed_ca="$(in_container rpm -q --qf '%{VERSION}' step-ca)"
    fi
    [ -n "$installed_ca" ] || die "could not read the installed step-ca version"
    play role_ca_server.yml -e "ca_server_ca_version=$installed_ca"
    assert_unchanged "ca_server pinned to the version already installed"
    play_expecting_failure role_ca_server.yml \
        "a nonexistent step-ca version was accepted - is ca_server's pin reaching the package manager?" \
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
