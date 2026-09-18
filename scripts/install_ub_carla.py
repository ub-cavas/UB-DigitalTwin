#!/usr/bin/env python3
"""Install matching CARLA and Autoware map releases from public Drive folders."""

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
import zipfile

ROOT = Path(__file__).resolve().parent.parent
CARLA_FOLDER = "1dCVDd7S98pTDgj6CzOwHFzPWFqo9Gcrv"
MAPS_FOLDER = "1sGHwToKv8zCPXMBhPDRDJAsTEKW5T0Uy"
FOLDER_MIME = "application/vnd.google-apps.folder"
MAP_FILES = ("lanelet2_map.osm", "pointcloud_map.pcd", "map_projector_info.yaml")
CARLA_FILES = ("CarlaUE4.sh", "CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping")
CARLA_REQUIRED = CARLA_FILES + ("PythonAPI/carla/dist/carla-*-cp310-*.whl",)


class InstallError(Exception):
    pass


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime: str
    size: int | None = None


def normalize_version(value):
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise argparse.ArgumentTypeError("Use a version such as v1.1.0 or 1.1.0.")
    return value if value.startswith("v") else "v" + value


def parse_folder(page):
    # Public Drive pages embed their direct children as escaped JSON. Fail
    # explicitly if Google changes this format, rather than guess file IDs.
    match = re.search(r"window\['_DRIVE_ivd'\]\s*=\s*'((?:\\.|[^'\\])*)';", page)
    if not match:
        raise InstallError("Cannot read public Drive folder listing. Check sharing and try again.")
    payload = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m[1], 16)), match[1])
    try:
        rows = json.loads(payload)[0] or []
        entries = [DriveFile(row[0], row[2], row[3], row[13]) for row in rows]
    except (ValueError, IndexError, TypeError) as exc:
        raise InstallError("Google Drive folder listing format was not recognized.") from exc
    # The public page can truncate large folders; do not select a potentially
    # ambiguous version from an incomplete listing.
    if len(entries) >= 50:
        raise InstallError("Drive folder may be truncated (50+ entries); split or archive older releases.")
    return entries


class ConfirmationForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}
        self.inside = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "download-form":
            self.action = attrs.get("action")
            self.inside = True
        elif tag == "input" and self.inside and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.inside = False

    def url(self):
        parsed = urlparse(self.action or "")
        if parsed.scheme != "https" or parsed.hostname not in {
            "drive.google.com", "drive.usercontent.google.com"
        }:
            raise InstallError("Drive did not return a download. The upload may be incomplete or download quota exceeded.")
        return self.action + "?" + urlencode(self.fields)


class PublicDrive:
    def __init__(self):
        # Only anonymous cookies obtained during these public requests are used.
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def open(self, url):
        return self.opener.open(Request(url, headers={"User-Agent": "UB-DigitalTwin-Installer/1.0"}), timeout=60)

    def list_folder(self, folder_id):
        with self.open(f"https://drive.google.com/drive/folders/{folder_id}") as response:
            return parse_folder(response.read().decode("utf-8"))

    def download(self, item, destination):
        url = "https://drive.google.com/uc?" + urlencode({"export": "download", "id": item.id})
        for _ in range(3):
            with self.open(url) as response:
                if "text/html" in response.headers.get("Content-Type", "").lower():
                    form = ConfirmationForm()
                    form.feed(response.read(2 * 1024 * 1024).decode("utf-8", errors="replace"))
                    url = form.url()
                    continue
                expected = response.headers.get("Content-Length")
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
            size = destination.stat().st_size
            if not size or (item.size is not None and size != int(item.size)) or (expected and size != int(expected)):
                raise InstallError(f"Incomplete download: {item.name}. Retry after the upload finishes.")
            with destination.open("rb") as downloaded:
                prefix = downloaded.read(256).lstrip().lower()
            if prefix.startswith((b"<!doctype html", b"<html")):
                raise InstallError(f"Drive returned an HTML page instead of {item.name}.")
            return
        raise InstallError(f"Could not confirm the public download of {item.name}; retry later.")


def unique_match(entries, names, label, folder=False):
    matches = [entry for entry in entries if entry.name in names and (entry.mime == FOLDER_MIME) == folder]
    if not matches:
        raise InstallError(f"{label} not found in public Drive folder. Expected {', '.join(names)}. "
                           "The upload may still be in progress; rerun the same command when it finishes.")
    if len(matches) != 1:
        raise InstallError(f"Multiple matches for {label}; keep one release with that version in Drive.")
    return matches[0]


def resolve_build(drive, version):
    return [unique_match(drive.list_folder(CARLA_FOLDER),
                         (f"UB-CARLA-{version}.zip", f"{version}.zip"), f"CARLA {version}")]


def resolve_maps(drive, version):
    folder = unique_match(drive.list_folder(MAPS_FOLDER), (version,), f"Autoware maps {version}", folder=True)
    entries = drive.list_folder(folder.id)
    return [unique_match(entries, (name,), f"Autoware maps {version}: {name}") for name in MAP_FILES]


def is_complete(path, required):
    return all(any(p.is_file() and p.stat().st_size > 0 for p in path.glob(name)) for name in required)


def destination_ready(path, required):
    if is_complete(path, required):
        return True
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise InstallError(f"Incomplete installation already exists at {path}. "
                           "Move it aside or complete it manually before retrying; existing files will not be overwritten.")
    return False


