"""Check glossary code-source paths and local Markdown links (stdlib only)."""
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def check(root: Path = ROOT) -> list[str]:
    errors = []
    glossary = root / "docs/glossary.md"
    code_table = False
    for number, line in enumerate(glossary.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("|"):
            code_table = False
        elif "代码出处" in line:
            code_table = True
        if not code_table or not line.startswith("| **"):
            continue
        source = line.rsplit("|", 2)[-2]
        paths = re.findall(r"`([^`]+\.(?:py|md))`", source)
        if not paths:
            errors.append(f"docs/glossary.md:{number}: missing code-source path")
        for path in paths:
            if not (root / path).is_file():
                errors.append(f"docs/glossary.md:{number}: missing {path}")
    for name in ("README.md", "docs/glossary.md", "docs/README.md"):
        document = root / name
        for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            target = unquote(target.strip("<>").split("#", 1)[0])
            if not target or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            if not (document.parent / target).exists():
                errors.append(f"{name}: missing link {target}")
    return errors


if __name__ == "__main__":
    failures = check()
    print("\n".join(failures) if failures else "Glossary source paths and local documentation links OK")
    sys.exit(bool(failures))
