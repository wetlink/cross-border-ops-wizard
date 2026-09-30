#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REFERENCE_RE = re.compile(r"(?:references|scripts)/[A-Za-z0-9_./-]+")


class ValidationError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and package this Skill repository.")
    parser.add_argument("--skill-name", default="", help="Skill directory name. Defaults to the only folder under skill/.")
    parser.add_argument("--keep-staging", action="store_true", help="Keep .skill-package-staging/<skill-name>.")
    parser.add_argument("--zip", action="store_true", help="Write skill/<skill-name>/<skill-name>.zip after validation.")
    return parser.parse_args()


def resolve_skill_name(root: Path, explicit: str) -> str:
    if explicit:
        return explicit
    skill_root = root / "skill"
    names = [p.name for p in skill_root.iterdir() if p.is_dir()]
    if len(names) != 1:
        raise ValidationError("Expected exactly one directory under skill/. Pass --skill-name.")
    return names[0]


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValidationError(f"{path} must start with YAML frontmatter.")
    try:
        _, frontmatter, body = text.split("---\n", 2)
    except ValueError as exc:
        raise ValidationError(f"{path} frontmatter is not closed.") from exc
    data: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValidationError(f"Invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
    if "name" not in data or "description" not in data:
        raise ValidationError("Frontmatter must contain name and description.")
    return data, body


def copy_tree_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        if path.name == ".DS_Store" or path.suffix in (".zip", ".pyc", ".pyo") or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def build_package(root: Path, skill_name: str, staging_parent: Path) -> Path:
    source_skill = root / "skill" / skill_name / "SKILL.md"
    if not source_skill.is_file():
        raise ValidationError(f"Missing skill/{skill_name}/SKILL.md")
    package_dir = staging_parent / skill_name
    package_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_skill, package_dir / "SKILL.md")
    copy_tree_if_exists(root / "references", package_dir / "references")
    copy_tree_if_exists(root / "scripts", package_dir / "scripts")
    validate_frontmatter(package_dir / "SKILL.md", skill_name)
    validate_references(package_dir)
    return package_dir


def validate_frontmatter(skill_md: Path, skill_name: str) -> None:
    data, _ = parse_frontmatter(skill_md)
    unexpected = sorted(set(data) - {"name", "description"})
    if unexpected:
        raise ValidationError(
            "Unexpected SKILL.md frontmatter keys: " + ", ".join(unexpected)
        )
    name = data["name"]
    if not NAME_RE.fullmatch(name):
        raise ValidationError(f"Skill name '{name}' must be lowercase hyphen-case.")
    if name != skill_name:
        raise ValidationError(f"Skill name '{name}' must match folder '{skill_name}'.")
    if len(data["description"]) < 20:
        raise ValidationError("Skill description is too short.")


def validate_references(package_dir: Path) -> None:
    _, body = parse_frontmatter(package_dir / "SKILL.md")
    refs = sorted(set(REFERENCE_RE.findall(body)))
    missing = [ref for ref in refs if not (package_dir / ref).is_file()]
    if missing:
        raise ValidationError("Missing bundled references: " + ", ".join(missing))


def validate_python(root: Path) -> None:
    py_files = sorted((root / "scripts").glob("*.py")) if (root / "scripts").exists() else []
    if not py_files:
        return
    cmd = [sys.executable, "-m", "py_compile", *map(str, py_files)]
    cp = subprocess.run(cmd, text=True, capture_output=True)
    if cp.returncode != 0:
        raise ValidationError(cp.stderr or cp.stdout)


def write_zip(package_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name == ".DS_Store" or path.suffix == ".zip":
                continue
            zf.write(path, path.relative_to(package_dir.parent))
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
    if bad:
        raise ValidationError(f"Zip integrity check failed at {bad}")


def main() -> int:
    root = Path.cwd()
    args = parse_args()
    try:
        skill_name = resolve_skill_name(root, args.skill_name)
        validate_python(root)
        with tempfile.TemporaryDirectory(prefix=f"{skill_name}.") as tmp:
            package_dir = build_package(root, skill_name, Path(tmp))
            if args.keep_staging:
                kept_parent = root / ".skill-package-staging"
                kept_dir = kept_parent / skill_name
                if kept_parent.exists():
                    shutil.rmtree(kept_parent)
                kept_parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(package_dir, kept_dir)
                print(f"[ok] kept staged package: {kept_dir}")
            if args.zip:
                zip_path = root / "skill" / skill_name / f"{skill_name}.zip"
                write_zip(package_dir, zip_path)
                print(f"[ok] wrote zip: {zip_path}")
        print(f"[ok] {skill_name} skill package validated")
        return 0
    except ValidationError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
