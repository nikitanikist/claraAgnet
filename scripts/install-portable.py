"""Provision application-local dependencies using an existing Windows embeddable Python.

Run with the existing python.exe. Its files are only read. No MSI, elevation,
registry changes, new Python download, or change to Windows policy is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
PIP_URL = "https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl"
PIP_SHA256 = "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e"
OWNER = ".clara-runtime.json"
READY = ".clara-ready"


def run(argv, **kwargs):
    subprocess.run([str(arg) for arg in argv], check=True, **kwargs)


def prepare_runtime(source, destination, version):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("The new runtime must be separate from the existing Python folder.")
    tag = f"python{version[0]}{version[1]}"
    for name in ("python.exe", f"{tag}.dll", f"{tag}.zip", f"{tag}._pth"):
        if not (source / name).is_file() or (source / name).is_symlink():
            raise ValueError(f"Expected an embeddable Python folder; missing {name}.")
    if destination.exists():
        marker = destination / OWNER
        if not marker.is_file() or json.loads(marker.read_text()).get("owner") != "clara-portable":
            raise ValueError(f"Refusing to overwrite an unrelated folder: {destination}")
        saved = json.loads(marker.read_text())
        if saved.get("python") != list(version):
            raise ValueError("This folder uses another Python version. Extract Clara into a new folder.")
        return destination / "python.exe"

    destination.mkdir(parents=True)
    # Only interpreter files: no old application, packages, paths, or credentials.
    names = {"python.exe", "pythonw.exe", "python3.dll", f"{tag}.dll", f"{tag}.zip",
             "vcruntime140.dll", "vcruntime140_1.dll", "libcrypto-3.dll", "libssl-3.dll",
             "sqlite3.dll", "libffi-8.dll", "LICENSE.txt", "python.cat"}
    try:
        for file in source.iterdir():
            if file.is_file() and not file.is_symlink() and (file.name in names or file.suffix == ".pyd"):
                shutil.copy2(file, destination / file.name)
        (destination / "Lib/site-packages").mkdir(parents=True)
        # Replace stale paths in the COPY; enable its own site-packages and .pth
        # processing (needed for pywin32), plus Clara's source directory.
        (destination / f"{tag}._pth").write_text(
            f"{tag}.zip\n.\nLib/site-packages\n..\nimport site\n", encoding="utf-8")
        (destination / OWNER).write_text(json.dumps({"owner": "clara-portable", "python": list(version)}))
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination / "python.exe"


def extract_pip(wheel, destination):
    if hashlib.sha256(Path(wheel).read_bytes()).hexdigest() != PIP_SHA256:
        raise ValueError("The pip wheel checksum did not match the pinned release.")
    destination = Path(destination).resolve()
    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.infolist():
            output = (destination / entry.filename).resolve()
            if output != destination and destination not in output.parents:
                raise ValueError("Invalid path inside the pip wheel.")
        archive.extractall(destination)


def bootstrap_pip():
    tools = ROOT / ".install-tools"
    tools.mkdir(exist_ok=True)
    wheel = tools / "pip-26.2.1.whl"
    if not wheel.exists() or hashlib.sha256(wheel.read_bytes()).hexdigest() != PIP_SHA256:
        print("Downloading the pinned package installer from PyPI...", flush=True)
        with urllib.request.urlopen(PIP_URL, timeout=60) as response:
            wheel.write_bytes(response.read())
    extract_pip(wheel, tools / "pip")
    runner = tools / "run-pip.py"
    runner.write_text(
        "import sys, runpy\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent / 'pip'))\n"
        "runpy.run_module('pip', run_name='__main__')\n", encoding="utf-8")
    return runner


def provision(python, runner, requirements, probe):
    directory = python.parent
    fingerprint = hashlib.sha256(Path(requirements).read_bytes() + PIP_SHA256.encode()).hexdigest()
    marker = directory / READY
    try:
        current = json.loads(marker.read_text()).get('requirements_sha256') == fingerprint
    except (FileNotFoundError, ValueError, AttributeError):
        current = False
    marker.unlink(missing_ok=True)
    if current:
        print(f"Rechecking {directory.name}...", flush=True)
    else:
        # A failed attempt may leave partial packages only in this owned copy.
        # Retries rebuild that dependency directory, never the source runtime.
        packages = directory / "Lib/site-packages"
        shutil.rmtree(packages)
        packages.mkdir(parents=True)
        run([python, runner, "--isolated", "--disable-pip-version-check", "install",
             "--index-url", "https://pypi.org/simple", "--only-binary=:all:", "--no-compile",
             "--target", packages, "-r", requirements], cwd=ROOT)
    run([python, runner, "--isolated", "--disable-pip-version-check", "check"], cwd=ROOT)
    run([python, ROOT / "scripts/verify-portable.py", probe], cwd=ROOT)
    marker.write_text(json.dumps({'requirements_sha256': fingerprint, 'probe': probe}))


def install_browser(skip):
    if skip:
        return "Skipped; run Setup-Browser.ps1 when browser control is needed."
    run([sys.executable, ROOT / 'scripts/install-browser.py'], cwd=ROOT)
    return "Installed; browser actions still need testing."


def core_runtime(source,version):
    target=ROOT/'.portable-python'
    if source.resolve()==target.resolve():
        owner=target/OWNER
        if not owner.is_file() or json.loads(owner.read_text()).get('owner')!='clara-portable' or json.loads(owner.read_text()).get('python')!=list(version):
            raise ValueError('The current runtime is not a matching Clara-owned portable installation.')
        return target/'python.exe'
    return prepare_runtime(source,target,version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-desktop", action="store_true")
    parser.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args()
    if os.name != "nt" or sys.version_info < (3, 12) or struct.calcsize("P") != 8:
        raise SystemExit("Run this script with an existing 64-bit Windows embeddable Python 3.12 or newer.")
    source = Path(sys.executable).resolve().parent
    version = tuple(sys.version_info[:3])
    print(f"Existing runtime: {source}\nClara application: {ROOT}", flush=True)
    python = core_runtime(source,version)
    runner = bootstrap_pip()
    print("Installing Clara's core dependencies...", flush=True)
    provision(python, runner, ROOT / "requirements.lock", "core")

    failures = []
    desktop = "Skipped; desktop controls remain unavailable until installed."
    if not args.skip_desktop:
        try:
            print("Installing the separate Windows desktop dependencies...", flush=True)
            desktop_python = prepare_runtime(source, ROOT / ".portable-desktop", version)
            provision(desktop_python, runner, ROOT / "requirements-windows-desktop.txt", "desktop")
            desktop = "Installed; screenshots, clicks and RDP behavior still need testing."
        except Exception as error:
            desktop = f"FAILED: {error}"
            failures.append("desktop")
    try:
        browser = install_browser(args.skip_browser)
    except Exception as error:
        browser = f"FAILED: {error}"
        failures.append("browser")
    summary = {"core": "Installed; native login and live model task still need testing.",
               "desktop": desktop, "browser": browser}
    (ROOT / "portable-setup-result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nSETUP RESULT\n" + json.dumps(summary, indent=2), flush=True)
    print("\nNext, sign in using Login-Clara.ps1, then launch Start-Clara.ps1.", flush=True)
    if failures:
        raise SystemExit("Clara core is installed. Connector setup failed: " + ", ".join(failures))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"SETUP STOPPED: {error}\nKeep this output for diagnosis. Windows policy was not changed.")
