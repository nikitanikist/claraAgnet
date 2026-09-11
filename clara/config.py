"""Local application configuration. No model credentials are stored here."""
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
PROJECT = PACKAGE.parent


def atomic_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


@dataclass
class Config:
    data: Path
    port: int = 8876

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
                                "desktop_enabled": False, "max_budget_usd": None})
        for source in (PACKAGE / "starter_skills").glob("*"):
            target = self.skills / source.name
            if source.is_dir() and not target.exists():
                shutil.copytree(source, target)
        (self.workspace / "outputs").mkdir(exist_ok=True)

    def settings(self):
        return json.loads(self.settings_file.read_text(encoding="utf-8"))

    def save_settings(self, settings):
        atomic_json(self.settings_file, settings)

    def read_roots(self):
        return [self.workspace.resolve(), (self.data / "attachments").resolve()] + [
            Path(p).expanduser().resolve() for p in self.settings()["read_roots"]]


def default_data():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) if os.name == "nt" else Path.home()
    return base / ("Clara" if os.name == "nt" else ".clara")
