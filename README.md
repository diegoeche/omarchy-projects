# Omarchy Projects

**One project name. One shortcut. Every monitor switches together.**

A small layer over Omarchy 4.5's existing per-monitor workspaces. Each project
uses the same local slot on every participating monitor. `Super+2` brings up
Boreal on both displays; moving a window to Atlas keeps it on its physical screen.

```text
                 Left screen             Right screen
1 Atlas          Atlas editor            Atlas browser
2 Boreal         Boreal terminal         Boreal docs
3 Personal       Personal windows        Personal windows
```

The bar shows the project names on every screen, highlights the project only
when the monitors agree, and dims empty projects. Existing occupied workspaces
outside the configured projects remain clickable as `WS N`.

## What it contains

- A Lua module loaded by Hyprland, using `o.workspaces.focus`,
  `move_window`, and `workspace_id` from Omarchy.
- A small native Omarchy bar widget, using the existing shell and theme.
- A CLI and installer using Python's standard library.
- Optional project themes and wallpapers, applied through Omarchy's own commands.

**No package installation, third-party Python libraries, daemon, service, or
polling loop.** Python 3, Hyprland Lua, and Quickshell are already part of a
standard Omarchy installation. The controller uses short one-shot event timers;
the widget watches a local state file and compositor events. Appearance changes
run in a short-lived serialized worker, not a resident background process.

This does not replace Omarchy's workspace reconciler, renumber workspaces,
configure displays, or modify packaged Omarchy files.

## Install

Requires Omarchy **4.5+**, Hyprland **0.56.2+** with Lua configuration, Python
**3.10+**, and the stock Omarchy shell for the optional bar widget.

```sh
git clone https://github.com/diegoeche/omarchy-projects.git
cd omarchy-projects
python3 scripts/install.py
```

The installer adds one marked loader block to `~/.config/hypr/hyprland.lua`,
replaces the workspace widget's bar entry with Projects, and validates Hyprland
after reloading. Changed files are backed up; dotfile symlinks are preserved.
If validation fails, the installation rolls back.

If the bar has not rediscovered the local widget automatically, run:

```sh
omarchy restart shell
```

Use `--no-bar` to keep your current bar. To install your own config initially:

```sh
python3 scripts/install.py --config /path/to/private-projects.json
```

## Configure names and slots

Edit `~/.config/omarchy-projects/projects.json`:

```json
{
  "version": 1,
  "projects": [
    { "id": "atlas", "name": "Atlas", "slot": 1 },
    { "id": "boreal", "name": "Boreal", "slot": 2 },
    { "id": "personal", "name": "Personal", "slot": 3 }
  ],
  "monitors": [],
  "follow_focus": true
}
```

Then run:

```sh
omarchy-projects reload
```

- `id` is the stable CLI identifier; `name` is the visible label. Renaming a
  project leaves its windows where they are.
- `slot` is Omarchy's monitor-local workspace slot, 1–10. Slots must be unique.
  Slot 10 uses the `0` key. Config order determines next/previous navigation.
- An empty `monitors` list includes every active independent display. To select
  displays explicitly, use output names or `desc:` selectors, for example
  `["desc:My Main Display", "HDMI-A-1"]`. Mirrored outputs are excluded.
- `follow_focus: true` synchronizes the other monitors when an app launcher or
  another shortcut focuses a configured project's workspace. Set it to `false`
  to synchronize only through project shortcuts and CLI commands.

Omarchy owns the underlying IDs and persistent monitor identities. A project's
slot may map to IDs 1 and 11 today, and another saved block after reconnecting.
The layer asks Omarchy for the mapping rather than assuming those numbers.

Changing a slot assigns that name to a different existing workspace; it does
not migrate windows. Keep slots stable and change names freely.

## Shortcuts

| Keys | Action |
| --- | --- |
| `Super+number` | Switch all participating monitors to that project |
| `Super+Shift+number` | Move the window to the project on its current screen, then switch all screens |
| `Super+Shift+Alt+number` | Send the window to the project without switching |
| `Super+Tab` / `Super+Shift+Tab` | Next / previous project, wrapping in config order |
| `Super+Ctrl+Tab` | Return to the former project |
| `Super+scroll` | Next / previous project |
| `Super+Shift+Ctrl+Arrow` | Move the window to a neighboring monitor within the same project |

Switching projects finishes on the monitor you were using. The numbered
shortcuts replace stock bindings only for configured slots; other number keys
remain available. Window focus, window swaps, layouts, scratchpad, and normal
monitor-focus shortcuts continue to use Omarchy.

