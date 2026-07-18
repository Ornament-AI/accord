#!/usr/bin/env bash
# Shared TCP listen-port resolution for Accord local dev scripts.
#
# Requires ACCORD_ROOT (repo root). Optional: info/warn/die from dev-ui.sh.
#
# Frontend/backend ports are chosen from free candidates (or an explicit env
# override), then cached under .accord-dev/ so start/status/stop stay aligned.

if [[ -n "${ACCORD_PORTS_LOADED:-}" ]]; then
	return 0
fi
ACCORD_PORTS_LOADED=1

ACCORD_FRONTEND_DEFAULT_PORT=5173
ACCORD_BACKEND_DEFAULT_PORT=8000

_accord_ports_state_dir() {
	printf '%s\n' "${ACCORD_ROOT:?ACCORD_ROOT must be set}/.accord-dev"
}

_accord_port_cache_path() {
	local name="$1"
	printf '%s\n' "$(_accord_ports_state_dir)/$name.port"
}

port_is_listening() {
	local port="$1"
	command -v lsof >/dev/null 2>&1 || return 1
	lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

read_cached_port() {
	local name="$1" cache port
	cache="$(_accord_port_cache_path "$name")"
	[[ -f "$cache" ]] || return 1
	port="$(tr -d '[:space:]' <"$cache" 2>/dev/null || true)"
	[[ "$port" =~ ^[0-9]+$ ]] || return 1
	printf '%s\n' "$port"
}

persist_port() {
	local name="$1" port="$2" state cache
	[[ "$port" =~ ^[0-9]+$ ]] || return 1
	state="$(_accord_ports_state_dir)"
	cache="$state/$name.port"
	mkdir -p "$state"
	printf '%s\n' "$port" >"$cache"
}

# True when a pidfile process is still alive and the port is listening
# (Vite/uvicorn may listen from a child of the recorded pid).
port_matches_pidfile() {
	local port="$1" pidfile="$2" pid
	[[ -f "$pidfile" ]] || return 1
	pid="$(tr -d '[:space:]' <"$pidfile" 2>/dev/null || true)"
	[[ -n "$pid" ]] || return 1
	kill -0 "$pid" 2>/dev/null || return 1
	port_is_listening "$port"
}

_accord_dedupe_ports() {
	local -a out=()
	local port seen existing
	for port in "$@"; do
		[[ "$port" =~ ^[0-9]+$ ]] || continue
		seen=0
		for existing in "${out[@]+"${out[@]}"}"; do
			if [[ "$existing" == "$port" ]]; then
				seen=1
				break
			fi
		done
		if (( !seen )); then
			out+=("$port")
		fi
	done
	printf '%s\n' "${out[@]+"${out[@]}"}"
}

find_free_port() {
	local port
	while IFS= read -r port; do
		[[ -n "$port" ]] || continue
		if ! port_is_listening "$port"; then
			printf '%s\n' "$port"
			return 0
		fi
	done
	return 1
}

# resolve_app_port <env_var_name> <cache_name> <default> [extra candidates...]
# Exports the env var (e.g. FRONTEND_PORT) and persists when a free/owned port
# is selected. Explicit env values always win.
resolve_app_port() {
	local env_name="$1"
	local cache_name="$2"
	local default_port="$3"
	shift 3
	local -a extras=("$@")
	local host="127.0.0.1"
	local current cached port pidfile
	local -a candidates=()

	pidfile="$(_accord_ports_state_dir)/${cache_name}.pid"
	# bash indirect expansion for caller-supplied env var name
	current="${!env_name-}"

	if [[ -n "$current" ]]; then
		printf -v "$env_name" '%s' "$current"
		export "$env_name"
		persist_port "$cache_name" "$current"
		if port_is_listening "$current"; then
			if declare -F info >/dev/null 2>&1; then
				info "Using $env_name=$current (explicit; already listening)"
			fi
		elif declare -F info >/dev/null 2>&1; then
			info "Using $env_name=$current (explicit)"
		fi
		return 0
	fi

	candidates=("$default_port" "${extras[@]+"${extras[@]}"}")
	if cached="$(read_cached_port "$cache_name")"; then
		# Prefer a healthy prior Accord bind, else a still-free cached port.
		if port_matches_pidfile "$cached" "$pidfile" || ! port_is_listening "$cached"; then
			printf -v "$env_name" '%s' "$cached"
			export "$env_name"
			persist_port "$cache_name" "$cached"
			if declare -F info >/dev/null 2>&1; then
				info "Using $env_name=$cached (cached)"
			fi
			return 0
		fi
		# Cached port taken by something else (e.g. Atlas) — fall through.
		if declare -F warn >/dev/null 2>&1; then
			warn "Cached $cache_name port $cached is in use; picking another"
		fi
	fi

	if port="$( _accord_dedupe_ports "${candidates[@]}" | find_free_port )"; then
		printf -v "$env_name" '%s' "$port"
		export "$env_name"
		persist_port "$cache_name" "$port"
		if [[ "$port" == "$default_port" ]]; then
			if declare -F info >/dev/null 2>&1; then
				info "Using $env_name=$port"
			fi
		elif declare -F info >/dev/null 2>&1; then
			info "Using $env_name=$port ($default_port busy)"
		fi
		return 0
	fi

	if declare -F die >/dev/null 2>&1; then
		die "No free port for $env_name (tried: $(_accord_dedupe_ports "${candidates[@]}" | paste -sd, -))"
	fi
	echo "No free port for $env_name" >&2
	return 1
}

resolve_frontend_port() {
	resolve_app_port FRONTEND_PORT frontend "$ACCORD_FRONTEND_DEFAULT_PORT" \
		5174 5175 5176 5177 5178 5179 5180 5181 5182 5183
}

resolve_backend_port() {
	resolve_app_port BACKEND_PORT backend "$ACCORD_BACKEND_DEFAULT_PORT" \
		8002 8003 8004 8005 8006 8007 8008 8080 8800
}

# load_app_port <env_var_name> <cache_name> <default>
# For status/stop: honor explicit env or cache without allocating a new free port.
load_app_port() {
	local env_name="$1"
	local cache_name="$2"
	local default_port="$3"
	local current cached

	current="${!env_name-}"
	if [[ -n "$current" ]]; then
		printf -v "$env_name" '%s' "$current"
		export "$env_name"
		return 0
	fi

	if cached="$(read_cached_port "$cache_name")"; then
		printf -v "$env_name" '%s' "$cached"
		export "$env_name"
		return 0
	fi

	printf -v "$env_name" '%s' "$default_port"
	export "$env_name"
}

load_frontend_port() {
	load_app_port FRONTEND_PORT frontend "$ACCORD_FRONTEND_DEFAULT_PORT"
}

load_backend_port() {
	load_app_port BACKEND_PORT backend "$ACCORD_BACKEND_DEFAULT_PORT"
}
