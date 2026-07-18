#!/usr/bin/env bash
# Shared Postgres tool + local port resolution for Accord dev scripts.
#
# Requires ACCORD_ROOT (repo root) before resolve/persist helpers run.
# Optional: declare info/warn/die (from scripts/lib/dev-ui.sh) for messaging.

if [[ -n "${ACCORD_POSTGRES_LOADED:-}" ]]; then
	return 0
fi
ACCORD_POSTGRES_LOADED=1

ACCORD_PG_DEFAULT_PORT=5432
ACCORD_PG_ALT_PORT=5433

find_postgres_tool() {
	local tool="$1" prefix formula
	if command -v "$tool" >/dev/null 2>&1; then
		command -v "$tool"
		return 0
	fi

	if command -v brew >/dev/null 2>&1; then
		for formula in postgresql@18 postgresql; do
			prefix="$(brew --prefix "$formula" 2>/dev/null || true)"
			if [[ -n "$prefix" && -x "$prefix/bin/$tool" ]]; then
				printf '%s\n' "$prefix/bin/$tool"
				return 0
			fi
		done
	fi

	return 1
}

_accord_pg_state_dir() {
	printf '%s\n' "${ACCORD_ROOT:?ACCORD_ROOT must be set}/.accord-dev"
}

_accord_pg_port_cache() {
	printf '%s\n' "$(_accord_pg_state_dir)/pg.port"
}

_accord_pg_isready_bin() {
	if [[ -n "${PG_ISREADY:-}" ]]; then
		printf '%s\n' "$PG_ISREADY"
		return 0
	fi
	find_postgres_tool pg_isready || true
}

pg_is_ready_on() {
	local port="$1"
	local host="${PGHOST:-127.0.0.1}"
	local bin
	bin="$(_accord_pg_isready_bin)"
	[[ -n "$bin" ]] || return 1
	"$bin" -h "$host" -p "$port" -q
}

read_cached_pg_port() {
	local cache port
	cache="$(_accord_pg_port_cache)"
	[[ -f "$cache" ]] || return 1
	port="$(tr -d '[:space:]' <"$cache" 2>/dev/null || true)"
	[[ "$port" =~ ^[0-9]+$ ]] || return 1
	printf '%s\n' "$port"
}

persist_pg_port() {
	local port="$1" state cache
	[[ "$port" =~ ^[0-9]+$ ]] || return 1
	state="$(_accord_pg_state_dir)"
	cache="$state/pg.port"
	mkdir -p "$state"
	printf '%s\n' "$port" >"$cache"
}

# Read configured port= from Homebrew postgresql data dirs (best-effort).
postgres_conf_ports() {
	local prefix formula conf port
	if ! command -v brew >/dev/null 2>&1; then
		return 0
	fi

	for formula in postgresql@18 postgresql; do
		prefix="$(brew --prefix "$formula" 2>/dev/null || true)"
		[[ -n "$prefix" ]] || continue
		# Homebrew stores the cluster under $(brew --prefix)/var/<formula>
		conf="$(brew --prefix 2>/dev/null)/var/$formula/postgresql.conf"
		if [[ ! -f "$conf" ]]; then
			conf="$prefix/var/postgresql.conf"
		fi
		[[ -f "$conf" ]] || continue
		port="$(sed -nE 's/^[[:space:]]*port[[:space:]]*=[[:space:]]*([0-9]+).*/\1/p' "$conf" | head -n1)"
		if [[ "$port" =~ ^[0-9]+$ ]]; then
			printf '%s\n' "$port"
		fi
	done
}

# Candidate ports: 5432, Homebrew conf port(s), 5433 (deduped, stable order).
pg_port_candidates() {
	local -a raw=("$ACCORD_PG_DEFAULT_PORT")
	local -a out=()
	local port conf_port seen

	while IFS= read -r conf_port; do
		[[ -n "$conf_port" ]] && raw+=("$conf_port")
	done < <(postgres_conf_ports)

	raw+=("$ACCORD_PG_ALT_PORT")

	for port in "${raw[@]}"; do
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

	printf '%s\n' "${out[@]}"
}

