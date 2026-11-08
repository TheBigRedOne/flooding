"""Exit 0 only when the Baseline smoke evidence is complete."""

import sys

import smoke_validate


def main() -> None:
    results = sys.argv[1]
    errors = smoke_validate.check_baseline(results)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        sys.exit(1)
    print("PASS: baseline smoke")


if __name__ == "__main__":
    main()
