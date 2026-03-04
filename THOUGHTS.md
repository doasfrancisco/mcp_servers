# Thoughts & Insights

Lessons learned while building and iterating on MCP servers.

## FastMCP (Python)

### Pydantic validation: MCP clients send lists as strings

MCP clients (including Claude Code) send `list[BaseModel]` parameters as **stringified JSON**, not parsed arrays. FastMCP's flexible coercion handles `"10"` → `int` but NOT stringified objects/lists.

**Fix:** Use `Annotated` with Pydantic's `BeforeValidator` to parse the string before validation:

```python
from typing import Annotated
from pydantic import BaseModel, BeforeValidator

def _parse_json_str(v):
    if isinstance(v, str):
        return json.loads(v)
    return v

class MessageRef(BaseModel):
    id: str
    account: str

MessagesList = Annotated[list[MessageRef], BeforeValidator(_parse_json_str)]
```

This is documented in FastMCP's docs under "Validation Modes":
> Pydantic model parameters must be provided as JSON objects (dicts), not as stringified JSON.

### Server instructions vs tool-level instructions

FastMCP only supports instructions at two levels:

1. **Server-level** — `FastMCP("Name", instructions="...")` — sent once on connect, applies globally.
2. **Tool description** — the docstring or `description` param on `@mcp.tool()` — per-tool guidance.

There is no separate per-tool `instructions` field. Use server instructions for behavioral rules (e.g., "confirm before write operations") and tool descriptions for tool-specific usage guidance.

### Tool design: per-item operations > global params

When a tool operates on multiple items that may need different parameters, put the params **on each item** rather than as global tool params. This allows mixed operations in a single call.

**Before** (2 calls needed):
```python
def tag_messages(messages: list[MessageRef], tag: str, remove_tag: str):
    # All messages get the same tag/remove_tag
```

**After** (1 call for mixed operations):
```python
class TagOp(BaseModel):
    id: str
    account: str
    tag: str | None = None
    remove_tag: str | None = None

def tag_messages(messages: list[TagOp]):
    # Each message carries its own instructions
    # Server groups by (account, tag, remove_tag) for efficient batching
```

## Gmail API

### batchModify for bulk operations

Gmail's `batchModify` endpoint handles up to 1000 message IDs per call. Supports `addLabelIds` and `removeLabelIds` simultaneously, so tag swaps are atomic.

```python
service.users().messages().batchModify(
    userId="me",
    body={"ids": [...], "addLabelIds": [...], "removeLabelIds": [...]},
).execute()
```

### Tag system via Gmail labels

Custom tags map directly to Gmail labels (e.g., `credentials`, `contacts`). The `important` tag maps to `STARRED`. Labels are auto-created on first use via `labels().create()`. `list_tags` returns all user-created labels grouped by account.

## MCP Server Design

### Dependency management with uv

Use `pyproject.toml` + `uv run` instead of venv + requirements.txt. Claude Code registers the MCP with:

```
claude mcp add -s user gmail -- uv run --directory /path/to/server fastmcp run server.py
```

No venv activation needed — `uv` handles it transparently.

### Compiling to native binaries for distribution

Code running locally on the user's machine can be protected from reading by compiling to native binaries. Options by runtime:

- **Bun** (JS/TS) — `bun build --compile server.ts --outfile server` — single executable, hard to reverse. Claude Code's own CLI uses this approach.
- **Node.js** — `pkg` or `nexe` — bundles code + runtime into one binary.
- **Python** — Nuitka (compiles to C then to binary, strongest protection) or PyInstaller (bundles but easier to extract).

None are truly unreadable to determined reverse engineers, but they raise the bar significantly vs shipping plain source.
