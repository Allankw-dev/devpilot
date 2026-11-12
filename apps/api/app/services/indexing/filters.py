"""Deciding which files in a repository snapshot get indexed.

The defaults leave out dependencies, build output, lockfiles, binaries and anything that
usually holds credentials. Extra patterns come from the INDEX_EXCLUDE setting.
"""

import fnmatch
import posixpath
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.indexing.languages import language_of

MAX_PATH_LENGTH = 500

EXCLUDED_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "bower_components", "vendor", "third_party",
        "dist", "build", "out", "target", "bin", "obj", ".next", ".nuxt", ".svelte-kit",
        ".output", "coverage", "htmlcov", "__pycache__", ".venv", "venv", "env", ".tox",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode", "pods",
        ".gradle", ".terraform", ".cache", ".parcel-cache", "site-packages",
    }
)  # fmt: skip

EXCLUDED_NAME_GLOBS = (
    # dependency locks and generated files
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock",
    "cargo.lock", "composer.lock", "go.sum", "uv.lock", "requirements.lock", "gemfile.lock",
    "*.min.js", "*.min.css", "*.map", "*.bundle.js", "*.chunk.js", "*.pb.go", "*_pb2.py",
    # images, fonts, archives, binaries
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.ico", "*.svg", "*.bmp", "*.tiff",
    "*.woff", "*.woff2", "*.ttf", "*.otf", "*.eot", "*.zip", "*.tar", "*.gz", "*.tgz",
    "*.7z", "*.rar", "*.jar", "*.war", "*.class", "*.pyc", "*.exe", "*.dll", "*.so",
    "*.dylib", "*.bin", "*.o", "*.a", "*.pdf", "*.mp3", "*.mp4", "*.mov", "*.wav",
    "*.sqlite", "*.db", "*.parquet", "*.ipynb",
)  # fmt: skip

# Names that usually hold credentials. Never indexed, whatever the extension map says.
SECRET_NAME_GLOBS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.ppk",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "credentials", "credentials.json",
    "credentials.yaml", "credentials.yml", "credentials.xml", "credentials.txt",
    ".npmrc", ".pypirc", ".netrc", ".htpasswd", "secrets.json", "secrets.yaml", "secrets.yml",
    "secrets.toml", "secrets.txt", "secrets.env", "*.tfstate", "*.tfstate.*",
    "*.tfvars", "service-account*.json", "*serviceaccount*.json",
)  # fmt: skip
SECRET_NAME_ALLOWED = frozenset({".env.example", ".env.sample", ".env.template", ".env.dist"})


def clean_path(name: str) -> str | None:
    """Normalise an archive member name. None for anything that isn't a plain relative path."""
    if not name or "\\" in name or "\x00" in name or any(ord(c) < 32 for c in name):
        return None
    if name.startswith("/") or len(name) > MAX_PATH_LENGTH:
        return None
    normal = posixpath.normpath(name)
    if normal.startswith("../") or normal in ("..", "."):
        return None
    return normal


def _matches_extra(path_lower: str, patterns: Sequence[str]) -> bool:
    segments = path_lower.split("/")
    name = segments[-1]
    for raw in patterns:
        pattern = raw.strip().strip("/").lower()
        if not pattern:
            continue
        if not any(ch in pattern for ch in "*?/"):
            if pattern in segments:  # a bare name excludes any folder or file called that
                return True
        elif "*" not in pattern and "?" not in pattern:
            if path_lower == pattern or path_lower.startswith(pattern + "/"):
                return True
        elif fnmatch.fnmatchcase(path_lower, pattern) or fnmatch.fnmatchcase(name, pattern):
            return True
    return False


@dataclass(frozen=True)
class FileRules:
    max_bytes: int = 200_000
    extra_excludes: tuple[str, ...] = ()

    def skip_reason(self, path: str, size: int) -> str | None:
        """Why a file is left out, or None if it should be indexed. `path` is clean_path()'d."""
        lower = path.lower()
        segments = lower.split("/")
        name = segments[-1]

        if any(seg in EXCLUDED_DIRS for seg in segments[:-1]):
            return "excluded"
        if name not in SECRET_NAME_ALLOWED and any(
            fnmatch.fnmatchcase(name, g) for g in SECRET_NAME_GLOBS
        ):
            return "secret_file"
        if any(fnmatch.fnmatchcase(name, g) for g in EXCLUDED_NAME_GLOBS):
            return "excluded"
        if _matches_extra(lower, self.extra_excludes):
            return "excluded"
        if language_of(path) is None:
            return "unsupported"
        if size > self.max_bytes:
            return "too_large"
        if size == 0:
            return "empty"
        return None
