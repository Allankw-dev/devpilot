import pytest

from app.services.indexing.filters import FileRules, clean_path
from app.services.indexing.languages import language_of
from app.services.indexing.secretscan import contains_secret

RULES = FileRules(max_bytes=1000)


def reason(path: str, size: int = 100, rules: FileRules = RULES) -> str | None:
    cleaned = clean_path(path)
    assert cleaned is not None
    return rules.skip_reason(cleaned, size)


# ---------- what gets indexed ----------


@pytest.mark.parametrize(
    "path",
    [
        "app/main.py", "src/index.ts", "README.md", "Dockerfile", "Makefile", "docs/guide.rst",
        "config/settings.yaml", "pkg/server.go", "src/lib/db.sql", ".github/workflows/ci.yml",
        ".env.example", "secrets.py", "app/core/credentials.py", "src/Vendor.java",
    ],
)  # fmt: skip
def test_normal_source_and_docs_are_indexed(path: str) -> None:
    assert reason(path) is None


# ---------- what is left out, and why ----------


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/react/index.js", "a/b/node_modules/x/y.js", ".git/config",
        "dist/app.js", "build/out.py", "venv/lib/x.py", ".venv/lib/site-packages/y.py",
        "web/.next/server.js", "vendor/lib/a.go", "target/classes/A.java",
        "package-lock.json", "yarn.lock", "poetry.lock", "uv.lock", "requirements.lock",
        "static/app.min.js", "static/app.js.map", "assets/logo.png", "fonts/a.woff2",
        "release.zip", "lib/native.so", "notebooks/a.ipynb",
    ],
)  # fmt: skip
def test_dependencies_build_output_lockfiles_and_binaries_are_excluded(path: str) -> None:
    assert reason(path) == "excluded"


@pytest.mark.parametrize(
    "path",
    [
        ".env", ".env.local", ".env.production", "config/.env", "keys/server.pem",
        "certs/tls.key", "id_rsa", "home/.ssh/id_ed25519", "deploy/store.p12", "app.jks",
        ".npmrc", ".pypirc", "terraform.tfstate", "prod.tfvars", "credentials.json",
        "secrets.yaml", "gcp/service-account-prod.json",
    ],
)  # fmt: skip
def test_files_that_usually_hold_credentials_are_never_indexed(path: str) -> None:
    assert reason(path) == "secret_file"


def test_unknown_file_types_are_skipped() -> None:
    assert reason("data/blob.dat") == "unsupported"
    assert reason("LICENSE.bin") == "excluded"


def test_size_limits() -> None:
    assert reason("a.py", size=1001) == "too_large"
    assert reason("a.py", size=1000) is None
    assert reason("a.py", size=0) == "empty"


def test_extension_matching_is_case_insensitive() -> None:
    assert reason("Assets/LOGO.PNG") == "excluded"
    assert reason("NODE_MODULES/x.js") == "excluded"
    assert reason("CONFIG/.ENV") == "secret_file"


# ---------- user-configured exclusions ----------


def test_extra_excludes_bare_names_globs_and_paths() -> None:
    rules = FileRules(extra_excludes=("generated", "*.snap", "docs/legacy", "src/**/gen_*.py"))
    assert reason("app/generated/models.py", rules=rules) == "excluded"  # bare name: any folder
    assert reason("generated.py", rules=rules) is None  # ...but only whole segments
    assert reason("tests/__snapshots__/a.snap", rules=rules) == "excluded"
    assert reason("docs/legacy/old.md", rules=rules) == "excluded"
    assert reason("docs/legacy_notes.md", rules=rules) is None  # a folder prefix, not a string prefix
    assert reason("src/api/gen_client.py", rules=rules) == "excluded"
    assert reason("src/api/client.py", rules=rules) is None


def test_blank_extra_patterns_are_ignored() -> None:
    assert reason("a.py", rules=FileRules(extra_excludes=("", "  ", "/"))) is None


# ---------- archive member names ----------


@pytest.mark.parametrize(
    "name",
    ["", "/etc/passwd", "../x.py", "a/../../x.py", "..", ".", "a\\b.py", "a\x00b.py", "a\nb.py", "x" * 501],
)
def test_unsafe_paths_are_rejected(name: str) -> None:
    assert clean_path(name) is None


def test_clean_paths_are_normalised() -> None:
    assert clean_path("a/./b//c.py") == "a/b/c.py"
    assert clean_path("a/b/../c.py") == "a/c.py"


def test_language_detection() -> None:
    assert language_of("x/y.TSX") == "typescript"
    assert language_of("Dockerfile") == "dockerfile"
    assert language_of("a/b.unknown") is None


# ---------- secret scanner ----------


@pytest.mark.parametrize(
    "text",
    [
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE...",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "aws_key = 'AKIAIOSFODNN7EXAMPLE'",
        "token = ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
        "GEMINI = 'AIza" + "SyA-1234567890abcdefghijklmnopqrstu'",
        "key: sk-ant-api03-" + "abcdefghijklmnopqrstuvwxyz",
        "slack = xoxb-1234567890-abcdefghij",
        'DATABASE_PASSWORD = "correct-horse-battery-staple-99"',
        "api_key: 'abcdefghijklmnopqrstuvwxyz123456'",
        "STRIPE = 'sk_live_" + "abcdefghijklmnopqrstu'",
    ],
)
def test_credentials_are_detected(text: str) -> None:
    assert contains_secret(text)


@pytest.mark.parametrize(
    "text",
    [
        "def get_password(user): return db.lookup(user)",
        "password = os.environ['DB_PASSWORD']",
        'password = "changeme"',  # short placeholder
        "api_key = settings.api_key",
        "token = request.headers.get('Authorization')",
        "# set GEMINI_API_KEY in your .env file",
        "AKIA is a prefix AWS uses",
        "sk-learn is not a key",
    ],
)
def test_ordinary_code_is_not_flagged(text: str) -> None:
    assert not contains_secret(text)
