#!/usr/bin/env bash
# Source this helper; the calling launcher owns EXIT/INT/TERM traps.

UB_IAP_CONTROL_DIR=""

ub_iap_cleanup() {
  if [[ -n "${UB_IAP_CONTROL_DIR}" ]]; then
    ssh -S "${UB_IAP_CONTROL_DIR}/ssh" -O exit "${UB_IAP_INSTANCE:-carla}" >/dev/null 2>&1 || true
    rm -rf -- "${UB_IAP_CONTROL_DIR}"
    UB_IAP_CONTROL_DIR=""
  fi
}

ub_iap_preview() {
  local mode="${1:-redis}"
  local redis_port="${2:-${UB_IAP_LOCAL_REDIS_PORT:-16390}}"
  echo "IAP tunnel: ${UB_IAP_INSTANCE:-carla} (${UB_IAP_PROJECT:-buf-prj-digitaltwin-svxz}, ${UB_IAP_ZONE:-us-central1-a})"
  echo "  Redis: 127.0.0.1:${redis_port} -> ${UB_IAP_REDIS_HOST:-127.0.0.1}:${UB_IAP_REDIS_PORT:-6390}"
  if [[ "${mode}" == manual ]]; then
    echo "  CARLA RPC: 127.0.0.1:${3:-12000} -> ${UB_IAP_CARLA_HOST:-127.0.0.1}:${UB_IAP_CARLA_PORT:-2000}"
    echo "  CARLA streaming: 127.0.0.1:${UB_IAP_CARLA_STREAMING_PORT:-2001} -> ${UB_IAP_CARLA_HOST:-127.0.0.1}:${UB_IAP_CARLA_STREAMING_PORT:-2001}"
  fi
}

ub_iap_start() {
  local mode="${1:-redis}"
  local redis_port="${2:-${UB_IAP_LOCAL_REDIS_PORT:-16390}}"
  local rpc_port="${3:-12000}"
  local streaming_port="${UB_IAP_CARLA_STREAMING_PORT:-2001}"
  local dependency
  if [[ "${mode}" != redis && "${mode}" != manual ]]; then
    echo "Error: unsupported IAP tunnel mode: ${mode}" >&2
    return 2
  fi
  for dependency in gcloud ssh; do
    if ! command -v "${dependency}" >/dev/null 2>&1; then
      echo "Error: ${dependency} is required for --iap mode." >&2
      return 1
    fi
  done

  UB_IAP_CONTROL_DIR="$(mktemp -d /tmp/ub-carla-iap.XXXXXX)"
  local forwards=(-L "127.0.0.1:${redis_port}:${UB_IAP_REDIS_HOST:-127.0.0.1}:${UB_IAP_REDIS_PORT:-6390}")
  if [[ "${mode}" == manual ]]; then
    # The world-state stream uses the port advertised by CARLA, independently
    # of any RPC port remapping. Keep the local streaming port unchanged.
    forwards+=(
      -L "127.0.0.1:${rpc_port}:${UB_IAP_CARLA_HOST:-127.0.0.1}:${UB_IAP_CARLA_PORT:-2000}"
      -L "127.0.0.1:${streaming_port}:${UB_IAP_CARLA_HOST:-127.0.0.1}:${streaming_port}"
    )
  fi

  ub_iap_preview "${mode}" "${redis_port}" "${rpc_port}"
  # -f waits for authentication and local port binding before returning. The
  # private control socket lets cleanup close only this launcher's tunnel.
  gcloud compute ssh "${UB_IAP_INSTANCE:-carla}" \
    --project="${UB_IAP_PROJECT:-buf-prj-digitaltwin-svxz}" \
    --zone="${UB_IAP_ZONE:-us-central1-a}" \
    --tunnel-through-iap \
    -- -f -N -M -S "${UB_IAP_CONTROL_DIR}/ssh" \
    -o ControlPersist=no \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    "${forwards[@]}"

  if ! ssh -S "${UB_IAP_CONTROL_DIR}/ssh" -O check "${UB_IAP_INSTANCE:-carla}" >/dev/null 2>&1; then
    echo "Error: IAP tunnel did not become ready; client was not started." >&2
    return 1
  fi
}
