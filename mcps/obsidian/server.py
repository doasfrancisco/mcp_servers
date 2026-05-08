"""Obsidian MCP — books knowledge base.

Three tools:
    raw_graph()                              graph of raw/ — md+pdf+image
                                             nodes + wikilink/embed/fm edges
    read(path)                               read a .md file
    write(path, content="", image_path=...)  write a .md (content=) or
                                             image (image_path=, server
                                             reads bytes from local disk)

PDFs are visible in the graph but not readable through this server. The
markdown layer is the human↔AI channel.
"""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

from obsidian_client import ObsidianClient, build_graph

_log_dir = Path(__file__).parent / "logs"
_log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[RotatingFileHandler(_log_dir / "obsidian.log", maxBytes=5_000_000, backupCount=1)],
)

from fastmcp import FastMCP

mcp = FastMCP(
    "Obsidian",
    instructions="""Personal Obsidian KB of math + CS books. Layout:
  raw/<book>/<book>.md          (hub: frontmatter + nav callout + summary)
  raw/<book>/*.pdf              (sources: textbook, solutions, errata, ...)
  raw/<book>/notes.md           (notes INDEX: frontmatter `book: [[X]]`,
                                  body minimal — children link UP to it)
  raw/<book>/notes/<slug>.md    (atomic notes: frontmatter
                                  `parent: [[notes]]` only — book is
                                  reached transitively via notes)
  attachments/<book>/*.png|jpg  (screenshots, diagrams)
  wiki/                         (LLM-compiled output — only on explicit
                                  "compile" / "rebuild concepts" requests)

THREE TOOLS:
  raw_graph()                              full graph of raw/
  read(path)                               read a .md file
  write(path, content="",                  write a .md (use content=) or
        image_path=None)                   an image (use image_path=)

IMPORTANT: discover schemas with ToolSearch before first call.

ALWAYS START WITH raw_graph. Don't read blindly. The graph tells you
what exists, node types (hub|notes|note|other_md|pdf|image), the
wikilinks, and which links are ghosts (target_exists: false). All
read/write decisions follow from it.

NOTES MODEL — ATOMIC, ZETTELKASTEN-STYLE:
  - notes.md is an INDEX node. Frontmatter `book: [[X]]`, body minimal
    (a tagline at most). DO NOT pile entries into notes.md.
  - Each thought lives in raw/<book>/notes/<slug>.md with frontmatter
    `parent: [[notes]]` ONLY — no `book:` field. The book is reached
    transitively (atomic note → notes → book), no direct edge.
  - Slug is kebab-case from the concept name (e.g.
    inyectividad-y-predecesores.md). Optional metadata in frontmatter:
    `created`, `chapter`, `section`.
  - notes.md does NOT need to list children — Obsidian shows backlinks
    automatically via the children's `parent: [[notes]]` edge.
  - Adding a note flow: (1) raw_graph, (2) read existing notes whose
    titles touch the same concept, (3) decide:
        a) belongs in an existing note → read it, append, write back
        b) distinct concept           → create new <slug>.md

PDFS ARE NOT READABLE. They appear in the graph as nodes (with page
count + extractable from the sibling hub's sources[]) so you know they
exist, but `read` is .md-only. If asked "what does ch.3 of Lages say?",
you cannot answer from the PDF. Offer to: (a) search atomic notes that
reference ch.3, (b) summarize what the hub records, (c) ask the user
to paste the passage. Do not pretend to have read the PDF.

SCREENSHOTS / IMAGES:
  - Vault path: attachments/<book>/<yyyy-mm-dd>-<slug>.png|jpg|webp
  - User pastes a screenshot or hands you a local fs path. Use Bash to
    locate it on disk if needed, then call:
        write(path="attachments/Lages/2026-05-04-inyectividad.png",
              image_path="C:/Users/.../screenshot.png")
  - Reference from a note with `![[2026-05-04-inyectividad.png]]`.
  - Allowed extensions: .png .jpg .jpeg .webp.

APPEND = READ-MODIFY-WRITE. `write` is a full overwrite for .md. To
extend an existing atomic note, read first, modify in memory, write
the whole thing back. Partial writes destroy what's there.

PRESERVE FRONTMATTER. Never drop, reorder, or silently mutate YAML
frontmatter unless asked. Frontmatter is the queryable schema and the
edge backbone of the graph (parent, book, status, sources, tags).
Same for nav callouts in hubs.

WIKILINK HYGIENE. Use [[Exact Basename]] from raw_graph. Don't invent
ghost links. If you must reference something that doesn't exist, say
so explicitly and offer to create it.

NO NEW TOP-LEVEL FOLDERS. Only raw/, wiki/, attachments/ by design.
New books go in raw/<book>/. New atomic notes go in raw/<book>/notes/.
Don't invent siblings.

CONFIRM BEFORE WRITE. Tell the user the path, the mode (.md content vs
image), and a one-line summary. Stop. Wait for confirmation. Exception:
if pre-authorized ("just log this"), proceed.

PRESENTATION when showing the graph:
- Group by folder (one section per book in raw/)
- For each book: **Title** — Author · status · sources (mark "needs OCR"
  if all sources are unextractable)
- For each book: list of atomic notes with one-line summaries
- Surface ghost links explicitly — they're gaps in the KB
- Don't dump raw JSON; render as prose + nested lists.
""",
)


