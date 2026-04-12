---
name: nia-fix
description: Query documentation sites via nia-docs when you need to look up docs for a library, cloud provider, or framework. Use proactively when the user says "ask nia", "check the docs", "look it up", or invokes /nia-fix.
---

# nia-fix

Use `npx nia-docs` to browse any documentation site as a virtual filesystem. You can `ls`, `grep`, `cat`, and pipe — standard bash.

Do not explain what you're about to do. Just run the commands.

## How to query docs

### 1. Index at the most specific URL you can

Top-level sites crawl shallowly. Subdirectories crawl deeply and give you the real content.

```bash
# Index the specific section you need
npx nia-docs https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ -c "ls"
# ✔ Indexed docs.aws.amazon.com (414 pages)
```

If you don't know the subdirectory, start at the top level and navigate down:

```bash
npx nia-docs https://docs.aws.amazon.com/ -c "ls | grep -i ecs"
# → AmazonECS

npx nia-docs https://docs.aws.amazon.com/ -c "ls AmazonECS/latest"
# → APIReference / developerguide
```

Then re-index at the subdirectory for full depth.

### 2. Find files

```bash
# Find files by name
npx nia-docs <url> -c "ls | grep -i <keyword>"

# Grep inside files
npx nia-docs <url> -c "grep -rl '<pattern>'"
```

### 3. Read content

```bash
# Full file
npx nia-docs <url> -c "cat getting-started.html"

# Control output size
npx nia-docs <url> -c "cat getting-started.html" 2>&1 | head -150
```

### 4. Cache

After the first run the site is cached — subsequent calls are instant. No need to re-index.

## Example: finding ECS Express Mode docs

```bash
# 1. Start at top level, find the ECS directory
npx nia-docs https://docs.aws.amazon.com/ -c "ls | grep -i ecs"
# → AmazonECS

# 2. Navigate down
npx nia-docs https://docs.aws.amazon.com/ -c "ls AmazonECS/latest"
# → APIReference / developerguide

# 3. Top-level crawl is shallow — only 2 files in the subdir
#    Re-index at the subdirectory for full depth (414 pages)
npx nia-docs https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ -c "ls | grep -i express"
# → express-service-getting-started.html
# → express-service-create-full.html
# → express-service-work.html
# → ... (10 files)

# 4. Read the guide
npx nia-docs https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ -c "cat express-service-getting-started.html"
```

## Common documentation URLs

| Service | URL |
|---------|-----|
| AWS ECS | `https://docs.aws.amazon.com/AmazonECS/latest/developerguide/` |
| AWS ECR | `https://docs.aws.amazon.com/AmazonECR/latest/userguide/` |
| AWS IAM | `https://docs.aws.amazon.com/IAM/latest/UserGuide/` |
| AWS App Runner | `https://docs.aws.amazon.com/apprunner/latest/dg/` |
| FastMCP | `https://gofastmcp.com/` |
| Vercel | `https://vercel.com/docs/` |
| Next.js | `https://nextjs.org/docs/` |
| Stripe | `https://docs.stripe.com/` |
| Claude Platform | `https://platform.claude.com/docs/` |

## Do not

- **Do not run nia-docs interactively** — always use `-c "<command>"`.
- **Do not skip the subdirectory step** — top-level URLs give you a shallow index (e.g., 2 files instead of 414). Always navigate to the specific docs section and re-index there.
- **Do not use `search` as a nia-docs command** — it doesn't exist. Use `ls`, `grep`, `cat`.
- **Do not forget `2>&1`** — pipe stderr too, otherwise you miss the loading/indexing output.
- **Do not forget timeout** — set `timeout: 120000` on Bash calls. First-time indexing can take 30-60s.
