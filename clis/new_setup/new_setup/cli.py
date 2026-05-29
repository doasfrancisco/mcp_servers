import argparse
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


def templates_dir() -> Path:
    return Path(__file__).parent / "templates"


def fail(msg: str) -> None:
    print(f"[newsetup] error: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: str, cwd: Path) -> None:
    print(f"\n[newsetup] $ {cmd}  (in {cwd})")
    result = subprocess.run(cmd, cwd=str(cwd), shell=True)
    if result.returncode != 0:
        fail(f"command failed ({result.returncode}): {cmd}")


def load_manifest(template_dir: Path) -> dict:
    manifest = template_dir / "template.toml"
    if not manifest.exists():
        return {}
    return tomllib.loads(manifest.read_text(encoding="utf-8"))


def discover_modules(template_dir: Path, data: dict) -> list[str]:
    folders = {
        d.name
        for d in template_dir.iterdir()
        if d.is_dir() and d.name != "config"
    }
    declared = {k for k, v in data.items() if isinstance(v, dict)}
    return sorted(folders | declared)


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p


def cmd_list() -> None:
    root = templates_dir()
    found = False
    for tdir in sorted(p for p in root.iterdir() if p.is_dir()):
        data = load_manifest(tdir)
        desc = data.get("description", "")
        modules = discover_modules(tdir, data)
        found = True
        print(f"{tdir.name}" + (f" - {desc}" if desc else ""))
        print(f"  modules: {', '.join(modules) if modules else '(none)'}")
        print("  (config root files always applied; use --bare for config only)")
    if not found:
        print(f"[newsetup] no templates in {root}")


def cmd_new(args: argparse.Namespace) -> None:
    if args.only and args.bare:
        fail("--only and --bare are mutually exclusive.")

    template_dir = templates_dir() / args.template
    if not template_dir.is_dir():
        fail(f"unknown template '{args.template}'. run `newsetup list` to see options.")

    data = load_manifest(template_dir)
    modules = discover_modules(template_dir, data)

    if args.bare:
        selected: list[str] = []
    elif args.only:
        unknown = [m for m in args.only if m not in modules]
        if unknown:
            avail = ", ".join(modules) if modules else "(none)"
            fail(f"unknown module(s): {', '.join(unknown)}. available: {avail}")
        selected = list(dict.fromkeys(args.only))
    else:
        selected = modules

    target = Path(args.path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    config_dir = template_dir / "config"
    apply_config = config_dir.is_dir()

    for m in selected:
        d = target / m
        if d.exists() and any(d.iterdir()):
            fail(f"{d} already exists and is not empty. refusing to clobber.")
    if apply_config:
        for f in iter_files(config_dir):
            dest = target / f.relative_to(config_dir)
            if dest.exists() and not args.force:
                fail(f"{dest} already exists. use --force to overwrite.")

    summary = "bare (config only)" if args.bare else (
        f"modules [{', '.join(selected)}] + config" if selected else "config only"
    )
    print(f"[newsetup] template '{args.template}' -> {target}  ({summary})")

    run("git init", target)

    for m in selected:
        section = data.get(m) if isinstance(data.get(m), dict) else {}
        cwd = section.get("cwd", ".")
        run_dir = target / cwd
        if cwd != ".":
            run_dir.mkdir(parents=True, exist_ok=True)
        for cmd in section.get("commands", []):
            run(cmd, run_dir)
        src = template_dir / m
        if src.is_dir():
            shutil.copytree(src, target / m, dirs_exist_ok=True)
            print(f"[newsetup] copied {m}/ template files")

    if apply_config:
        for f in iter_files(config_dir):
            dest = target / f.relative_to(config_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            print(f"[newsetup] wrote {dest}")

    print(f"\n[newsetup] done. project ready at {target}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="newsetup",
        description="Scaffold projects from templates.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list available templates and their modules")

    p_new = sub.add_parser("new", help="scaffold a new project from a template")
    p_new.add_argument(
        "--path",
        required=True,
        help="where to scaffold: '.' for here, a name for ./<name>, or a full path",
    )
    p_new.add_argument(
        "--template",
        required=True,
        help="template to scaffold from (see `newsetup list`)",
    )
    p_new.add_argument(
        "--only",
        nargs="+",
        metavar="MODULE",
        help="build only these modules (config root files are always included)",
    )
    p_new.add_argument(
        "--bare",
        action="store_true",
        help="config root files only, no modules",
    )
    p_new.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite existing root config files",
    )

    args = parser.parse_args()
    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "new":
        cmd_new(args)
