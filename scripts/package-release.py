"""Package only reviewable source. Never include runtime data or account state."""
import hashlib
import json
import re
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRECTORIES = ('clara', 'docs', 'scripts', 'tests')
TOP_LEVEL = ('README.md', 'START-HERE.md', 'pyproject.toml', 'requirements.lock',
    'requirements-dev.txt', 'requirements-windows-desktop.txt', 'package.json', 'package-lock.json',
    '.gitignore', 'Install-Clara.ps1', 'Install-FromGitHub.ps1', 'Start-Clara.ps1', 'Login-Clara.ps1', 'Open-Clara.ps1', 'Setup-Browser.ps1', 'Update-Clara.ps1',
    'Start-Clara.command', 'Login-Clara.command', 'Open-Clara.command')
EXCLUDED = {'__pycache__', '.pytest_cache', '.venv', '.windows-venv', 'node_modules', '.git'}


def main():
    files = [ROOT / name for name in TOP_LEVEL]
    for directory in DIRECTORIES:
        files.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and not p.is_symlink()
                     and not any(part in EXCLUDED for part in p.relative_to(ROOT).parts)
                     and p.suffix not in {'.pyc', '.log'})
    files = sorted(set(files))
    manifest = []
    for file in files:
        data = file.read_bytes()
        if re.search(rb'(?:sk-ant-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)', data):
            raise RuntimeError(f'Refusing possible credential material: {file.name}')
        if (str(Path.home()) + '/').encode() in data:
            raise RuntimeError(f'Refusing developer-specific path: {file.name}')
        manifest.append({'path':str(file.relative_to(ROOT)), 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()})
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Expected a numeric release version')
    name = f'Clara-Agent-{version}'
    archive = out / f'{name}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for file in files:
            bundle.write(file, Path('Clara-Agent') / file.relative_to(ROOT))
        bundle.writestr('Clara-Agent/release-manifest.json', json.dumps(manifest, indent=2))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / f'{name}.sha256').write_text(digest + f'  {name}.zip\n')
    with zipfile.ZipFile(archive) as check:
        assert check.testzip() is None
    print(json.dumps({'archive':str(archive), 'files':len(files), 'bytes':archive.stat().st_size, 'sha256':digest}, indent=2))


if __name__ == '__main__':
    main()
