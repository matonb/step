#!/usr/bin/env bash
# Copyright: (c) 2025, Brett Maton <matonb@users.noreply.github.com>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
#
# Runs the provisioner module against real step-ca instances, one in each
# management mode. Unit tests cannot prove that a flag is accepted by the real
# binary or that an Admin API change lands in the running CA; this can.
#
# Requires docker, the step CLI, and ansible-playbook. Everything it creates is
# removed on exit, including on failure.

set -euo pipefail

IMAGE="${STEP_TEST_IMAGE:-smallstep/step-ca:latest}"
ADMIN_CONTAINER="matonb-step-it-admin"
CONFIG_CONTAINER="matonb-step-it-config"
ADMIN_PORT="${STEP_TEST_ADMIN_PORT:-9101}"
CONFIG_PORT="${STEP_TEST_CONFIG_PORT:-9102}"
CA_PASSWORD="integration-test-password"
# Per-run volume name. A surviving volume would make the next run's CA come up
# already initialised, silently ignoring DOCKER_STEPCA_INIT_* and serving the
# previous run's PKI.
ADMIN_VOLUME="${ADMIN_CONTAINER}-data-$$"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { echo "$*" >&2; exit 1; }

cleanup() {
    local status=$?
    log "Cleaning up"
    docker rm -f "$ADMIN_CONTAINER" "$CONFIG_CONTAINER" >/dev/null 2>&1 || true
    if ! docker volume rm "$ADMIN_VOLUME" >/dev/null 2>&1; then
        # Only matters if it still exists; a never-created volume is fine.
        docker volume inspect "$ADMIN_VOLUME" >/dev/null 2>&1 &&
            echo "WARNING: could not remove volume $ADMIN_VOLUME; remove it before re-running" >&2
    fi
    # The config CA directory is written by the container as uid 1000. If that
    # is not us, drop privileges through the image itself rather than failing.
    if [ -d "$WORK" ] && ! rm -rf "$WORK" 2>/dev/null; then
        docker run --rm -u 0:0 -v "$WORK:/w" "$IMAGE" rm -rf /w/config-ca >/dev/null 2>&1 || true
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
require curl
require docker
require step
require ansible-playbook

# The container writes as uid 1000 into the bind-mounted config CA directory,
# and this script reads and greps those files.
[ "$(id -u)" -eq 1000 ] || die "this suite needs to run as uid 1000 to share the bind-mounted CA directory (found $(id -u))"

# A container left behind by a SIGKILLed run would make `docker run --name`
# fail outright.
docker rm -f "$ADMIN_CONTAINER" "$CONFIG_CONTAINER" >/dev/null 2>&1 || true

# The module resolves `ansible_collections.matonb.step...`, so the checkout has
# to be reachable under that path. A symlink is enough for Ansible itself.
COLLECTIONS="$WORK/collections"
mkdir -p "$COLLECTIONS/ansible_collections/matonb"
ln -s "$REPO_ROOT" "$COLLECTIONS/ansible_collections/matonb/step"
export ANSIBLE_COLLECTIONS_PATH="$COLLECTIONS"

wait_for_ca() {
    local url=$1 root=$2 name=$3 container=$4
    for _ in $(seq 1 30); do
        if curl -fsS --cacert "$root" -o /dev/null "$url/health" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "$name did not become ready at $url" >&2
    docker logs "$container" 2>&1 | tail -20 >&2
    return 1
}

###############################################################################
log "Starting admin-mode CA (--remote-management) on :$ADMIN_PORT"
###############################################################################
docker run -d --name "$ADMIN_CONTAINER" \
    -p "$ADMIN_PORT:9000" \
    -v "$ADMIN_VOLUME:/home/step" \
    -e "DOCKER_STEPCA_INIT_NAME=Integration Admin CA" \
    -e "DOCKER_STEPCA_INIT_DNS_NAMES=localhost,127.0.0.1" \
    -e "DOCKER_STEPCA_INIT_REMOTE_MANAGEMENT=true" \
    -e "DOCKER_STEPCA_INIT_PASSWORD=$CA_PASSWORD" \
    "$IMAGE" >/dev/null

ADMIN_DIR="$WORK/admin"
mkdir -p "$ADMIN_DIR/steppath"
# The CA needs a moment to generate its PKI before these files exist.
copied=false
for _ in $(seq 1 30); do
    if docker cp "$ADMIN_CONTAINER:/home/step/certs/root_ca.crt" "$ADMIN_DIR/root_ca.crt" 2>/dev/null; then
        copied=true
        break
    fi
    sleep 1
done
if [ "$copied" != true ]; then
    docker logs "$ADMIN_CONTAINER" 2>&1 | tail -20 >&2
    die "admin CA never generated its PKI"
fi
docker cp "$ADMIN_CONTAINER:/home/step/config/ca.json" "$ADMIN_DIR/ca.json"
printf '%s' "$CA_PASSWORD" > "$ADMIN_DIR/pass"
chmod 600 "$ADMIN_DIR/pass"

ADMIN_URL="https://localhost:$ADMIN_PORT"
wait_for_ca "$ADMIN_URL" "$ADMIN_DIR/root_ca.crt" "admin CA" "$ADMIN_CONTAINER"

###############################################################################
log "Starting config-mode CA (bind-mounted ca.json) on :$CONFIG_PORT"
###############################################################################
# Bind-mounting means the host-side module and the containerised CA share one
# ca.json, so `restart_required` can be observed rather than assumed. The image
# runs as uid/gid 1000, which matches a typical developer account.
CONFIG_DIR="$WORK/config-ca"
mkdir -p "$CONFIG_DIR"
# mktemp -d gives 0700; the container must be able to traverse into it.
chmod 711 "$WORK"

docker run -d --name "$CONFIG_CONTAINER" \
    -p "$CONFIG_PORT:9000" \
    -v "$CONFIG_DIR:/home/step" \
    -e "DOCKER_STEPCA_INIT_NAME=Integration Config CA" \
    -e "DOCKER_STEPCA_INIT_DNS_NAMES=localhost,127.0.0.1" \
    -e "DOCKER_STEPCA_INIT_PASSWORD=$CA_PASSWORD" \
    "$IMAGE" >/dev/null

appeared=false
for _ in $(seq 1 30); do
    if [ -f "$CONFIG_DIR/certs/root_ca.crt" ]; then
        appeared=true
        break
    fi
    sleep 1
done
if [ "$appeared" != true ]; then
    docker logs "$CONFIG_CONTAINER" 2>&1 | tail -20 >&2
    die "config CA never generated its PKI into the bind mount"
fi

CONFIG_URL="https://localhost:$CONFIG_PORT"
wait_for_ca "$CONFIG_URL" "$CONFIG_DIR/certs/root_ca.crt" "config CA" "$CONFIG_CONTAINER"

###############################################################################
log "Admin mode"
###############################################################################
STEP_TEST_ADMIN_DIR="$ADMIN_DIR" \
STEP_TEST_ADMIN_URL="$ADMIN_URL" \
    ansible-playbook "$REPO_ROOT/tests/integration/admin_mode.yml"

###############################################################################
log "Config mode"
###############################################################################
STEP_TEST_CONFIG_DIR="$CONFIG_DIR" \
STEP_TEST_CONFIG_URL="$CONFIG_URL" \
STEP_TEST_CONFIG_CONTAINER="$CONFIG_CONTAINER" \
    ansible-playbook "$REPO_ROOT/tests/integration/config_mode.yml"