The stock `Super+Shift+Alt+Arrow` whole-workspace moves are unbound while the
layer is enabled: moving a raw workspace would change its project association.
The installer loads this module after personal bindings, so the shortcuts in
the table take precedence. Removal restores the original config's bindings.

## CLI

```sh
omarchy-projects list
omarchy-projects switch boreal       # a slot number also works
omarchy-projects next
omarchy-projects prev
omarchy-projects back
omarchy-projects move atlas
omarchy-projects move atlas --silent
omarchy-projects monitor l
omarchy-projects status
omarchy-projects status --json
omarchy-projects check
```

The CLI runs only when invoked. Switching from a bar button or keybinding uses
the in-process Lua module directly. Project labels are rendered as plain text.

## Project themes and wallpapers

Right-click a project name to open its appearance menu. **Open Aether** switches
to that project and opens the existing Aether app. When the look is ready,
right-click the project again and choose **Save current theme and wallpaper**.
This saves the installed theme's name and a durable copy of the wallpaper.

Switching projects then restores the saved wallpaper and palette. Aether edits
are not undone by its compositor reloads: saving is explicit, so you can finish
configuring a look before replacing the project's previous setting.

The same operations are available from the CLI:

```sh
omarchy-projects appearance menu atlas
omarchy-projects appearance save           # current project
omarchy-projects appearance save atlas    # Atlas must be focused
omarchy-projects appearance set atlas --theme catppuccin --wallpaper ~/Pictures/atlas.png
```

Or add an optional `appearance` field to a project in `projects.json`, then run
`omarchy-projects reload`:

```json
{
  "id": "atlas",
  "name": "Atlas",
  "slot": 1,
  "appearance": {
    "theme": "catppuccin",
    "wallpaper": "~/Pictures/atlas.png"
  }
}
```

Theme slugs must name installed Omarchy themes; wallpapers are local files.
Profiles are independent even when they initially use the same theme. Projects
without an appearance setting leave the current look in place.

Workspace navigation remains immediate. Appearance changes are debounced and
serialized, with rapid switching converging on the latest project. Switching
between projects with the same palette only changes the wallpaper. Failed
background/theme commands are recorded in
`~/.local/state/omarchy-projects/appearance.log`.

Omarchy themes are global: the active project's palette applies to the bar,
terminals, and other themed applications, including windows on hidden projects.
The next project switch restores its assigned look. Aether is optional; themes
and wallpaper paths can be configured directly without installing it.

## Hotplug and current limits

This is primarily for fixed multi-monitor project workflows. Omarchy continues
to handle unplugging, merging, and restoring monitor workspaces. With a single
display connected, project switching still works on that display. Refreshing
the bar's mapping after hotplug never moves windows from a monitor teardown
callback.

Omarchy may renumber a disconnected display's workspaces into spare slots on
the surviving display. Those displaced windows follow **stock Omarchy behavior**;
this layer does not merge them into matching projects. They remain reachable
through the extra `WS N` buttons. Switching projects after reconnecting uses
Omarchy's current mapping.

There are at most ten projects, matching Omarchy's ten slots per monitor.
Project history survives the compositor reloads triggered by theme changes.
App launch recipes, saved layouts, and Slack instances are outside this version.

## Update and remove

```sh
git pull
python3 scripts/install.py

# Remove later:
python3 scripts/install.py --uninstall
```

Removal deletes the marked loader and installed runtime files, restores the
previous workspace bar entries, and keeps unrelated edits made since installation.
Your project config and backups remain. Restart the shell if it still displays
the old widget.

Configuration follows `XDG_CONFIG_HOME`; runtime files follow `XDG_DATA_HOME`
and `XDG_STATE_HOME`. The executable is installed in `~/.local/bin`. For an
offline packaging check, use `--home /tmp/a-disposable-home --no-reload` with a
fixture Hyprland and shell configuration.

## Development

```sh
python3 -m unittest discover -s tests -v
lua tests/controller_test.lua
luac -p hypr/controller.lua
```

Tests use isolated files and a fake compositor. They cover changing monitor
blocks, rapid switching, silent/following moves, external focus, hotplug
deferral, Unicode/markup labels, CLI errors, rollback, and symlink-preserving
installation/removal. Native desktop verification is documented in [QA.md](QA.md).

MIT licensed. Inspired by the linked-workspace workflows discussed in
[Omarchy discussion #8785](https://github.com/omacom/omarchy/discussions/8785).
Implementation is original and uses Omarchy's current helper API.
