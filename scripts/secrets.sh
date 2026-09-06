#!/usr/bin/env bash
# Общий file-based store для основного Bearer Token.

SECRET_DIR="$ROOT_DIR/secrets"
ACCESS_TOKEN_FILE="$SECRET_DIR/rtkey_access_token"

normalize_access_token() {
    local token="$1"
    token="$(printf '%s' "$token" | tr -d '\r\n')"
    if [[ "${token,,}" == bearer\ * ]]; then
        token="${token:7}"
    fi
    [[ "$token" =~ ^[A-Za-z0-9._~-]+$ ]] || return 1
    printf '%s' "$token"
}

read_access_token_secret() {
    [[ -r "$ACCESS_TOKEN_FILE" ]] || return 0
    cat -- "$ACCESS_TOKEN_FILE"
}

write_access_token_secret() (
    set -Eeuo pipefail
    local token="$1"
    local tmp=""

    umask 077
    mkdir -p -- "$SECRET_DIR"
    chmod 0700 "$SECRET_DIR"
    tmp="$(mktemp "$SECRET_DIR/.rtkey_access_token.XXXXXX")"
    trap 'rm -f -- "$tmp"' EXIT
    printf '%s' "$token" > "$tmp"

    # Local Docker Compose bind-mounts file secrets and cannot remap uid/gid.
    # The parent directory is private on the host; 0444 lets UID 10001 read the
    # single file after Docker mounts it at /run/secrets inside the container.
    chmod 0444 "$tmp"
    mv -f -- "$tmp" "$ACCESS_TOKEN_FILE"
    trap - EXIT
)
