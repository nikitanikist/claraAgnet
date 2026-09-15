"""Local application configuration. No model credentials are stored here."""
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
PROJECT = PACKAGE.parent
STARTER_SKILLS = PACKAGE / "starter_skills"
SIDECAR = ".clara-starter.sha256"


def atomic_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


@dataclass
class Config:
    data: Path
    port: int = 8876
    pending_skill_updates: list = field(default_factory=list, repr=False, compare=False)

    @property
    def workspace(self):
        return self.data / "workspace"

    @property
    def skills(self):
        return self.workspace / ".claude" / "skills"

    @property
    def settings_file(self):
        return self.data / "settings.json"

    def initialize(self):
        self.data = self.data.expanduser().resolve()
        for directory in (self.data, self.workspace, self.skills, self.data / "attachments", self.data / "artifacts"):
            directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.data.chmod(0o700)
        if not self.settings_file.exists():
            self.save_settings({"model": "sonnet", "max_turns": 40, "task_timeout_minutes": 20,
                                "read_roots": [], "browser_enabled": False,
                                "desktop_enabled": False, "max_budget_usd": None,
                                "default_execution_mode": "autonomous", "reasoning_effort":"medium"})
        self.pending_skill_updates = self.refresh_starter_skills()
        (self.workspace / "outputs").mkdir(exist_ok=True)
        from .skill_pack import install
        install(self)
        return self.pending_skill_updates

    def refresh_starter_skills(self):
        """Install packaged starter skills; refresh unmodified installs, keep operator edits, report the rest."""
        pending = []
        for source in sorted(STARTER_SKILLS.glob("*")):
            if not source.is_dir() or not (source / "SKILL.md").is_file():
                continue
            target = self.skills / source.name
            sidecar = target / SIDECAR
            packaged = _sha256(source / "SKILL.md")
            if not target.exists():
                shutil.copytree(source, target)
                sidecar.write_text(packaged + "\n", encoding="utf-8")
                continue
            current = _sha256(target / "SKILL.md") if (target / "SKILL.md").is_file() else None
            installed = sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else None
            if installed is None:
                if current == packaged:
                    sidecar.write_text(packaged + "\n", encoding="utf-8")
                else:
                    pending.append({"skill": source.name, "installed_sha256": current,
                                    "packaged_sha256": packaged, "reason": "legacy_unknown"})
            elif current != installed:
                if packaged != installed:
                    pending.append({"skill": source.name, "installed_sha256": current,
                                    "packaged_sha256": packaged, "reason": "locally_edited"})
            elif packaged != installed:
                for file in sorted(source.rglob("*")):
                    if not file.is_file():
                        continue
                    destination = target / file.relative_to(source)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_name(destination.name + ".tmp")
                    shutil.copyfile(file, temporary)
                    temporary.replace(destination)
                sidecar.write_text(packaged + "\n", encoding="utf-8")
        report = self.data / "skills-update-pending.json"
        if pending:
            atomic_json(report, pending)
        else:
            report.unlink(missing_ok=True)
        return pending

    def settings(self):
        settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
        settings.setdefault("default_execution_mode", "autonomous")
        settings.setdefault("reasoning_effort", "medium")
        return settings

    def save_settings(self, settings):
        atomic_json(self.settings_file, settings)

    def read_roots(self):
        return [self.workspace.resolve(), (self.data / "attachments").resolve()] + [
            Path(p).expanduser().resolve() for p in self.settings()["read_roots"]]


def _sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def default_data():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) if os.name == "nt" else Path.home()
    return base / ("Clara" if os.name == "nt" else ".clara")
