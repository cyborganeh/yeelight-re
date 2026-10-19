"""Entry point used by PyInstaller when building the Windows executable."""

from yeelight_re.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
