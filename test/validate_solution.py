"""Exit 0 only when the Solution smoke evidence is complete."""

import sys

import smoke_validate


def main() -> None:
    results = sys.argv[1]
    errors = smoke_validate.check_solution(results)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        sys.exit(1)
    print("PASS: solution smoke")


if __name__ == "__main__":
    main()
