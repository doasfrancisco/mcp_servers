---
name: vercel
description: Deploy projects and manage domains on Vercel from the CLI. Leads with the clean one-shot flow (create project, set framework, link folder, connect GitHub, attach domains, deploy) and keeps a full troubleshooting section for when things go wrong. Use when the user asks to deploy to Vercel, manage a Vercel project, connect a GitHub repo, or add/remove/detach a Vercel domain, or invokes /vercel.
---

# vercel

Two responsibilities: **deploying a project** and **managing its domains**. This skill leads with the clean one-shot flow. If that flow works, you're done. If anything misbehaves, jump to the "When things go wrong" section — it has every diagnostic step we've verified.

## 0. Verify the right account first

Before anything, confirm the CLI is pointed at the account the user actually means. A wrong-account login is the most common reason commands return "0 domains" or "project not found".

```bash
vercel whoami              # prints current user/team slug
vercel domains ls          # should match the dashboard
```

If the list is empty but the dashboard shows domains, the CLI is on a stale/different account. Fix:

```bash
vercel logout
vercel login               # interactive device flow — do NOT pass email as arg (deprecated)
```

Compare the slug in `vercel domains ls` output against the URL in the dashboard (`vercel.com/<slug>/...`). Slug mismatches with similar names (e.g. `pedro-domnguezs-projects` vs `pedro-dominguezs-projects`) mean you're logged into the wrong account.

---

# Part A — Deploying a project (the clean flow)

## A1. Simplest case: folder name can be the project name

If you don't need a specific project name, the full flow is:

```bash
cd /path/to/project
vercel --prod --yes                                 # auto-link, auto-detect framework, deploy
echo y | vercel git connect <github-repo-url>       # connect GitHub for auto-deploys on push
vercel domains add example.com                      # attach apex
vercel domains add www.example.com                  # attach www
vercel --prod --yes --force                         # rebind aliases on a new production deploy
```

On the first `vercel --prod`, Vercel auto-links, auto-detects the framework from `package.json`, creates the project with the framework already set, and deploys. The project's name defaults to the folder basename. The linked state is stored in `.vercel/project.json`.

`vercel git connect` is interactive and prompts for confirmation when a local git remote exists — pipe `y` into it to answer non-interactively.

Verify with `curl -skI "https://example.com?_=$(date +%s)" | head -5` — expect `HTTP 200`.

## A2. Custom project name: the one-shot flow

When the project name must differ from the folder basename, do the steps **in this order**:

```bash
# 1. Create empty project (framework is null at this point — that's fine as long as you fix it next)
vercel project add <name>

# 2. Set framework BEFORE the first deploy. This is the load-bearing step.
#    Replace "nextjs" with the real framework slug: sveltekit, remix, astro, vite, etc.
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<name> -X PATCH -f framework=nextjs

# 3. Link the local folder to the named project
cd /path/to/project
vercel link --yes --project <name>

# 4. Connect the GitHub repo so pushes to the production branch auto-deploy.
#    Pipe y to answer the "use local git remote?" confirmation non-interactively.
echo y | vercel git connect <github-repo-url>

# 5. Attach the domains BEFORE the first deploy. They auto-bind when the first deploy runs.
vercel domains add example.com
vercel domains add www.example.com

# 6. Deploy once. Framework is set, GitHub is connected, domains are pre-attached, aliases bind automatically.
vercel --prod --yes
```

**One deploy, not three.** The order matters: project → framework → link → git → domains → deploy. Every out-of-order variant of this sequence introduces a failure mode covered in the troubleshooting section below.

