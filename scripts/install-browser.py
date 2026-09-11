"""Install the pinned Chrome connector; Windows Node stays inside Clara's folder."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
NODE_VERSION = "22.22.3"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-win-x64.zip"
NODE_SHA256 = "6c8d54f635feff4df76c2ca80f45332eb2ff57d25226edce36592e51a177ee33"


def supported(node):
    try:
        version = subprocess.check_output([str(node), "--version"], text=True, timeout=15).strip().lstrip("v")
        major, minor, *_ = map(int, version.split('.'))
        return (major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major >= 23
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def npm_cli(node):
    candidates=[node.parent/'node_modules/npm/bin/npm-cli.js',node.parent.parent/'lib/node_modules/npm/bin/npm-cli.js']
    return next((p for p in candidates if p.is_file()),candidates[0])


def unpack_node(data, destination):
    if hashlib.sha256(data).hexdigest() != NODE_SHA256:
        raise ValueError("Node.js checksum did not match the pinned official Windows release.")
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            path = Path(entry.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or ':' in entry.filename:
                raise ValueError("Unsafe path in Node.js archive.")
        archive.extractall(destination)
    return destination / f"node-v{NODE_VERSION}-win-x64"


def node_runtime():
    local = ROOT / '.portable-node' / 'node.exe'
    if local.is_file() and supported(local):
        return local
    external = shutil.which('node')
    if external and supported(external) and npm_cli(Path(external)).is_file():
        return Path(external)
    if os.name != 'nt':
        raise ValueError('Install a supported Node.js version with npm first (22.12+ recommended).')
    target = ROOT / '.portable-node'
    if target.exists() and not (target / '.clara-owned').is_file():
        raise ValueError('The .portable-node folder is not owned by this installer. Choose a clean Clara folder.')
    print('Downloading the pinned Node.js runtime from nodejs.org...', flush=True)
    with urllib.request.urlopen(NODE_URL, timeout=60) as response:
        data = response.read(60_000_001)
    if len(data) > 60_000_000:
        raise ValueError('Node.js archive exceeded the expected download bound.')
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        extracted = unpack_node(data, Path(temporary))
        if not supported(extracted / 'node.exe'):
            raise ValueError('Downloaded Node.js failed its version check.')
        (extracted / '.clara-owned').write_text(NODE_VERSION)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(extracted), target)
    return local


def install():
    node = node_runtime()
    npm = npm_cli(node)
    env = dict(os.environ, PATH=str(node.parent) + os.pathsep + os.environ.get('PATH', ''))
    subprocess.run([str(node), str(npm), 'ci', '--ignore-scripts', '--no-fund', '--no-audit'], cwd=ROOT, env=env, check=True)
    connector = ROOT / 'node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js'
    subprocess.run([str(node), str(connector), '--help'], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL, timeout=30)
    result = {'installed': True, 'node': str(node), 'connector': 'chrome-devtools-mcp',
              'message': 'Browser connector installed. Open Connections in Clara, enable Chrome and run the browser test.'}
    (ROOT / 'browser-setup-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(install(), indent=2))
