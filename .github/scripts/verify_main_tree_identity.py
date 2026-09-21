#!/usr/bin/env python3
"""Verify that a main-push tree is identical to its merged pull-request head tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import urllib.request

GIT = shutil.which("git")
if GIT is None:
    raise RuntimeError("git executable is required")


def _git(*args: str) -> str:
    return subprocess.check_output((GIT, *args), text=True).strip()  # noqa: S603


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    args = parser.parse_args()
    if not args.repository or not args.sha:
        parser.error("--repository and --sha are required")

    request = urllib.request.Request(
        f"https://api.github.com/repos/{args.repository}/commits/{args.sha}/pulls",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request) as response:  # noqa: S310 -- fixed GitHub API origin
        pulls = json.load(response)
    merged = [
        pull
        for pull in pulls
        if pull.get("merged_at") and pull.get("base", {}).get("ref") == "main"
    ]
    if not merged:
        raise SystemExit(f"no merged pull request is associated with main commit {args.sha}")
    head_sha = merged[0]["head"]["sha"]
    subprocess.run(  # noqa: S603 -- SHA comes from the authenticated GitHub API.
        (GIT, "fetch", "--no-tags", "origin", head_sha), check=True
    )
    main_tree = _git("rev-parse", f"{args.sha}^{{tree}}")
    candidate_tree = _git("rev-parse", f"{head_sha}^{{tree}}")
    if main_tree != candidate_tree:
        raise SystemExit(f"main tree {main_tree} differs from tested PR head tree {candidate_tree}")
    print(
        json.dumps(
            {
                "main_sha": args.sha,
                "main_tree": main_tree,
                "pull_request": merged[0]["number"],
                "tested_head_sha": head_sha,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
