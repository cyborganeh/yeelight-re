"""Entry point used by PyInstaller when building the windowed GUI executable."""

from yeelight_re.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
