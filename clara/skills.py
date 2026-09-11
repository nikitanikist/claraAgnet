import io
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_name(name):
    if not NAME.fullmatch(name) or len(name) > 64:
        raise ValueError("Use a skill name with lowercase letters, numbers and hyphens (maximum 64 characters).")
    return name


def metadata(text):
    match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.S)
    if not match:
        raise ValueError("SKILL.md needs YAML frontmatter with name and description.")
    result = {}
    for key in ("name", "description"):
        found = re.search(rf"^{key}:\s*(.+)$", match[1], re.M)
        if not found:
            raise ValueError(f"Missing {key} in skill frontmatter. Use a single-line description.")
        result[key] = found.group(1).strip().strip('"\'')
    validate_name(result["name"])
    if not result["description"] or len(result["description"]) > 1500:
        raise ValueError("Skill description must be 1–1500 characters.")
    return result


def list_skills(config):
    skills = []
    for file in sorted(config.skills.glob("*/SKILL.md")):
        try:
            text = file.read_text(encoding="utf-8")
            skills.append({**metadata(text), "content": text, "files": len(list(file.parent.rglob("*")))})
        except (ValueError, OSError):
            continue
    return skills


def save_skill(config, name, content):
    validate_name(name)
    info = metadata(content)
    if info["name"] != name:
        raise ValueError("Folder name and frontmatter name must match.")
    if len(content.encode()) > 200_000:
        raise ValueError("Keep SKILL.md below 200 KB; attach longer resources separately.")
    directory = config.skills / name
    directory.mkdir(exist_ok=True)
    temporary = directory / "SKILL.tmp"
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(directory / "SKILL.md")
    return info


def import_skill(config, filename, data):
    if len(data) > 10_000_000:
        raise ValueError("Skill uploads are limited to 10 MB.")
    if filename.lower().endswith(".md"):
        content = data.decode("utf-8-sig")
        info = metadata(content)
        if (config.skills / info["name"]).exists():
            raise ValueError("That skill exists. Use the editor to update it.")
        return save_skill(config, info["name"], content)
    if not filename.lower().endswith(".zip"):
        raise ValueError("Upload a SKILL.md or a ZIP containing one skill folder.")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 200 or sum(e.file_size for e in entries) > 20_000_000:
            raise ValueError("Skill archive exceeds 200 files or 20 MB expanded.")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename
                    or ((entry.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError("Unsafe path or symlink in skill ZIP.")
            if any(part.lower() in {".env", ".git", "node_modules", ".claude"} for part in path.parts):
                raise ValueError("Remove credentials, configuration and dependency folders from the skill ZIP.")
        candidates = [e for e in entries if PurePosixPath(e.filename).name == "SKILL.md"]
        if len(candidates) != 1:
            raise ValueError("Upload exactly one skill with one SKILL.md.")
        entry = candidates[0]
        if entry.file_size > 200_000:
            raise ValueError("SKILL.md exceeds 200 KB.")
        info = metadata(archive.read(entry).decode("utf-8-sig"))
        prefix = PurePosixPath(entry.filename).parent
        destination = config.skills / info["name"]
        if destination.exists():
            raise ValueError("That skill already exists.")
        with tempfile.TemporaryDirectory(dir=config.data) as temporary:
            staging = Path(temporary) / info["name"]
            staging.mkdir()
            for member in entries:
                path = PurePosixPath(member.filename)
                if member.is_dir():
                    continue
                try:
                    relative = path.relative_to(prefix)
                except ValueError:
                    raise ValueError("All files must be inside the skill folder.")
                target = staging.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
            shutil.move(str(staging), str(destination))
        return info
