#!/bin/bash
# Custom @ file picker for meta-repo with nested git repos.
# Uses git index for speed: tracked files + recurse into ignored sub-repos.
# Caches results; rebuilds every 60s in background.

PROJECT_HASH=$(pwd | md5sum | cut -d' ' -f1)
CACHE_DIR="${TMPDIR:-/tmp}/claude-file-suggestion-${PROJECT_HASH}"
CACHE_FILE="$CACHE_DIR/index.txt"
CACHE_DIRS="$CACHE_DIR/dirs.txt"
CACHE_LOCK="$CACHE_DIR/lock"
CACHE_TTL=60

mkdir -p "$CACHE_DIR"

build_index() {
  {
    # 1. Root repo tracked files
    git ls-files 2>/dev/null

    # 2. Find ignored sub-repos and list their tracked files
    git ls-files --others --ignored --exclude-standard 2>/dev/null | while read -r dir; do
      dir="${dir%/}"
      [ -d "$dir/.git" ] || continue
      git -C "$dir" ls-files 2>/dev/null | sed "s|^|$dir/|"
    done
  } | sort > "$CACHE_FILE.tmp"

  # Pre-compute unique directories
  grep '/' "$CACHE_FILE.tmp" | sed 's|/[^/]*$||' | sort -u | sed 's|$|/|' > "$CACHE_DIRS.tmp"
  mv "$CACHE_FILE.tmp" "$CACHE_FILE"
  mv "$CACHE_DIRS.tmp" "$CACHE_DIRS"
}

# Build cache if missing or stale
if [ ! -f "$CACHE_FILE" ]; then
  build_index
elif [ -f "$CACHE_FILE" ]; then
  age=$(( $(date +%s) - $(date -r "$CACHE_FILE" +%s 2>/dev/null || echo 0) ))
  if [ "$age" -gt "$CACHE_TTL" ] && ! [ -f "$CACHE_LOCK" ]; then
    touch "$CACHE_LOCK"
    ( build_index; rm -f "$CACHE_LOCK" ) &
  fi
fi

query=$(cat | jq -r '.query // ""')

if [ -z "$query" ]; then
  ls -1p | head -15
  exit 0
fi

# Build fuzzy pattern: "perso" → "p[^/]*e[^/]*r[^/]*s[^/]*o"
fuzzy=""
for (( i=0; i<${#query}; i++ )); do
  c="${query:$i:1}"
  # Escape regex special chars
  if [[ "$c" =~ [\.\^\$\*\+\?\\\{\}\(\)\|/\[\]] ]]; then
    c="\\$c"
  fi
  if [ $i -eq 0 ]; then
    fuzzy="$c"
  else
    fuzzy="${fuzzy}[^/]*$c"
  fi
done

# Sort helper: shorter paths first (shallower = more relevant)
by_depth() { awk -F/ '{print NF, $0}' | sort -n | cut -d' ' -f2-; }

# All searches use grep on pre-built cache files (fast, no loops)
# Tiers are searched in order; within each tier, shallowest paths win.
{
  # Tier 1: segment starts with query (exact prefix) — dirs + files merged
  { grep -iE "(^|/)$query" "$CACHE_DIRS" 2>/dev/null
    grep -iE "(^|/)$query" "$CACHE_FILE" 2>/dev/null
  } | by_depth | head -10

  # Tier 2: fuzzy match on segment — dirs + files merged
  { grep -iE "(^|/)$fuzzy" "$CACHE_DIRS" 2>/dev/null
    grep -iE "(^|/)$fuzzy" "$CACHE_FILE" 2>/dev/null
  } | by_depth | head -10

  # Tier 3: substring anywhere (fallback)
  grep -i "$query" "$CACHE_FILE" 2>/dev/null | by_depth | head -8
} | awk '!seen[$0]++' | head -15