Verify the git link stuck with:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<name> --raw > /tmp/p.json
python -c "import json; d=json.load(open('/tmp/p.json')); print('link:', d.get('link'))"
```

The `link` field should be an object with `type: github`, `repo`, `org`, and `productionBranch`. If it's `None`, the connection didn't stick — see C12 below.

## A3. Always verify the deploy

A CLI "Ready" status and `aliasAssigned: true` in the API are **not** proof the deployment serves content. Always end with a curl against the intended public URL:

```bash
curl -skI "https://example.com?_=$(date +%s)" | head -5
```

Interpret the status code:

- **`HTTP 200`** → working. Done.
- **`HTTP 401` with `set-cookie: _vercel_sso_nonce`** → the URL is SSO-protected. Expected on `<project>-<hash>.vercel.app` canonical URLs when the project has Deployment Protection set to `all_except_custom_domains`. Test the custom domain instead.
- **`HTTP 404` with `x-vercel-error: NOT_FOUND`** → jump to "When things go wrong" below.

## A4. Project linking reference

`.vercel/project.json` tracks which Vercel project the local folder belongs to. Created by `vercel link`. Added to `.gitignore` automatically.

- Single project / single repo: `vercel link --yes` (picks or creates a project by folder name) or `vercel link --yes --project <name>` (must already exist — use `vercel project add` first).
- Monorepo with multiple deployable apps: `vercel link --repo` (creates `.vercel/repo.json`, tracks multiple projects from one root).

When a linked command misbehaves, check `.vercel/project.json` first — a wrong `projectId` is a common cause of "deploying to the wrong place" bugs.

---

# Part B — Domain management (the clean flow)

Two distinct operations that are easy to confuse:

- **Unlink** — detach a domain from a project but keep it in the account. Used when repointing a domain to a different project.
- **Remove** — delete the domain from the team account entirely. Used when giving up ownership.

## B1. List and inspect

```bash
vercel domains ls                      # all domains in the current scope
vercel domains inspect example.com     # project attachments, registrar, nameservers
```

**Warning:** `vercel domains inspect` output can be stale after a mutation — it may still show a domain attached to a project several minutes after detaching. Do not use it to verify a write. Use the authoritative check in B4 instead.

## B2. Attach a domain to a project

From a folder that is already `vercel link`-ed to the target project:

```bash
vercel domains add example.com          # uses the linked project automatically
vercel domains add www.example.com      # same, for the www variant
```

Attach the apex and `www` separately — `vercel domains add` does not cascade.

**Critical:** if the project already has a production deployment, attaching a domain does NOT auto-alias it. You must trigger a new production deploy afterward:

```bash
vercel --prod --yes --force
```

(If you follow the A2 flow and attach domains *before* the first deploy, this step is automatic.)

If the domain was previously attached to a different project, use `--force` on the add to clear the old attachment:

```bash
vercel domains add example.com <project> --force
```

After the redeploy, verify with `curl -skI` per A3.

## B3. Unlink a domain from a project (keep domain)

There is no `vercel project domain rm` command. Use the REST API via `vercel api`:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<project>/domains/<domain> \
  -X DELETE --dangerously-skip-permissions
```

Three gotchas, all required on Windows/git-bash:

1. **`MSYS_NO_PATHCONV=1`** — without it, git-bash rewrites the leading `/` of the endpoint into a Windows path and you get `Error: Endpoint must start with /`.
2. **`--dangerously-skip-permissions`** — the `vercel api` command blocks non-interactive DELETE requests by default. Agents must pass this flag.
3. **Both apex and `www`** — if the project has `example.com` and `www.example.com`, detach each separately. Listing the apex does not cascade.

A successful DELETE returns `{}`. An empty JSON object means success, not a silent failure.

## B4. Verify the unlink worked

