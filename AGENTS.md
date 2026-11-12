# Omarchy Projects

Keep this a small customization layer for Omarchy 4.5+, not another desktop shell.

- Runtime dependencies are limited to software already shipped with Omarchy:
  Hyprland Lua, Quickshell, and Python's standard library. Do not add packages.
- Keep Omarchy's workspace controller and monitor identity mapping intact. Never
  hardcode workspace blocks, replace its reconciler, or edit packaged files.
- User project names and monitor choices belong in the user's config, not this repo.
- Preserve unrelated configuration and symlinks in installation and removal.
- Run `python3 -m unittest discover -s tests` and `lua tests/controller_test.lua`.
- Desktop checks may switch project views, but move only disposable test windows.
- Publishing this repository does not authorize publishing desktop captures or
  personal configuration. Use synthetic fixtures for public screenshots.

