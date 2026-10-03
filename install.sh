#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# nxXtend Installer
# ============================================================

# -------------------------
# Configuration
# -------------------------

REPO_URL="https://github.com/9-pixels/nxXtend.git"
REPO_API="https://api.github.com/repos/9-pixels/nxXtend/releases/latest"

INSTALL_ROOT="${HOME}/.local/share/nxXtend"
VENV_DIR="${INSTALL_ROOT}/venv"
BIN_DIR="${HOME}/.local/bin"
NX_BIN="${BIN_DIR}/nx"

BACKUP_DIR="${HOME}/.local/share/nxXtend-backup"

MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11

LATEST_RELEASE=""
INSTALLED_VERSION=""
INSTALL_STATE=""

# -------------------------
# Colors
# -------------------------

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    C_RED='\033[0;31m'
    C_GREEN='\033[0;32m'
    C_YELLOW='\033[0;33m'
    C_CYAN='\033[0;36m'
    C_MAGENTA='\033[0;35m'
    C_BOLD='\033[1m'
    C_DIM='\033[2m'
    C_NC='\033[0m'
else
    C_RED=''
    C_GREEN=''
    C_YELLOW=''
    C_CYAN=''
    C_MAGENTA=''
    C_BOLD=''
    C_DIM=''
    C_NC=''
fi

# -------------------------
# UI
# -------------------------

print_banner() {
    printf '%b\n' "${C_CYAN}"
    cat <<'EOF'
  ▐▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▌
  ▐                                                                   ▌
  ▐                           ██╗                                     ▌
  ▐   ███╗   ██╗██╗  ██╗██╗  ██╔╝███████╗███████╗███╗   ██╗██████╗    ▌
  ▐   ████╗  ██║╚██╗██╔╝╚██╗██╔╝╚══██╔══╝██╔════╝████╗  ██║██╔══██╗   ▌
  ▐   ██╔██╗ ██║ ╚███╔╝  ╚███╔╝    ██║   █████╗  ██╔██╗ ██║██║  ██║   ▌
  ▐   ██║╚██╗██║ ██╔██╗  ██╔██╗    ██║   ██╔══╝  ██║╚██╗██║██║  ██║   ▌
  ▐   ██║ ╚████║██╔╝ ██ ██╔╝ ██╗   ██║   ███████╗██║ ╚████║██████╔╝   ▌
  ▐   ╚═╝  ╚═══╝╚═╝    ██╔╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═══╝╚═════╝    ▌
  ▐                    ╚═╝                                            ▌
  ▐                                                                   ▌
  ▐▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▌
EOF
    printf '%b\n\n' "${C_NC}"
}

log() {
    printf '%b→%b %s\n' "${C_CYAN}" "${C_NC}" "$1"
}

success() {
    printf '%b✓%b %s\n' "${C_GREEN}" "${C_NC}" "$1"
}

warning() {
    printf '%b⚠%b %s\n' "${C_YELLOW}" "${C_NC}" "$1"
}

error() {
    printf '%b✗%b %s\n' "${C_RED}" "${C_NC}" "$1" >&2
}

info() {
    printf '%b  %s%b\n' "${C_DIM}" "$1" "${C_NC}"
}

die() {
    error "$1"
    exit 1
}