`vercel domains inspect` is cached — do not trust it. Query the project's domain list directly:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<project>/domains
```

The unlinked domain should be gone from the `domains[]` array. Only the auto-assigned `<project>.vercel.app` should remain if no other domains are attached.

Alternative verification: re-run the DELETE. If it returns `Error: The domain "<domain>" is not assigned to "<project>". (404)`, the unlink was successful.

## B5. Fully remove a domain from the account

This is destructive — the team loses ownership. Confirm with the user before running.

```bash
vercel domains rm example.com --yes
```

All project attachments are cleared automatically. Cannot be undone from the CLI (the domain returns to the registrar).

---

# Part C — When things go wrong

Jump here whenever A3's curl returns something other than `HTTP 200` on a custom domain, or any other sequence breaks. Run the checks in order — each one narrows the next.

## C1. 404 NOT_FOUND on a custom domain: the `framework: null` trap

**Symptom**: deployment is `READY`, CLI reports aliases assigned, `vercel api /v9/projects/<name>/domains` lists the domain, DNS resolves to a Vercel IP, but curling the custom domain returns `HTTP 404 x-vercel-error: NOT_FOUND`. The canonical `.vercel.app` URL returns `HTTP 401` (SSO wall) while custom domains return `HTTP 404`.

**Cause**: `vercel project add <name>` creates an empty project with `framework: null`. Subsequent `vercel --prod` deploys build successfully but the project-level framework setting is never updated from `null` to `nextjs` (or whatever). At runtime, Vercel's edge doesn't know how to map `/` to the build output and returns `NOT_FOUND` on every non-SSO-protected URL, including custom domains. The build logs look perfect. `vercel alias set` reports success. The deployment shows `readyState: READY`, `aliasAssigned: true`, and the alias list contains the custom domain. Still 404.

**Diagnosis** — run this first, before anything else:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<name> --raw > /tmp/p.json
python -c "import json; d=json.load(open('/tmp/p.json')); print('framework:', d.get('framework'))"
```

If `framework: None`, you hit this bug.

**Fix**:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<name> -X PATCH -f framework=nextjs
vercel --prod --yes --force
```

Watch the deploy output — on success it will log `Aliased: https://example.com` (the custom domain, not just the `.vercel.app` canonical). Then curl again to confirm `HTTP 200`.

## C2. 404 NOT_FOUND with framework already set

If `framework` is correct and you're still getting 404, walk through in this order:

1. **Alias actually assigned to THIS deployment.**

   ```bash
   MSYS_NO_PATHCONV=1 vercel api /v13/deployments/<deployment-id> --raw > /tmp/d.json
   python -c "import json; d=json.load(open('/tmp/d.json')); print('readyState:', d.get('readyState')); print('aliasAssigned:', d.get('aliasAssigned')); print('aliasError:', d.get('aliasError')); print('alias:', d.get('alias'))"
   ```

   `readyState` must be `READY`. `aliasAssigned` must be `True`. The custom domain must be in the `alias` list. If not, force a new production deploy with `vercel --prod --yes --force`.

2. **Domain not silently attached to another project.**

   ```bash
   MSYS_NO_PATHCONV=1 vercel api /v9/projects/<other-project>/domains
   ```

   Check every project you suspect. If the domain still appears on another project, unlink per B3. Then `vercel domains add example.com --force` from the correct linked folder.

3. **Team/account mismatch.** The domain's `teamId` must match the project's `accountId`. Pull both:

   ```bash
   MSYS_NO_PATHCONV=1 vercel api /v4/domains/example.com --raw > /tmp/dom.json
   MSYS_NO_PATHCONV=1 vercel api /v9/projects/<name> --raw > /tmp/p.json
   python -c "
   import json
   dom = json.load(open('/tmp/dom.json'))['domain']
   proj = json.load(open('/tmp/p.json'))
   print('domain teamId:', dom.get('teamId'))
   print('project accountId:', proj.get('accountId'))
   "
   ```

   If they differ, the domain lives on a different team than the project. Vercel's edge returns `NOT_FOUND` rather than `403` for security. Move the domain with `vercel domains move example.com <destination-team>` or deploy under the domain's team.

4. **Edge cache propagation.** Rare but real — up to 2 minutes after an alias change. If everything else checks out, wait 2 minutes and retry.

## C3. `vercel api` fails with "Endpoint must start with /"

Git-bash / MSYS rewrote the leading `/` into a Windows path. Prefix the command with `MSYS_NO_PATHCONV=1`:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<name>
```

This applies to every `vercel api` call on Windows/git-bash, not just DELETE requests.

## C4. `vercel api` DELETE fails with "DELETE operations require confirmation"

Pass `--dangerously-skip-permissions`:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<name>/domains/<domain> \
  -X DELETE --dangerously-skip-permissions
```

