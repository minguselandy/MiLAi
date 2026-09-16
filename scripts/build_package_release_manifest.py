from __future__ import annotations

from pathlib import Path

from milai.operations.packaging import build_package_release_manifest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "integrations/package-release-manifest.json"


def main() -> None:
    build_package_release_manifest(ROOT, OUTPUT)


if __name__ == "__main__":
    main()
