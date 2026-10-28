import sys

from app.config import Settings
from app.db import generate_codes, init_db, write_codes_csv


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    settings = Settings.from_env()
    init_db(settings)
    created = generate_codes(settings, count)
    path = write_codes_csv(settings)
    print("\n".join(created))
    print(f"Wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
