#!/usr/bin/env bash
set -euo pipefail

DEFAULT_REPO="ub-cavas/UB-DigitalTwin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILDS_DIR="${ROOT_DIR}/CARLA/Builds"
TAG="latest"

usage() {
    cat <<EOF
Usage: $(basename "$0") [TAG]
       $(basename "$0") --tag TAG

Downloads the zip linked from the GitHub Release description's Google Drive
link and extracts it into CARLA/Builds/<tag>.

Options:
  -t, --tag TAG     Download using a specific release tag instead of latest.
  -h, --help        Show this help message.
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -t|--tag)
            [ "$#" -ge 2 ] || die "$1 requires a tag value."
            TAG="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            die "Unknown option: $1"
            ;;
        *)
            [ "$TAG" = "latest" ] || die "Only one tag may be specified."
            TAG="$1"
            shift
            ;;
    esac
done

require_cmd curl
require_cmd python3
require_cmd unzip

repo_from_git() {
    local remote
    remote="$(git -C "${ROOT_DIR}" remote get-url origin 2>/dev/null || true)"
    if [ -z "$remote" ]; then
        return 1
    fi

    python3 - "$remote" <<'PY'
import re
import sys

remote = sys.argv[1].strip()
patterns = (
    r"github\.com[:/]([^/]+)/([^/.]+)(?:\.git)?$",
    r"github\.com/([^/]+)/([^/.]+)(?:\.git)?$",
)

for pattern in patterns:
    match = re.search(pattern, remote)
    if match:
        print(f"{match.group(1)}/{match.group(2)}")
        sys.exit(0)

sys.exit(1)
PY
}

extract_release_data() {
    python3 - "$1" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    release = json.load(handle)

tag_name = release.get("tag_name") or ""
body = release.get("body") or ""
urls = re.findall(r"https?://[^\s<>\"')\]]+", body)
drive_urls = [
    url.rstrip(".,;")
    for url in urls
    if "drive.google.com" in url or "docs.google.com" in url
]

if not tag_name:
    print("ERROR: Release response did not include tag_name.", file=sys.stderr)
    sys.exit(2)

if not drive_urls:
    print("ERROR: No Google Drive link found in release description.", file=sys.stderr)
    sys.exit(3)

print(tag_name)
print(drive_urls[0])
PY
}

drive_file_id() {
    python3 - "$1" <<'PY'
import re
import sys
from urllib.parse import parse_qs, urlparse

url = sys.argv[1]
parsed = urlparse(url)
query = parse_qs(parsed.query)

for key in ("id", "fileid"):
    if query.get(key):
        print(query[key][0])
        sys.exit(0)

match = re.search(r"/(?:file/)?d/([^/?#]+)", parsed.path)
if match:
    print(match.group(1))
    sys.exit(0)

print(f"ERROR: Could not extract a Google Drive file id from: {url}", file=sys.stderr)
sys.exit(1)
PY
}

download_with_curl() {
    local file_id="$1"
    local output="$2"
    local cookie_file="$3"
    local first_response="${output}.response"
    local confirm_url

    curl -fL --progress-bar -c "$cookie_file" \
        "https://drive.google.com/uc?export=download&id=${file_id}" \
        -o "$first_response"

    if unzip -tq "$first_response" >/dev/null 2>&1; then
        mv "$first_response" "$output"
        return 0
    fi

    confirm_url="$(
        python3 - "$first_response" "$file_id" <<'PY'
import html
import re
import sys
from urllib.parse import urlencode, urljoin

path, file_id = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8", errors="ignore").read()

hrefs = re.findall(r'href="([^"]+)"', text)
for href in hrefs:
    href = html.unescape(href)
    if "confirm=" in href and ("id=" in href or file_id in href):
        print(urljoin("https://drive.google.com", href))
        sys.exit(0)

confirm_match = re.search(r'name="confirm"\s+value="([^"]+)"', text)
uuid_match = re.search(r'name="uuid"\s+value="([^"]+)"', text)

if confirm_match:
    params = {
        "export": "download",
        "id": file_id,
        "confirm": html.unescape(confirm_match.group(1)),
    }
    if uuid_match:
        params["uuid"] = html.unescape(uuid_match.group(1))
    print("https://drive.usercontent.google.com/download?" + urlencode(params))
    sys.exit(0)

sys.exit(1)
PY
    )" || die "Google Drive did not return a zip file or a downloadable confirmation page."

    curl -fL --progress-bar -b "$cookie_file" -c "$cookie_file" \
        "$confirm_url" \
        -o "$output"
    rm -f "$first_response"
}