This is required in non-interactive mode for any DELETE via `vercel api`.

## C5. `vercel domains add <domain> <project>` fails when a project is linked

Error message: `Linked project is "<name>". Run: vercel domains add <domain>`.

`vercel domains add` ignores the `<project>` positional when a `.vercel/project.json` is present — it always targets the linked project. Either:
- Drop the project arg: `vercel domains add example.com`
- Or run from a folder that isn't linked, and pass the project arg.

## C6. `vercel domains rm` removes the domain from the account, not from a project

`vercel domains rm` is for giving up ownership entirely. To detach a domain from a project while keeping it in your account, use B3 (`vercel api ... -X DELETE`) — not `vercel domains rm`.

## C7. `vercel login <email>` prints a deprecation warning

The positional email argument is deprecated. Use the interactive device flow:

```bash
vercel logout
vercel login       # then follow the device code prompt
```

## C8. "0 domains" or "0 projects" when the dashboard shows many

The CLI is logged into a different account. This commonly happens when two Vercel accounts share a display name but have distinct slugs (e.g. `pedro-domnguezs-projects` vs `pedro-dominguezs-projects`). Fix per step 0.

## C9. `vercel domains inspect` shows a domain as still attached after you detached it

`vercel domains inspect` is cached on the server side for several minutes after mutations. It is not authoritative for verification. Use the project domains endpoint per B4 instead:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<project>/domains
```

## C10. Deployment canonical URL returns 401 with `_vercel_sso_nonce` cookie

The project has Deployment Protection enabled. If it's set to `all_except_custom_domains`, this is expected — custom domains bypass the wall. Only worry if the custom domain also returns 401. To check the project's protection setting:

```bash
python -c "import json; d=json.load(open('/tmp/p.json')); print('ssoProtection:', d.get('ssoProtection'))"
```

## C11. `vercel curl` fails with "URL using bad/illegal format"

`vercel curl` expects a path argument as the first positional: `vercel curl /api/health`. The path must start with `/`. For flags, use the `--` separator: `vercel curl /api/health -- -sSI`. It generates a protection bypass token automatically on the first call.

## C12. `vercel git connect` hangs or doesn't persist

Two failure modes:

**a) Hangs waiting for input.** When the local repo has a remote configured, `vercel git connect` prompts `Do you still want to connect <url>? (y/N)`. Piping `yes |` floods stdin and can hang the TUI — use a single `echo y |` instead:

```bash
echo y | vercel git connect https://github.com/<org>/<repo>
```

**b) Reports "Connected" but the API shows `link: null`.** Re-run the command — the first attempt sometimes fails silently on Windows when the project was just created by `vercel project add`. Re-verify with:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<name> --raw > /tmp/p.json
python -c "import json; d=json.load(open('/tmp/p.json')); print('link:', d.get('link'))"
```

If the second attempt still won't persist, set it via the API:

```bash
MSYS_NO_PATHCONV=1 vercel api /v9/projects/<name>/link -X POST \
  -f type=github -f repo=<org>/<repo>
```

---

## Rules

- Always run step 0 (account check) before any mutation.
- For a new project with a custom name, **always PATCH `framework` before the first deploy**. Don't skip this, even if it looks redundant.
- Always end a deploy with a `curl -skI` against the intended public URL. A CLI "Ready" status is not verification.
- When diagnosing a 404 on a Vercel domain, check `framework` on the project **first** — it's the single most common cause and takes one command to rule out.
- Never confuse unlink (`vercel api ... -X DELETE`) with remove (`vercel domains rm`). Ask the user which they want if unclear.
- Never trust `vercel domains inspect` to verify a write — use B4.
- Never pass the user's email to `vercel login` as an argument; it's deprecated. Use the interactive device flow.
- Before `vercel domains rm`, confirm out loud with the user.
- On Windows/git-bash, prefix every `vercel api` call with `MSYS_NO_PATHCONV=1`.
- For `vercel api` DELETE in non-interactive mode, always pass `--dangerously-skip-permissions`.