_accord_pg_candidates_csv() {
	local IFS=','
	# shellcheck disable=SC2046
	printf '%s\n' "$(pg_port_candidates | paste -sd, -)"
}

_accord_set_pg_port() {
	local port="$1"
	local persist="${2:-1}"
	export PGPORT="$port"
	if [[ "$persist" == "1" ]] && pg_is_ready_on "$port"; then
		persist_pg_port "$port"
	fi
}

# Resolve PGPORT for local scripts.
# - Explicit PGPORT (already set in the environment) always wins.
# - Else prefer a ready cached port, then the first ready candidate.
# - If nothing is ready: reuse cache when present, else default 5432 (not persisted).
# Sets ACCORD_PGPORT_EXPLICIT=1 when the caller supplied PGPORT.
resolve_pg_port() {
	local host="${PGHOST:-127.0.0.1}"
	local port cached

	if [[ -n "${PGPORT:-}" ]]; then
		ACCORD_PGPORT_EXPLICIT=1
		port="$PGPORT"
		export PGPORT
		if pg_is_ready_on "$port"; then
			persist_pg_port "$port"
			if declare -F info >/dev/null 2>&1; then
				info "Using PostgreSQL at $host:$port (PGPORT)"
			fi
		elif declare -F warn >/dev/null 2>&1; then
			warn "PGPORT=$port set but Postgres is not ready at $host:$port"
		fi
		return 0
	fi

	ACCORD_PGPORT_EXPLICIT=0

	if cached="$(read_cached_pg_port)" && pg_is_ready_on "$cached"; then
		_accord_set_pg_port "$cached" 1
		if declare -F info >/dev/null 2>&1; then
			info "Using PostgreSQL at $host:$cached (cached)"
		fi
		return 0
	fi

	while IFS= read -r port; do
		if pg_is_ready_on "$port"; then
			_accord_set_pg_port "$port" 1
			if declare -F info >/dev/null 2>&1; then
				info "Detected PostgreSQL at $host:$port"
			fi
			return 0
		fi
	done < <(pg_port_candidates)

	if cached="$(read_cached_pg_port)"; then
		export PGPORT="$cached"
		if declare -F warn >/dev/null 2>&1; then
			warn "Postgres not ready; using cached port $cached"
		fi
		return 0
	fi

	export PGPORT="$ACCORD_PG_DEFAULT_PORT"
	if declare -F warn >/dev/null 2>&1; then
		warn "Postgres not ready; defaulting to port $PGPORT (tried: $(_accord_pg_candidates_csv))"
	fi
}

# After starting Postgres, wait until a port is ready.
# Honors an explicit PGPORT; otherwise probes all candidates (incl. Homebrew conf).
wait_for_postgres_port() {
	local host="${PGHOST:-127.0.0.1}"
	local attempts="${1:-30}"
	local port
	local -a unique=()

	if [[ "${ACCORD_PGPORT_EXPLICIT:-0}" == "1" && -n "${PGPORT:-}" ]]; then
		unique=("$PGPORT")
	else
		local p seen
		while IFS= read -r port; do
			seen=0
			for existing in "${unique[@]+"${unique[@]}"}"; do
				if [[ "$existing" == "$port" ]]; then
					seen=1
					break
				fi
			done
			if (( !seen )); then
				unique+=("$port")
			fi
		done < <(pg_port_candidates)
	fi

	local _attempt
	for ((_attempt = 1; _attempt <= attempts; _attempt++)); do
		for port in "${unique[@]}"; do
			if pg_is_ready_on "$port"; then
				_accord_set_pg_port "$port" 1
				if declare -F info >/dev/null 2>&1; then
					info "PostgreSQL ready at $host:$port"
				fi
				return 0
			fi
		done
		sleep 0.5
	done

	local tried
	tried="$(IFS=','; echo "${unique[*]}")"
	if declare -F die >/dev/null 2>&1; then
		die "PostgreSQL did not become ready at $host (tried ports: $tried). Check brew services / postgresql.conf."
	fi
	echo "PostgreSQL did not become ready at $host (tried ports: $tried)" >&2
	return 1
}
