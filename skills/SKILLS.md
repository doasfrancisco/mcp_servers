# Skills

How to build and deploy Claude Code skills in this repo.

## What is a skill?

A skill is a folder with a `SKILL.md` file that teaches Claude Code how to do something specific. When the user types `/skill-name`, Claude reads the SKILL.md and follows its instructions.

## Structure

```
skills/
  my-skill/
    SKILL.md        # Required — the skill definition
    README.md       # Optional — credits, context, links
    scripts/        # Optional — scripts the skill runs
    assets/         # Optional — files the skill needs
```

## Building a skill step by step

### 1. Create the folder

```bash
mkdir skills/my-skill
```

### 2. Write `SKILL.md`

Every SKILL.md has two parts:

**Frontmatter** — name, description, and trigger conditions:

```markdown
---
name: my-skill
description: One-line description of what it does and when to use it.
---
```

The `description` field is what Claude uses to decide whether to trigger the skill. Be specific about trigger phrases (e.g., "Use when the user says 'push', 'ship it', or invokes /my-skill").

**Body** — the actual instructions Claude follows. Write it like you're briefing a colleague:

- Tell Claude exactly what commands to run
- Specify the order of operations
- Include the output format you want
- Add rules for edge cases

### 3. Add scripts or assets (optional)

If your skill needs to run code, put scripts in `scripts/`. Reference them from SKILL.md with:

```bash
python <skill-path>/scripts/my_script.py
```

`<skill-path>` is automatically resolved to the installed skill directory at runtime.

### 4. Add a README (optional)

For credits, source links, or context that isn't part of the skill instructions.

## Deploying

Skills are developed here in `skills/` and deployed to `~/.claude/skills/` using `deploy.py`.

```bash
# Deploy one or more skills
python deploy.py --add my-skill
python deploy.py --add my-skill another-skill

# Deploy all skills
python deploy.py --all

# Check what changed without deploying
python deploy.py --diff my-skill

# List available skills and their install status
python deploy.py --list
```

After deploying, the skill is immediately available as `/my-skill` in any Claude Code session.

## Tips

- **Keep SKILL.md focused.** One skill = one job. If it's doing two things, make two skills.
- **Be explicit about output format.** If you want a report, specify the sections. If you want silence, say "move on silently."
- **Don't over-guard.** If a check produces false positives, users will stop trusting the skill. Only flag real problems.
- **Test by invoking.** After deploying, run `/my-skill` and see if the behavior matches what you wanted. Iterate on the SKILL.md.