_client: ObsidianClient | None = None


def _get_client() -> ObsidianClient:
    global _client
    if _client is None:
        _client = ObsidianClient.from_env()
    return _client


_MIME = {
    ".md": "text/markdown",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _ext(path: str) -> str:
    return "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _normalize(path: str) -> str:
    p = path.replace("\\", "/").lstrip("/")
    if not p:
        raise ValueError("path is empty")
    parts = p.split("/")
    if any(part in ("..", "") for part in parts):
        raise ValueError(f"invalid path: {path!r}")
    if _ext(p) not in _MIME:
        raise ValueError(
            f"unsupported extension for {path!r}; "
            f"allowed: {', '.join(_MIME.keys())}"
        )
    return p


@mcp.tool()
def raw_graph() -> str:
    """Return the graph of `raw/` — every .md, .pdf, and image node,
    plus the wikilink/embed/frontmatter edges between them.

    Shape:
        {
          "nodes": [
            {"path": str,
             "type": "hub|notes|note|other_md|pdf|image|other",
             "frontmatter"?: dict,           # for .md
             "pages"?: int, "extractable"?: bool, "role"?: str  # for .pdf
            }, ...
          ],
          "edges": [
            {"from": path, "to": path-or-basename,
             "kind": "wikilink|embed|frontmatter",
             "target_exists": bool}, ...
          ]
        }

    Call this at the start of every session to orient. Cheap and
    idempotent — no caching needed by the caller.
    """
    g = build_graph(_get_client(), root="raw")
    return json.dumps(g, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
def read(path: str) -> str:
    """Read a markdown file from the vault. Path must end in .md.

    Args:
        path: Vault-relative path, e.g.
              "raw/Analisis Real - Lages/Analisis Real - Lages.md"
    """
    p = _normalize(path)
    try:
        return _get_client().read_text(p)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            raise ValueError(f"file not found: {p}") from None
        raise


@mcp.tool()
def write(path: str, content: str = "", image_path: str | None = None) -> str:
    """Write a file to the vault. Full overwrite — creates or replaces.

    Two modes, dispatched by `path`'s extension:

      .md path                → markdown write. Pass `content` (string).
      .png/.jpg/.jpeg/.webp   → image write. Pass `image_path` (absolute
                                local filesystem path). Server reads
                                bytes from disk and PUTs as image/*.

    To append to a markdown file, read first, modify in memory, then
    write the whole file back. Partial writes destroy existing content.

    Args:
        path: Vault-relative path, must end in .md or an image extension.
        content: Full markdown body (used only for .md paths).
        image_path: Absolute local filesystem path to the image file
                    (used only for image paths). Extension must match
                    `path`'s extension.
    """
    p = _normalize(path)
    ext = _ext(p)
    mime = _MIME[ext]

    if ext in _IMAGE_EXTS:
        if not image_path:
            raise ValueError(f"writing to {ext} requires image_path")
        if content:
            raise ValueError(f"{ext} writes use image_path=, not content=")
        src = Path(image_path)
        if _ext(src.name) != ext:
            raise ValueError(
                f"image_path extension ({_ext(src.name)!r}) must match "
                f"vault path extension ({ext!r})"
            )
        try:
            body = src.read_bytes()
        except OSError as e:
            raise ValueError(f"failed to read image_path {image_path!r}: {e}") from None
    else:
        if image_path:
            raise ValueError(".md writes use content=, not image_path=")
        body = content.encode("utf-8")

    _get_client().write_bytes(p, body, mime)
    return json.dumps({"path": p, "bytes": len(body)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
