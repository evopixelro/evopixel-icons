from pathlib import Path

from evopixel_icons import main

if __name__ == "__main__":
    raise SystemExit(main(default_root=Path(__file__).resolve().parent.parent))
