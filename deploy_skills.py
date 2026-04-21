"""Deploy skills from skills/ to Claude and Droid personal skill folders."""

import argparse
import os
import shutil
import sys
from pathlib import Path

SKILLS_SRC = Path(__file__).parent / "skills"
DESTINATIONS = {
    "claude": Path.home() / ".claude" / "skills",
    "droid": Path.home() / ".factory" / "skills",
}

def _supports_color():
    """Check if the terminal supports ANSI color codes."""
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        # Windows 10+ supports ANSI if virtual terminal processing is enabled.
        # os.system("") is a known trick to flip the flag on.
        try:
            os.system("")
            return True
        except Exception:
            return False
    return True


_COLOR = _supports_color()
RED = "\033[31m" if _COLOR else ""
GREEN = "\033[32m" if _COLOR else ""
YELLOW = "\033[33m" if _COLOR else ""
RESET = "\033[0m" if _COLOR else ""


def available_skills():
    return sorted(d.name for d in SKILLS_SRC.iterdir() if d.is_dir())


def installed_skills():
    installed = set()
    for root in DESTINATIONS.values():
        if root.is_dir():
            installed.update(d.name for d in root.iterdir() if d.is_dir())
    return sorted(installed)


def deploy_skill(name: str):
    src = SKILLS_SRC / name

    if not src.is_dir():
        print(f"{RED}Error: skill '{name}' not found in {SKILLS_SRC}{RESET}")
        sys.exit(1)

    for label, root in DESTINATIONS.items():
        dst = root / name
        root.mkdir(parents=True, exist_ok=True)

        # Remove old install, then copy fresh — excluding .skill binary packages
        if dst.exists():
            shutil.rmtree(dst)

        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.skill"))
        print(f"{GREEN}Deployed '{name}' -> {dst} [{label}]{RESET}")


def diff_skill(name: str):
    src = SKILLS_SRC / name

    if not src.is_dir():
        print(f"{RED}Error: skill '{name}' not found in {SKILLS_SRC}{RESET}")
        sys.exit(1)

    for label, root in DESTINATIONS.items():
        dst = root / name

        if not dst.is_dir():
            print(f"{YELLOW}'{name}' not yet installed in {label} — full deploy needed{RESET}")
            continue

        diffs_found = False
        src_files = {p.relative_to(src) for p in src.rglob("*") if p.is_file() and p.suffix != ".skill"}
        dst_files = {p.relative_to(dst) for p in dst.rglob("*") if p.is_file()}

        print(f"{label}:")

        for rel in sorted(src_files - dst_files):
            print(f"  + {rel}  (new)")
            diffs_found = True

        for rel in sorted(dst_files - src_files):
            print(f"  - {rel}  (removed)")
            diffs_found = True

        for rel in sorted(src_files & dst_files):
            if (src / rel).read_bytes() != (dst / rel).read_bytes():
                print(f"  ~ {rel}  (modified)")
                diffs_found = True

        if not diffs_found:
            print(f"{GREEN}  '{name}' is up to date{RESET}")


def remove_skills(names: list[str]):
    # IMPORTANT: Callers should still make sure the user actually wanted this
    # before running `--remove`, because it deletes the named skills from both
    # ~/.claude/skills and ~/.factory/skills in one shot with no extra prompt.

    for name in names:
        found = False
        for label, root in DESTINATIONS.items():
            dst = root / name
            if dst.is_dir():
                found = True
                shutil.rmtree(dst)
                print(f"{GREEN}Removed '{name}' from {dst} [{label}]{RESET}")
        if not found:
            print(f"{YELLOW}'{name}' is not installed in Claude or Droid{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Deploy skills to Claude and Droid personal skill folders.")
    parser.add_argument("--add", nargs="+", metavar="SKILL", help="Deploy one or more skills")
    parser.add_argument("--all", action="store_true", help="Deploy all skills")
    parser.add_argument("--diff", metavar="SKILL", help="Show what would change without deploying")
    parser.add_argument("--list", action="store_true", help="List available skills")
    parser.add_argument("--remove", nargs="+", metavar="SKILL", help="Remove one or more installed skills from both Claude and Droid")
    args = parser.parse_args()

    if args.list or (not args.add and not args.all and not args.diff and not args.remove):
        print("Available skills:")
        for name in available_skills():
            statuses = []
            for label, root in DESTINATIONS.items():
                status = "installed" if (root / name).is_dir() else "not installed"
                statuses.append(f"{label}: {status}")
            print(f"  {name}  ({', '.join(statuses)})")
        if not args.list:
            print(f"\nUsage: python {Path(__file__).name} --add <skill> [...] | --all | --diff <skill> | --remove <skill> [...]")
        return

    if args.diff:
        diff_skill(args.diff)
    elif args.remove:
        remove_skills(args.remove)
    elif args.all:
        for name in available_skills():
            deploy_skill(name)
    else:
        for name in args.add:
            deploy_skill(name)


if __name__ == "__main__":
    main()
