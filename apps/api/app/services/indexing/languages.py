"""Which files are worth indexing, and what language they are."""

import posixpath

LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".dart": "dart",
    ".lua": "lua",
    ".r": "r",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".less": "css",
    ".vue": "vue",
    ".svelte": "svelte",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "text",
    ".txt": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".xml": "xml",
    ".gradle": "gradle",
    ".tf": "terraform",
    ".proto": "protobuf",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".dockerfile": "dockerfile",
}

# Files without a useful extension, matched on the whole (lower-cased) name.
LANGUAGE_BY_NAME: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    ".env.example": "env",
    ".env.sample": "env",
    ".env.template": "env",
    ".env.dist": "env",
    "readme": "markdown",
    "license": "text",
    "jenkinsfile": "groovy",
    "gemfile": "ruby",
    "rakefile": "ruby",
}


def language_of(path: str) -> str | None:
    """None means 'not a file type we index'."""
    name = posixpath.basename(path).lower()
    if name in LANGUAGE_BY_NAME:
        return LANGUAGE_BY_NAME[name]
    return LANGUAGE_BY_EXTENSION.get(posixpath.splitext(name)[1])
