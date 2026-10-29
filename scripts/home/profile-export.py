"""Export a validated schema-3 profile without cloud-init media."""
from pathlib import Path
import sys

from seed import main

if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("Run the profile-export flake app to export a profile")
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:], profile_only=True))
