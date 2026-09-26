import os
import sys
from pathlib import Path

import uvicorn


def _load_dotenv(path: Path) -> None:
    """server/.env (gitignored): KEY=VALUE lines; real env vars win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip().removeprefix("export "), v.strip().strip('"').strip("'"))


if __name__ == "__main__":
    _load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from pop.main import create_app
    try:
        app = create_app()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    uvicorn.run(app, host=os.environ.get("POP_HOST", "0.0.0.0"), port=int(os.environ.get("POP_PORT", "8000")))
