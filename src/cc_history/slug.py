"""Convert between Claude Code's slugged project names and filesystem paths.

Claude Code stores sessions at ~/.claude/projects/<slug>/<uuid>.jsonl where
<slug> is the project's absolute path with `/` replaced by `-`. Directory names
that contain literal dashes are not distinguishable on the reverse — we accept
that ambiguity (rare in practice).
"""


def slug_to_path(slug: str) -> str:
    if not slug.startswith("-"):
        return slug
    return "/" + slug[1:].replace("-", "/")


def path_to_slug(path: str) -> str:
    return path.replace("/", "-")