download_from_drive() {
    local drive_url="$1"
    local output="$2"
    local cookie_file="$3"

    if command -v gdown >/dev/null 2>&1; then
        gdown --fuzzy "$drive_url" -O "$output"
    else
        local file_id
        file_id="$(drive_file_id "$drive_url")"
        download_with_curl "$file_id" "$output" "$cookie_file"
    fi
}

install_release() {
    local zip_file="$1"
    local tag_name="$2"
    local extract_dir="$3"
    local target_dir="${BUILDS_DIR}/${tag_name}"

    case "$tag_name" in
        ""|*/*)
            die "Release tag '${tag_name}' cannot be used as a single folder name."
            ;;
    esac

    if [ -e "$target_dir" ]; then
        die "Release folder already exists: ${target_dir}"
    fi

    mkdir -p "$BUILDS_DIR" "$extract_dir"
    unzip -q "$zip_file" -d "$extract_dir"

    shopt -s dotglob nullglob
    local extracted_items=("${extract_dir}"/*)
    shopt -u dotglob nullglob

    if [ "${#extracted_items[@]}" -eq 0 ]; then
        die "Zip archive did not contain any files."
    fi

    if [ "${#extracted_items[@]}" -eq 1 ] && [ -d "${extracted_items[0]}" ]; then
        mv "${extracted_items[0]}" "$target_dir"
    else
        mkdir "$target_dir"
        mv "${extracted_items[@]}" "$target_dir"/
    fi
}

REPO="$(repo_from_git || printf '%s\n' "$DEFAULT_REPO")"
if [ "$TAG" = "latest" ]; then
    API_URL="https://api.github.com/repos/${REPO}/releases/latest"
else
    API_URL="https://api.github.com/repos/${REPO}/releases/tags/${TAG}"
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

RELEASE_JSON="${TMP_DIR}/release.json"
ZIP_FILE="${TMP_DIR}/ub-digital-twin.zip"
COOKIE_FILE="${TMP_DIR}/drive-cookies.txt"
EXTRACT_DIR="${TMP_DIR}/extract"

echo "=== UB Digital Twin CARLA Downloader ==="
echo "Repository: ${REPO}"
echo "Release: ${TAG}"

curl -fsSL "$API_URL" -o "$RELEASE_JSON"
RELEASE_DATA_TEXT="$(extract_release_data "$RELEASE_JSON")"
mapfile -t RELEASE_DATA <<< "$RELEASE_DATA_TEXT"

RESOLVED_TAG="${RELEASE_DATA[0]}"
DRIVE_URL="${RELEASE_DATA[1]}"

echo "Found release: ${RESOLVED_TAG}"
echo "Found Google Drive link: ${DRIVE_URL}"

case "$RESOLVED_TAG" in
    ""|*/*)
        die "Release tag '${RESOLVED_TAG}' cannot be used as a single folder name."
        ;;
esac

if [ -e "${BUILDS_DIR}/${RESOLVED_TAG}" ]; then
    die "Release folder already exists: ${BUILDS_DIR}/${RESOLVED_TAG}"
fi

echo "Downloading release zip..."

download_from_drive "$DRIVE_URL" "$ZIP_FILE" "$COOKIE_FILE"

unzip -tq "$ZIP_FILE" >/dev/null || die "Downloaded file is not a valid zip archive."

echo "Extracting into: ${BUILDS_DIR}/${RESOLVED_TAG}"
install_release "$ZIP_FILE" "$RESOLVED_TAG" "$EXTRACT_DIR"

echo "Done. Release extracted to: ${BUILDS_DIR}/${RESOLVED_TAG}"
