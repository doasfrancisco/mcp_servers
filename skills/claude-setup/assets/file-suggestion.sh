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

      # 3. If sub-repo is a meta-repo, index its sub-repos too
      [ -f "$dir/.meta-repo" ] || continue
      git -C "$dir" ls-files --others --ignored --exclude-standard 2>/dev/null | while read -r subdir; do
        subdir="${subdir%/}"
        [ -d "$dir/$subdir/.git" ] || continue
        git -C "$dir/$subdir" ls-files 2>/dev/null | sed "s|^|$dir/$subdir/|"
      done
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

# Build fuzzy patterns
# Segment fuzzy: "perso" → "p[^/]*e[^/]*r[^/]*s[^/]*o" (within one path segment)
# Global fuzzy:  "v6" → "v.*6" (anywhere in path, crosses segments)
fuzzy=""
gfuzzy=""
for (( i=0; i<${#query}; i++ )); do
  c="${query:$i:1}"
  if [[ "$c" =~ [\.\^\$\*\+\?\\\{\}\(\)\|/\[\]] ]]; then
    c="\\$c"
  fi
  if [ $i -eq 0 ]; then
    fuzzy="$c"
    gfuzzy="$c"
  else
    fuzzy="${fuzzy}[^/]*$c"
    gfuzzy="${gfuzzy}.*$c"
  fi
done

# Sort helper: by depth, files before dirs at same depth
by_depth() { awk -F/ '{d=($0 ~ /\/$/) ? 1 : 0; print NF, d, $0}' | sort -n -k1 -k2 | cut -d' ' -f3-; }

# All searches use grep on pre-built cache files (fast, no loops)
# Tiers are searched in order; within each tier, shallowest paths win.
{
  # Tier 1: segment starts with query (exact prefix) — root dir first, then files, then dirs
  grep -iE "(^|/)$query[^/]*/$" "$CACHE_DIRS" 2>/dev/null | by_depth | head -1
  { grep -iE "(^|/)$query" "$CACHE_DIRS" 2>/dev/null
    grep -iE "(^|/)$query" "$CACHE_FILE" 2>/dev/null
  } | by_depth | head -10

  # Tier 2: fuzzy match on segment — dirs + files merged
  { grep -iE "(^|/)$fuzzy" "$CACHE_DIRS" 2>/dev/null
    grep -iE "(^|/)$fuzzy" "$CACHE_FILE" 2>/dev/null
  } | by_depth | head -10

  # Tier 3: substring anywhere (fallback)
  grep -i "$query" "$CACHE_FILE" 2>/dev/null | by_depth | head -8

  # Tier 4: global fuzzy (crosses segment boundaries, e.g. "v6" matches "alcance_v0_0_6.md")
  { grep -iE "$gfuzzy" "$CACHE_DIRS" 2>/dev/null
    grep -iE "$gfuzzy" "$CACHE_FILE" 2>/dev/null
  } | by_depth | head -8
} | awk '!seen[$0]++' | head -15