spinner() {
    local pid="$1"
    local message="$2"
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local i=0

    while kill -0 "$pid" 2>/dev/null; do
        printf '\r\033[K%b%s%b %s' \
            "${C_CYAN}" \
            "${frames[i]}" \
            "${C_NC}" \
            "$message"

        i=$(( (i + 1) % ${#frames[@]} ))
        sleep 0.08
    done

    printf '\r\033[K'
}

run_with_spinner() {
    local message="$1"
    shift

    "$@" >/tmp/nxXtend-installer-output.$$ 2>&1 &
    local pid=$!

    spinner "$pid" "$message"

    if ! wait "$pid"; then
        cat /tmp/nxXtend-installer-output.$$ >&2
        rm -f /tmp/nxXtend-installer-output.$$
        return 1
    fi

    rm -f /tmp/nxXtend-installer-output.$$
}

# -------------------------
# Cleanup / rollback
# -------------------------

cleanup_backup() {
    if [[ -e "$BACKUP_DIR" ]]; then
        rm -rf "$BACKUP_DIR"
    fi
}

rollback() {
    if [[ ! -e "$BACKUP_DIR" ]]; then
        return 0
    fi

    printf '\n'
    warning "Installation failed. Restoring previous installation..."

    rm -rf "$INSTALL_ROOT"

    if ! mv "$BACKUP_DIR" "$INSTALL_ROOT"; then
        error "Rollback failed."
        error "Previous installation is still available at: $BACKUP_DIR"
        return 1
    fi

    success "Previous installation restored."
}

on_error() {
    local exit_code=$?

    if [[ "$INSTALL_STATE" == "UPDATE" && -e "$BACKUP_DIR" ]]; then
        rollback || true
    fi

    exit "$exit_code"
}

trap on_error ERR

# -------------------------
# Prerequisites
# -------------------------

check_prerequisites() {
    log "Checking prerequisites"

    if ! command -v git >/dev/null 2>&1; then
        die "Git is required but was not found."
    fi

    success "Git found"

    if ! command -v python3 >/dev/null 2>&1; then
        die "Python 3 is required but was not found."
    fi

    success "Python 3 found"

    local python_version
    python_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

    local major="${python_version%%.*}"
    local minor="${python_version#*.}"

    if (( major < MIN_PYTHON_MAJOR )) ||
       (( major == MIN_PYTHON_MAJOR && minor < MIN_PYTHON_MINOR )); then
        die "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required. Found Python ${python_version}."
    fi

    success "Python ${python_version}"
}

# -------------------------
# Installation state
# -------------------------

prepare_installation() {
    mkdir -p "${HOME}/.local/share"
    mkdir -p "$BIN_DIR"
}

detect_installation() {
    if [[ ! -e "$INSTALL_ROOT" ]]; then
        INSTALL_STATE="FRESH"
        return 0
    fi

    if [[ ! -d "$INSTALL_ROOT" ]]; then
        INSTALL_STATE="BROKEN"
        return 0
    fi

    if ! git -C "$INSTALL_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        INSTALL_STATE="BROKEN"
        return 0
    fi

    local remote_url
    remote_url="$(git -C "$INSTALL_ROOT" remote get-url origin 2>/dev/null || true)"

    case "$remote_url" in
        https://github.com/9-pixels/nxXtend.git|\
        https://github.com/9-pixels/nxXtend|\
        git@github.com:9-pixels/nxXtend.git)
            INSTALL_STATE="UPDATE"
            ;;
        *)
            INSTALL_STATE="INVALID"
            ;;
    esac
}

get_installed_version() {
    INSTALLED_VERSION="$(
        git -C "$INSTALL_ROOT" describe \
            --tags \
            --exact-match \
            HEAD \
            2>/dev/null || true
    )"

    if [[ -z "$INSTALLED_VERSION" ]]; then
        INSTALLED_VERSION="unknown"
    fi
}

# -------------------------
# GitHub Release
# -------------------------

get_latest_release() {
    log "Checking latest release"

    LATEST_RELEASE="$(
        python3 - <<PY
import json
import urllib.request

url = "${REPO_API}"

request = urllib.request.Request(
    url,
    headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "nxXtend-installer",
    },
)

with urllib.request.urlopen(request, timeout=15) as response:
    data = json.load(response)

tag = data.get("tag_name")

if not tag:
    raise SystemExit("GitHub did not return a release tag.")

print(tag)
PY
    )"

    [[ -n "$LATEST_RELEASE" ]] || die "Could not determine the latest release."

    success "Latest release: ${LATEST_RELEASE}"
}

# -------------------------
# Version comparison
# -------------------------

normalize_version() {
    local version="$1"
    version="${version#v}"
    printf '%s\n' "$version"
}

compare_versions() {
    local left
    local right

    left="$(normalize_version "$1")"
    right="$(normalize_version "$2")"

    python3 - "$left" "$right" <<'PY'
import sys

def parse(value):
    parts = value.split(".")
    if len(parts) != 3:
        raise ValueError(f"Unsupported version: {value}")
    return tuple(int(part) for part in parts)

left = parse(sys.argv[1])
right = parse(sys.argv[2])

if left < right:
    print("-1")
elif left > right:
    print("1")
else:
    print("0")
PY
}

# -------------------------
# Backup
# -------------------------

create_backup() {
    log "Creating backup"

    cleanup_backup

    if ! cp -a "$INSTALL_ROOT" "$BACKUP_DIR"; then
        die "Could not create installation backup."
    fi

    success "Backup created"
}

# -------------------------
# Repository
# -------------------------

clone_repository() {
    log "Downloading ${LATEST_RELEASE}"

    rm -rf "$INSTALL_ROOT"

    if ! run_with_spinner \
        "Cloning release..." \
        git clone \
            --depth 1 \
            --branch "$LATEST_RELEASE" \
            "$REPO_URL" \
            "$INSTALL_ROOT"; then
        die "Could not download ${LATEST_RELEASE}."
    fi

    success "Release downloaded"
}

