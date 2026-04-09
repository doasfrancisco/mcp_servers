"""Deploy skills from skills/ to ~/.claude/skills/."""

import argparse
import os
import shutil
import sys
from pathlib import Path

SKILLS_SRC = Path(__file__).parent / "skills"
SKILLS_DST = Path.home() / ".claude" / "skills"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def available_skills():
    return sorted(d.name for d in SKILLS_SRC.iterdir() if d.is_dir())


def deploy_skill(name: str):
    src = SKILLS_SRC / name
    dst = SKILLS_DST / name

    if not src.is_dir():
        print(f"{RED}Error: skill '{name}' not found in {SKILLS_SRC}{RESET}")
        sys.exit(1)

    # Remove old install, then copy fresh — excluding .skill binary packages
    if dst.exists():
        shutil.rmtree(dst)

    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.skill"))
    print(f"{GREEN}Deployed '{name}' -> {dst}{RESET}")


def diff_skill(name: str):
    src = SKILLS_SRC / name
    dst = SKILLS_DST / name

    if not src.is_dir():
        print(f"{RED}Error: skill '{name}' not found in {SKILLS_SRC}{RESET}")
        sys.exit(1)

    if not dst.is_dir():
        print(f"{YELLOW}'{name}' not yet installed — full deploy needed{RESET}")
        return

    diffs_found = False
    src_files = {p.relative_to(src) for p in src.rglob("*") if p.is_file() and p.suffix != ".skill"}
    dst_files = {p.relative_to(dst) for p in dst.rglob("*") if p.is_file()}

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
        print(f"{GREEN}'{name}' is up to date{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Deploy skills to ~/.claude/skills/")
    parser.add_argument("--add", nargs="+", metavar="SKILL", help="Deploy one or more skills")
    parser.add_argument("--all", action="store_true", help="Deploy all skills")
    parser.add_argument("--diff", metavar="SKILL", help="Show what would change without deploying")
    parser.add_argument("--list", action="store_true", help="List available skills")
    args = parser.parse_args()

    if args.list or (not args.add and not args.all and not args.diff):
        print("Available skills:")
        for name in available_skills():
            dst = SKILLS_DST / name
            status = "installed" if dst.is_dir() else "not installed"
            print(f"  {name}  ({status})")
        if not args.list:
            print(f"\nUsage: python {Path(__file__).name} --add <skill> [...] | --all | --diff <skill>")
        return

    if args.diff:
        diff_skill(args.diff)
    elif args.all:
        for name in available_skills():
            deploy_skill(name)
    else:
        for name in args.add:
            deploy_skill(name)


if __name__ == "__main__":
    main()
