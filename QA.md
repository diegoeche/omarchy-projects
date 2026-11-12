# Verification

## Automated

Run the commands in README.md. None of these tests modify the current desktop.

On an Omarchy machine, `python3 tests/qml_smoke.py` additionally loads the actual
widget and Omarchy UI components offscreen. It checks that labels exist and
markup is rendered as plain text, without opening a desktop window.

`python3 tests/scene_smoke.py` uses synthetic images in an offscreen window. It
checks ready images, shared moving wallpaper edges, latest-destination queuing,
and retained image sources/objects without dispatching desktop commands. It
covers horizontal and vertical scrolling, delayed project refreshes during
motion, and preserving an explicit manual wallpaper preview.

## Verified on 2026-11-12

- 40 Python tests and 22 controller behavior tests passed.
- Offscreen QML loading and literal markup labels passed against installed Omarchy.
- On a two-monitor Omarchy 4.5.0-3 / Hyprland 0.56.2 desktop, switching from either
  monitor synchronized both screens and preserved the focused monitor.
- Disposable Foot windows verified silent and following project moves, external
  focus synchronization, and movement between screens inside a project.
- Hyprland reported no configuration errors after installation and the checks.
- Native removal restored the stock numbered-workspace bindings; reinstallation
  retained the private project configuration.
- Project appearance switching restored each configured wallpaper automatically;
  rapid changes converged on the final project. The initial palette change used
  Omarchy's standard theme command. The former-project shortcut survives theme
  reloads, and silent window moves do not queue appearance changes.
- With the native 200 ms horizontal workspace slide enabled, a Lua VM marker
  survived a complete cross-theme project switch, confirming that the compositor
  was not reloaded. The bar model's file timestamp also stayed unchanged.
  Hyprland's prior auto-reload setting was restored after the theme update.
- The optional background clone loaded in the unlocked session. Its status
  reported all three configured images ready on two monitors. Repeated native
  project switches kept the image-load counter unchanged, synchronized both
  screens, and showed an intermediate animation state. The animation itself is
  configured for 200 ms; IPC polling adds overhead to observed completion time.
- Cross-palette native checks observed nine intermediate shell colors. Complete
  theme-worker convergence took approximately 280–360 ms, including its debounce
  and IPC checks. Cached templates were used; the compositor VM marker and bar
  model timestamp stayed intact, and config auto-reload was restored afterward.
- A regression check reloaded Hyprland before each of three project switches,
  then sent a stale background refresh during each slide. Both displays retained
  vertical movement with zero horizontal displacement, shared incoming/outgoing
  edges, unchanged image-load counts, and an active project renderer. Every
  switch recovered its renderer connection and kept managed wallpaper requests.
- Every project was regenerated with installed Aether's Colorful extraction
  mode. Independent saved theme palettes matched the active shell background
  colors after full application theme changes, and switching reused loaded
  wallpapers. The shared animation started after compositor acknowledgement
  (2–4 ms in these checks), with identical normalized progress on both screens.
  Physical presentation timing was not measured; the displays ran at different
  refresh rates.

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
