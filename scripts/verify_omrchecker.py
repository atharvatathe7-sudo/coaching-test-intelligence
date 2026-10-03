"""
Check that the vendored OMRChecker is exactly the audited upstream commit.

    python scripts/verify_omrchecker.py
        compares third_party/omrchecker with its manifest (offline)

    python scripts/verify_omrchecker.py --upstream <path to an OMRChecker clone>
        also compares the manifest with `git ls-tree -r <commit>` in that
        clone, i.e. with upstream itself
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.omr import vendor  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--upstream", help="path to a clone of Udayraj123/OMRChecker")
    args = parser.parse_args()

    problems = vendor.verify_vendored()

    if args.upstream:
        result = subprocess.run(
            ["git", "-C", args.upstream, "ls-tree", "-r", vendor.EXPECTED_COMMIT],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            problems.append("could not read the pinned commit from the clone")
        else:
            upstream = {
                line.split("\t")[1]: line.split()[2]
                for line in result.stdout.splitlines()
            }
            for name, blob in vendor.load_manifest()["files"].items():
                if upstream.get(name) != blob:
                    problems.append(f"differs from upstream: {name}")

    if problems:
        print("NOT the audited OMRChecker:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    manifest = vendor.load_manifest()
    print(
        f"OK: {len(manifest['files'])} files match upstream "
        f"{manifest['commit'][:7]} ({manifest['license']})."
        + (" Compared with upstream." if args.upstream else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