def extract_build(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        links = {}
        seen = set()
        # Packaged CARLA includes relative shared-library symlinks. Validate
        # them first and create them only after all regular files are extracted.
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise InstallError(f"Unsafe archive path: {member.filename}")
            if path in seen:
                raise InstallError(f"Duplicate archive path: {member.filename}")
            seen.add(path)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK):
                raise InstallError(f"Unsupported archive file type: {member.filename}")
            if kind == stat.S_IFLNK:
                if member.file_size > 4096:
                    raise InstallError(f"Invalid archive symlink: {member.filename}")
                target = bundle.read(member).decode("utf-8")
                resolved = (destination / path.parent / target).resolve()
                if not target or "\\" in target or Path(target).is_absolute() or not resolved.is_relative_to(destination.resolve()):
                    raise InstallError(f"Unsafe archive symlink: {member.filename}")
                links[path] = target
        for path in seen:
            if any(parent in links for parent in path.parents):
                raise InstallError(f"Archive entry is nested under a symlink: {path}")
        for member in members:
            if PurePosixPath(member.filename) in links:
                continue
            extracted = Path(bundle.extract(member, destination))
            if not member.is_dir():
                mode = (member.external_attr >> 16) & 0o777
                if mode:
                    extracted.chmod(mode)
        for path, target in links.items():
            link = destination / path
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
    # Accept a flat archive or wrapper folders, without adding nesting at the
    # final install location. Require exactly one actual packaged CARLA build.
    candidates = [p.parent for p in destination.rglob("CarlaUE4.sh") if is_complete(p.parent, CARLA_FILES)]
    if len(candidates) != 1:
        raise InstallError("Archive must contain exactly one packaged CARLA build with CarlaUE4.sh and its Linux binary.")
    build = candidates[0]
    for path in links:
        link = destination / path
        if link.is_relative_to(build) and not link.resolve().is_relative_to(build.resolve()):
            raise InstallError(f"Symlink points outside the packaged CARLA build: {path}")
    wheels = list((build / "PythonAPI/carla/dist").glob("carla-*-cp310-*.whl"))
    if not any(p.stat().st_size > 0 for p in wheels):
        raise InstallError("CARLA archive is missing the Python 3.10 wheel required by the launchers.")
    for name in CARLA_FILES:
        path = build / name
        path.chmod(path.stat().st_mode | 0o111)
    return build


def install(version, maps_only=False, check=False, root=ROOT, drive=None):
    components = []
    if not maps_only:
        components.append(("CARLA", root / "CARLA/Builds" / version, CARLA_REQUIRED, resolve_build))
    components.append(("Autoware maps", root / "Autoware/host_data/maps/ub_autonomous_proving_grounds" / version,
                       MAP_FILES, resolve_maps))
    pending = []
    for label, destination, required, resolve in components:
        if not check and destination_ready(destination, required):
            print(f"{label} {version} already installed: {destination}")
        else:
            pending.append((label, destination, required, resolve))
    if not pending:
        return
    drive = drive or PublicDrive()
    # Resolve every missing component first, before downloading large archives
    # or installing anything. A missing upload never selects another version.
    sources = []
    errors = []
    for label, destination, required, resolve in pending:
        try:
            files = resolve(drive, version)
            sources.append((label, destination, required, files))
            print(f"{label} {version}: {', '.join(item.name for item in files)} -> {destination}")
        except InstallError as exc:
            errors.append(str(exc))
    if errors:
        raise InstallError("\n".join(errors))
    if check:
        print("Public release files found. No files downloaded or installed.")
        return
    with ExitStack() as stack:
        staged = []
        for label, destination, required, files in sources:
            destination.parent.mkdir(parents=True, exist_ok=True)
            work = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix=f".{version}-", dir=destination.parent)))
            payload = work / "payload"
            payload.mkdir()
            if label == "CARLA":
                archive = work / "build.zip"
                print(f"Downloading {files[0].name}...", flush=True)
                drive.download(files[0], archive)
                print("Extracting CARLA...", flush=True)
                payload = extract_build(archive, payload)
                archive.unlink()
            else:
                for item in files:
                    print(f"Downloading {version}/{item.name}...", flush=True)
                    drive.download(item, payload / item.name)
            if not is_complete(payload, required):
                raise InstallError(f"Downloaded {label} {version} is incomplete.")
            staged.append((label, destination, required, payload))
        # Check destinations again after lengthy downloads, before publishing.
        for _, destination, required, _ in staged:
            if destination_ready(destination, required):
                raise InstallError(f"Installation appeared during download: {destination}. Rerun to reuse it.")
        for label, destination, _, payload in staged:
            # rename is atomic on the same filesystem and can replace an empty
            # placeholder directory, but cannot overwrite a populated directory.
            payload.rename(destination)
            print(f"Installed {label} {version}: {destination}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download a matching CARLA build and Autoware maps from public Google Drive folders; no login required.")
    parser.add_argument("version", nargs="?", type=normalize_version, help="Release version, e.g. v1.1.0 or 1.1.0 (default: BUILD_FOLDER or v1.1.0)")
    parser.add_argument("-t", "--tag", "--version", dest="tag", type=normalize_version, help="Alias for the positional version")
    parser.add_argument("--maps-only", action="store_true", help="Install only the matching Autoware maps")
    parser.add_argument("--check", action="store_true", help="Check public release availability without downloading or installing")
    args = parser.parse_args(argv)
    if args.version and args.tag:
        parser.error("Specify the version only once.")
    try:
        version = args.version or args.tag or normalize_version(os.environ.get("BUILD_FOLDER") or "v1.1.0")
        install(version, args.maps_only, args.check)
    except (InstallError, OSError, ValueError, zipfile.BadZipFile, argparse.ArgumentTypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
