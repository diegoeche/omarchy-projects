# Verification

## Automated

Run the commands in README.md. None of these tests modify the current desktop.

On an Omarchy machine, `python3 tests/qml_smoke.py` additionally loads the actual
widget and Omarchy UI components offscreen. It checks that labels exist and
markup is rendered as plain text, without opening a desktop window.

## Verified on 2026-11-12

- 13 Python tests and 13 controller behavior tests passed.
- Offscreen QML loading and literal markup labels passed against installed Omarchy.
- On a two-monitor Omarchy 4.5.0-3 / Hyprland 0.56.2 desktop, switching from either
  monitor synchronized both screens and preserved the focused monitor.
- Disposable Foot windows verified silent and following project moves, external
  focus synchronization, and movement between screens inside a project.
- Hyprland reported no configuration errors after installation and the checks.
- Native removal restored the stock numbered-workspace bindings; reinstallation
  retained the private project configuration.
- The running session was locked during bar verification. A shell restart was
  correctly refused by Omarchy; an unlocked, on-screen bar inspection is pending.

## Native desktop smoke test

Use Omarchy 4.5.0-3 / Hyprland 0.56.2 with two independent displays.

1. Record the focused monitor and each screen's current workspace before starting.
2. Install using a private config. Check `hyprctl reload` and `hyprctl configerrors`.
3. Switch between every configured project from each monitor. Both screens
   should show the same project, and focus should finish on the original screen.
4. Create disposable terminal windows with a test-specific app id. Exercise
   following, silent, and cross-monitor moves using only these windows.
5. Focus one of those windows through a direct compositor command. Confirm the
   other monitor follows when `follow_focus` is enabled.
6. Verify the widget's labels, shared active project, occupancy, and extra raw
   workspaces. Labels containing markup must remain literal text.
7. Remove the layer. Confirm original shortcuts and workspace bar entries return.
8. Reinstall and restore the original project view. Close only the test windows.

Do not simulate hot-unplug on a working desktop. Automated tests cover callback
ordering; physical unplug/restore remains a separate optional hardware check.
Do not publish screenshots containing private windows or project configurations.