update_repository() {
    log "Updating repository"

    if ! git -C "$INSTALL_ROOT" fetch \
        --depth 1 \
        origin \
        "refs/tags/${LATEST_RELEASE}:refs/tags/${LATEST_RELEASE}"; then
        die "Could not download release ${LATEST_RELEASE}."
    fi

    if ! git -C "$INSTALL_ROOT" checkout --force "$LATEST_RELEASE"; then
        die "Could not switch to release ${LATEST_RELEASE}."
    fi

    success "Repository updated to ${LATEST_RELEASE}"
}

# -------------------------
# Python environment
# -------------------------

create_venv() {
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        success "Python environment already exists"
        return 0
    fi

    log "Creating Python environment"

    if ! run_with_spinner \
        "Creating virtual environment..." \
        python3 -m venv "$VENV_DIR"; then
        die "Could not create Python virtual environment."
    fi

    success "Python environment created"
}

install_nx() {
    log "Installing nxXtend"

    if ! run_with_spinner \
        "Installing package..." \
        "$VENV_DIR/bin/python" \
            -m pip install \
            --upgrade \
            "$INSTALL_ROOT"; then
        die "Could not install nxXtend."
    fi

    success "nxXtend installed"
}

# -------------------------
# Command publishing
# -------------------------

publish_command() {
    log "Publishing nx command"

    mkdir -p "$BIN_DIR"

    ln -sfn "${VENV_DIR}/bin/nx" "$NX_BIN"

    if [[ ! -x "$NX_BIN" ]]; then
        die "Could not publish nx command."
    fi

    success "nx available at ${NX_BIN}"

    if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
        warning "${BIN_DIR} is not in PATH."
        info "Add ${BIN_DIR} to PATH before using nx from a new shell."
    fi
}

# -------------------------
# Verification
# -------------------------

verify_installation() {
    log "Verifying installation"

    [[ -x "$NX_BIN" ]] || die "nx executable was not created."

    local actual_version
    actual_version="$("$NX_BIN" --version 2>/dev/null || true)"

    if [[ -z "$actual_version" ]]; then
        die "nx exists but could not be executed."
    fi

    success "nx executable verified"
    info "Version: ${actual_version}"

    if ! "$NX_BIN" --help >/dev/null 2>&1; then
        die "nx --help failed."
    fi

    success "nx --help verified"
}

# -------------------------
# Fresh installation
# -------------------------

fresh_install() {
    printf '\n'
    log "Installing nxXtend ${LATEST_RELEASE}"

    clone_repository
    create_venv
    install_nx
    publish_command
    verify_installation

    success "nxXtend ${LATEST_RELEASE} installed successfully."
}

# -------------------------
# Update
# -------------------------

update_installation() {
    get_installed_version

    printf '\n'
    info "Installed release: ${INSTALLED_VERSION}"
    info "Latest release:   ${LATEST_RELEASE}"
    printf '\n'

    if [[ "$INSTALLED_VERSION" == "$LATEST_RELEASE" ]]; then
        success "nxXtend is already up to date."
        verify_installation
        return 0
    fi

    create_backup
    update_repository
    create_venv
    install_nx
    publish_command
    verify_installation

    cleanup_backup

    success "nxXtend updated successfully."
}

# -------------------------
# Main
# -------------------------

main() {
    print_banner

    check_prerequisites
    prepare_installation
    detect_installation

    case "$INSTALL_STATE" in

        FRESH)
            get_latest_release
            fresh_install
            ;;

        UPDATE)
            get_latest_release
            update_installation
            ;;

        BROKEN)
            error "An existing installation path was found, but it is not a valid nxXtend installation."
            info "Path: ${INSTALL_ROOT}"
            info "Nothing was overwritten."
            exit 1
            ;;

        INVALID)
            error "The installation directory belongs to another repository."
            info "Path: ${INSTALL_ROOT}"
            info "Nothing was overwritten."
            exit 1
            ;;

        *)
            die "Unknown installation state: ${INSTALL_STATE}"
            ;;
    esac

    printf '\n'
    printf '%b%s%b\n' \
        "${C_GREEN}${C_BOLD}" \
        "nxXtend installation complete." \
        "${C_NC}"
}

if [[ "${BASH_SOURCE[0]:-}" == "$0" ]]; then
    main "$@"
fi