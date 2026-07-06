#!/usr/bin/env bash
# Generic docker-compose container-wait/assert helpers. Scenario scripts set
# CARLA_DIR to the docker-compose project directory before calling these.

wait_for_one_shot_container() {
  local service="$1"
  local container_id=""
  local status=""

  cd "${CARLA_DIR}"
  for _ in {1..30}; do
    container_id="$(docker compose ps -a -q "${service}" 2>/dev/null || true)"
    if [[ -n "${container_id}" ]]; then
      break
    fi
    sleep 1
  done

  if [[ -z "${container_id}" ]]; then
    echo "Error: ${service} container was not created." >&2
    docker compose ps >&2 || true
    return 1
  fi

  echo "Waiting for ${service} to finish..."
  status="$(docker wait "${container_id}")"

  if [[ "${status}" != "0" ]]; then
    echo "Error: ${service} exited with status ${status}." >&2
    docker compose logs "${service}" >&2 || true
    return 1
  fi
}

assert_container_running() {
  local service="$1"
  local container_id=""
  local running=""
  local status=""
  local exit_code=""

  cd "${CARLA_DIR}"
  container_id="$(docker compose ps -q "${service}" 2>/dev/null || true)"
  if [[ -z "${container_id}" ]]; then
    echo "Error: ${service} container was not created." >&2
    docker compose ps >&2 || true
    return 1
  fi

  running="$(docker inspect -f '{{.State.Running}}' "${container_id}")"
  if [[ "${running}" == "true" ]]; then
    return 0
  fi

  status="$(docker inspect -f '{{.State.Status}}' "${container_id}")"
  exit_code="$(docker inspect -f '{{.State.ExitCode}}' "${container_id}")"
  echo "Error: ${service} container is not running: status=${status}, exit_code=${exit_code}" >&2
  docker compose logs --tail=120 "${service}" >&2 || true
  return 1
}

wait_for_container_stable() {
  local service="$1"
  echo "Checking ${service} stays alive..."
  for _ in {1..8}; do
    sleep 1
    assert_container_running "${service}"
  done
}
