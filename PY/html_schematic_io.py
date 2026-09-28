"""
html_schematic_io.py
────────────────────
Safe read/write helpers for the embedded schematic JSON block inside
SUMO24 MCP schematic-builder HTML files.

The key technique: comments are replaced with whitespace of the same length
before the regex runs, so a reference to <script id="schematic-data"> inside
an HTML comment never matches. The regex then operates on the comment-stripped
copy, but the splice indices are applied to the *original* raw text — so no
content is altered except the JSON block itself.

Post-edit structural validation ensures the file still contains the
canonical builder-function markers before it is written to disk.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil

# Strip comments from a working copy but keep offsets aligned.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Match the schematic-data script tag (both attribute orders accepted).
_TAG_RE = re.compile(
    r'<script\s+id="schematic-data"\s+type="application/json"\s*>(.*?)</script>',
    re.DOTALL,
)

# Markers that must survive the edit — if any are absent the write is refused.
_REQUIRED_MARKERS = (
    "<style",
    "<body",
    "buildStateJSON",
    "persistState",
    "loadFromJSON",
)


def update_schematic_in_html(
    html_path: "str | pathlib.Path",
    new_json_text: str,
    backup: bool = True,
) -> dict:
    """
    Replace the embedded schematic JSON in *html_path* with *new_json_text*.

    Parameters
    ----------
    html_path     : path to the schematic-builder HTML file.
    new_json_text : the new JSON as a string (will be validated before writing).
                    May also be a path ending in '.json', in which case the
                    file is read first.
    backup        : if True, a .bak copy is written before the file is modified.

    Returns
    -------
    dict with keys: ok, bytes_written, backup (path or None).

    Raises
    ------
    ValueError  if the tag is not found outside comments, if JSON is invalid,
                or if post-edit structural markers are missing.
    OSError     on file I/O failures.
    """
    html_path = pathlib.Path(html_path)

    # Accept a .json path as new_json_text.
    if isinstance(new_json_text, str) and new_json_text.strip().endswith(".json"):
        candidate = pathlib.Path(new_json_text)
        if candidate.exists():
            new_json_text = candidate.read_text(encoding="utf-8")

    # 1. Read the original file.
    raw = html_path.read_text(encoding="utf-8")

    # 2. Build a comment-stripped copy of the *same byte length* so regex
    #    offsets from the stripped copy map directly into the original.
    stripped = _COMMENT_RE.sub(lambda m: " " * len(m.group(0)), raw)

    # 3. Find the real (non-comment) script tag.
    m = _TAG_RE.search(stripped)
    if not m:
        raise ValueError(
            "No <script id='schematic-data' type='application/json'> tag found "
            "outside HTML comments in " + str(html_path)
        )

    # 4. Validate the new JSON before touching disk.
    try:
        json.loads(new_json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"new_json_text is not valid JSON: {exc}") from exc

    # 5. Splice into the original raw string using offsets from the stripped copy.
    start, end = m.start(1), m.end(1)
    new_raw = raw[:start] + "\n" + new_json_text.strip() + "\n" + raw[end:]

    # 6. Post-edit structural sanity — refuse if any required marker vanished.
    for required in _REQUIRED_MARKERS:
        if required not in new_raw:
            raise ValueError(
                f"Post-edit file lost required marker {required!r}; "
                "refusing to write. Check that new_json_text does not contain "
                "the closing </script> or </body> tags."
            )

    # 7. Backup + write.
    backup_path = None
    if backup:
        backup_path = str(html_path) + ".bak"
        shutil.copy2(html_path, backup_path)

    html_path.write_text(new_raw, encoding="utf-8")

    return {
        "ok":            True,
        "bytes_written": len(new_raw.encode("utf-8")),
        "backup":        backup_path,
    }


def read_schematic_from_html(html_path: "str | pathlib.Path") -> dict:
    """
    Extract and return the embedded schematic JSON from *html_path*.

    Returns the parsed dict on success. Raises ValueError if the tag is
    not found or the content is not valid JSON.
    """
    html_path = pathlib.Path(html_path)
    raw = html_path.read_text(encoding="utf-8")
    stripped = _COMMENT_RE.sub(lambda m: " " * len(m.group(0)), raw)
    m = _TAG_RE.search(stripped)
    if not m:
        raise ValueError(
            "No <script id='schematic-data' type='application/json'> tag found "
            "outside HTML comments in " + str(html_path)
        )
    return json.loads(m.group(1))
