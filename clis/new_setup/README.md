# newsetup

Scaffold projects from **templates**. A template bundles always-on root files
(`config/`) plus any number of optional **modules** (each its own folder), where
a module can run shell commands (e.g. `create-next-app`, `django-admin
startproject`) and/or drop in files.

```
newsetup list                                                    # show templates + their modules
newsetup new --path . --template default                         # all modules + config here
newsetup new --path myapp --template default --only frontend     # one module (+ config) into ./myapp
newsetup new --path myapp --template default --only frontend backend
newsetup new --path . --template default --bare                  # config root files only, no modules
newsetup new --path . --template default --bare --force          # overwrite existing root files (no prompt)
```

## Model

- **`--template`** is required — you always state what you're scaffolding. See
  `newsetup list` for available names.
- **`--path`** is required — no implicit current-directory default. Use `.` for
  here, a name for `./<name>`, or a full path. The folder is created if missing.
- **`config/`** = always-on. Everything in a template's `config/` folder is
  copied to the project **root** on every scaffold (e.g. `CLAUDE.md`). It is not
  a selectable module.
- **Modules** = every other folder in the template (and/or every section in
  `template.toml`). Drop a new folder like `infra/` into a template and it
  becomes a module automatically — it shows in `list` and is selectable with
  `--only infra`. No code change needed.
- **`--only A B`** builds exactly modules A and B; config still rides along.
  Omit `--only` to build all modules. `--only` and `--bare` are mutually
  exclusive.
- **`--bare`** builds config root files only (no modules).
- **Config conflicts.** If a root config file (e.g. `CLAUDE.md`) already exists,
  `newsetup` prompts per file: **[o]verride** (replace), **[m]erge** (keep the
  existing file, append a blank line, then the template's content), or
  **[s]kip** (leave it untouched). In a non-interactive shell it aborts instead
  of prompting — pass `--force` there.
- **`--force`** overwrites existing root config files without prompting. Module
  folders that already exist and are non-empty always abort (never clobbered).
- `git init` runs on every scaffold. If any command exits nonzero, `newsetup`
  stops.

### Requires on PATH

`git`, plus whatever a selected module's commands call — `npx` (Node) for
`frontend`, `django-admin` for `backend`. These run as subprocesses via your
system PATH; `newsetup` does not install them.

## Templates

```
new_setup/templates/<name>/
├── template.toml     # description + per-module { cwd, commands }
├── config/           # → copied to project ROOT (always)
│   └── CLAUDE.md
├── backend/          # module "backend": files overlaid into ./backend/
│   └── .gitignore
└── frontend/         # (optional) overlay files for ./frontend/
```

`template.toml`:

```toml
description = "Next.js frontend + Django backend"

[frontend]
cwd = "."                                              # run at root; the command makes ./frontend
commands = ["npx create-next-app@latest frontend --yes"]

[backend]
cwd = "backend"                                        # newsetup makes ./backend, runs the command inside
commands = ["django-admin startproject config ."]
```

- A module's `commands` run in `cwd` (relative to the project root; default
  `"."`). `newsetup` creates `cwd` first if it isn't `"."`.
- A module's folder contents (if any) are copied into `./<module>/` after its
  commands run.
- A module with no `template.toml` section is pure file-copy (no commands).

Templates ship inside the package and are read at runtime via the installed
package's own files — no dependency on this source folder's location.

**Add a template:** create a new folder under `new_setup/templates/`, then
reinstall.

## Install

Installed as a **uv tool** — uv builds it into an isolated environment and puts a
`newsetup` shim on your PATH (`~/.local/bin`). Snapshot install: code + templates
are copied into uv's data dir, so you can move/rename/delete this folder
afterward without breaking the command.

```sh
# from clis/new_setup/
uv tool install .
```

If `newsetup` isn't found, ensure uv's bin dir is on PATH:

```sh
uv tool update-shell   # then restart the shell
```

## Update

Snapshot install — edits here (code or templates) don't affect the installed
command until you reinstall:

```sh
# from clis/new_setup/, after editing
uv tool install --reinstall .
```

## Uninstall

```sh
uv tool uninstall newsetup
```
