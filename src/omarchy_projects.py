"""Configuration and CLI for Omarchy Projects. Standard library only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

from project_appearance import (apply_requested, current_look, resolve_look,
                                snapshot_look, validate_appearance)
from project_assets import prepare_assets


IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")


class ProjectError(Exception):
    pass


def validate_icon(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 4096
            or any(ord(char) < 32 for char in value)
            or not (value.startswith('/') or value.startswith('~/'))
            or Path(value).suffix.lower() not in {'.png', '.svg', '.ico', '.jpg', '.jpeg', '.webp', '.avif', '.bmp'}):
        raise ProjectError("icon must be an absolute or ~/ local image path (PNG, SVG, ICO, JPEG, WebP, AVIF, BMP)")


def paths(home=None):
    base = Path(home) if home else Path.home()
    def xdg(key, fallback):
        value = os.environ.get(key) if home is None else None
        return Path(value) if value else base / fallback
    return {
        "home": base,
        "config": xdg("XDG_CONFIG_HOME", ".config") / "omarchy-projects/projects.json",
        "hypr": xdg("XDG_CONFIG_HOME", ".config") / "hypr/hyprland.lua",
        "shell": xdg("XDG_CONFIG_HOME", ".config") / "omarchy/shell.json",
        "plugin": xdg("XDG_CONFIG_HOME", ".config") / "omarchy/plugins/diegoeche.projects",
        "background_plugin": xdg("XDG_CONFIG_HOME", ".config") / "omarchy/plugins/diegoeche.background",
        "data": xdg("XDG_DATA_HOME", ".local/share") / "omarchy-projects",
        "state": xdg("XDG_STATE_HOME", ".local/state") / "omarchy-projects",
        "bin": base / ".local/bin/omarchy-projects",
    }


def validate(value):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ProjectError("projects.json must be an object with version 1")
    unknown = set(value) - {"version", "projects", "monitors", "follow_focus", "workspace_transition", "preload_wallpapers"}
    if unknown:
        raise ProjectError("unknown config keys: " + ", ".join(sorted(unknown)))
    projects = value.get("projects")
    if not isinstance(projects, list) or not 1 <= len(projects) <= 10:
        raise ProjectError("define between 1 and 10 projects")
    ids, slots, result = set(), set(), []
    for project in projects:
        if (not isinstance(project, dict) or not {"id", "name", "slot"} <= set(project)
                or set(project) - {"id", "name", "slot", "appearance", "icon", "label"}):
            raise ProjectError("each project needs id, name, slot, and optionally appearance, icon, label")
        ident, name, slot = (project[k] for k in ("id", "name", "slot"))
        if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident):
            raise ProjectError("project ids must use lowercase letters, digits, - or _")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 48 or any(ord(c) < 32 for c in name):
            raise ProjectError("project names must be 1–48 characters without control characters")
        if type(slot) is not int or not 1 <= slot <= 10:
            raise ProjectError("project slots must be integers from 1 to 10")
        if ident in ids or slot in slots:
            raise ProjectError("project ids and slots must be unique")
        ids.add(ident)
        slots.add(slot)
        if "appearance" in project:
            validate_appearance(project["appearance"])
        if "icon" in project:
            validate_icon(project["icon"])
        if "label" in project:
            if project["label"] not in ("text", "icon", "both"):
                raise ProjectError("label must be text, icon, or both")
            if project["label"] != "text" and "icon" not in project:
                raise ProjectError("icon and both labels need an icon path")
        result.append(dict(project))
    monitors = value.get("monitors", [])
    if not isinstance(monitors, list) or any(
        not isinstance(m, str) or not m or len(m) > 256 or any(ord(c) < 32 for c in m)
        for m in monitors
    ):
        raise ProjectError("monitors must be a list of output names or desc: selectors")
    if len(set(monitors)) != len(monitors):
        raise ProjectError("monitor selectors must be unique")
    follow = value.get("follow_focus", True)
    if type(follow) is not bool:
        raise ProjectError("follow_focus must be true or false")
    config = {"version": 1, "projects": result, "monitors": monitors, "follow_focus": follow}
    if "preload_wallpapers" in value:
        if type(value["preload_wallpapers"]) is not bool:
            raise ProjectError("preload_wallpapers must be true or false")
        config["preload_wallpapers"] = value["preload_wallpapers"]
    transition = value.get("workspace_transition")
    if transition is None and config.get("preload_wallpapers"):
        transition = {"style": "slide", "duration_ms": 200}
    if transition is not None:
        if (not isinstance(transition, dict) or set(transition) != {"style", "duration_ms"}
                or not isinstance(transition["style"], str)
                or transition["style"] not in {"slide", "slidevert", "fade"}
                or type(transition["duration_ms"]) is not int
                or not 80 <= transition["duration_ms"] <= 300):
            raise ProjectError("workspace_transition needs style (slide, slidevert, fade) and duration_ms (80–300)")
        config["workspace_transition"] = dict(transition)
    return config


def load_config(path):
    try:
        return validate(json.loads(Path(path).read_text()))
    except (OSError, ValueError) as exc:
        raise ProjectError(f"cannot read {path}: {exc}") from exc


def lua(value):
    """Serialize data as Lua literals, including bytes unsafe in source strings."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        parts = []
        for byte in value.encode("utf-8"):
            if byte in (34, 92) or byte < 32 or byte >= 127:
                parts.append(f"\\{byte:03d}")
            else:
                parts.append(chr(byte))
        return '"' + "".join(parts) + '"'
    if isinstance(value, list):
        return "{" + ",".join(lua(item) for item in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join("[" + lua(key) + "]=" + lua(item) for key, item in value.items()) + "}"
    raise ProjectError(f"cannot serialize {type(value).__name__}")


def atomic_write(path, content, mode=0o600):
    # Follow an existing dotfile symlink without replacing the link itself.
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = target.stat().st_mode & 0o777 if target.exists() else mode
    fd, temporary = tempfile.mkstemp(prefix="." + target.name + ".", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.chmod(temporary, existing_mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def compile_config(config, locations):
    data = dict(config, state_file=str(locations["state"] / "view.json"),
                history_file=str(locations["state"] / "history"))
    if any("appearance" in project for project in config["projects"]):
        data["appearance_request_file"] = str(locations["state"] / "appearance-request.json")
        data["appearance_command"] = shlex.join([
            sys.executable, str(locations["data"] / "omarchy_projects.py"), "appearance", "apply"
        ]) + " >> " + shlex.quote(str(locations["state"] / "appearance.log")) + " 2>&1"
    return "-- Generated from projects.json; run omarchy-projects reload after editing.\nreturn " + lua(data) + "\n"


def select_project(config, ident):
    project = next((p for p in config["projects"]
                    if p["id"] == ident or str(p["slot"]) == ident), None)
    if project is None:
        raise ProjectError(f"unknown project: {ident}")
    return project


def focused_project(config, locations):
    call("publish")
    view = json.loads((locations["state"] / "view.json").read_text())
    monitors = json.loads(hyprctl("-j", "monitors"))
    focused = next((m for m in monitors if m["focused"]), None)
    if focused:
        for monitor in view["monitors"]:
            if monitor["name"] == focused["name"]:
                for ident, workspace in monitor["workspaces"].items():
                    if workspace == focused["activeWorkspace"]["id"]:
                        return select_project(config, ident)
    raise ProjectError("focus a configured project first")


def save_config_change(config, locations):
    path = locations["config"]
    previous = path.read_text()
    atomic_write(locations["state"] / "projects.before-appearance.json", previous)
    atomic_write(path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    try:
        reload_config(locations)
    except Exception:
        atomic_write(path, previous)
        raise


def set_transition(config, locations, direction, duration=None):
    styles = {"horizontal": "slide", "vertical": "slidevert", "fade": "fade"}
    config["workspace_transition"] = {"style": styles[direction],
        "duration_ms": duration if duration is not None else config.get("workspace_transition", {}).get("duration_ms", 200)}
    config = validate(config)
    save_config_change(config, locations)
    print("Workspace transition: " + direction + " (" + str(config["workspace_transition"]["duration_ms"]) + " ms)")


def icon_command(args, config, locations):
    project = select_project(config, args.project)
    if args.clear:
        if args.file or args.label:
            raise ProjectError("--clear cannot be combined with an icon file or --label")
        project.pop("icon", None)
        project.pop("label", None)
    elif args.file:
        source = Path(args.file).expanduser().resolve(strict=True)
        validate_icon(str(source))
        if not source.is_file() or source.stat().st_size > 4 * 1024 * 1024:
            raise ProjectError("icon must be an image file no larger than 4 MiB")
        data = source.read_bytes()
        target = locations["data"] / "icons" / (project["id"] + '-' + hashlib.sha256(data).hexdigest()[:16] + source.suffix.lower())
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='.icon-', dir=target.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        project["icon"] = str(target)
        project["label"] = args.label or "icon"
    elif args.label:
        project["label"] = args.label
    else:
        print(project.get("label", "both" if project.get("icon") else "text") + ": " + project.get("icon", project["name"]))
        return
    validate(config)
    save_config_change(config, locations)
    print("Updated label for " + project["name"])


def appearance_command(args, config, locations):
    if args.appearance_action == "apply":
        apply_requested(locations, load_config)
        return
    if args.appearance_action == "generate":
        if args.all and (args.project or args.wallpaper):
            raise ProjectError("--all cannot be combined with a project or --wallpaper")
        targets = config["projects"] if args.all else [select_project(config, args.project)
            if args.project else focused_project(config, locations)]
        for target in targets:
            look = dict(target.get("appearance") or current_look(locations))
            if args.wallpaper:
                look["wallpaper"] = args.wallpaper
            look["aether_variant"] = args.variant or look.get("aether_variant", "colorful")
            target["appearance"] = snapshot_look(target["id"], look, locations)
        save_config_change(config, locations)
        print("Prepared Aether palettes for " + str(len(targets)) + " project(s)")
        return
    project = select_project(config, args.project) if args.project else focused_project(config, locations)
    if args.appearance_action == "menu":
        call("show", project["id"])
        apply_requested(locations, load_config)
        choices = ["Open Aether", "Save current theme and wallpaper",
                   "Scroll vertically on all screens", "Scroll horizontally on all screens"]
        result = subprocess.run(["omarchy", "menu", "select", "Project appearance", *choices],
                                capture_output=True, text=True)
        if result.returncode:
            return
        choice = result.stdout.strip()
        if choice in choices[2:]:
            set_transition(config, locations, "vertical" if choice == choices[2] else "horizontal")
            return
        if choice == choices[0]:
            subprocess.Popen(["aether"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return
        if choice != choices[1]:
            return
        args.appearance_action = "save"
    if args.appearance_action == "save":
        if focused_project(config, locations)["id"] != project["id"]:
            raise ProjectError("switch to that project before saving its current appearance")
        project["appearance"] = snapshot_look(project["id"], current_look(locations), locations)
    else:
        project["appearance"] = resolve_look({"theme": args.theme, "wallpaper": args.wallpaper}, locations)
    save_config_change(config, locations)
    print("Saved appearance for " + project["name"])


def hyprctl(*arguments):
    try:
        result = subprocess.run(["hyprctl", *arguments], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProjectError(f"cannot reach Hyprland: {exc}") from exc
    output = (result.stdout + result.stderr).strip()
    if result.returncode or re.search(r"(?:runtime|syntax) error|error in lua|unknown request", output, re.I):
        raise ProjectError(output or "hyprctl failed")
    return result.stdout.strip()


def call(method, *arguments):
    return hyprctl("eval", 'assert(omarchy_projects, "Omarchy Projects is not loaded"); '
                   + "omarchy_projects." + method + "(" + ",".join(lua(arg) for arg in arguments) + ")")


def reload_config(locations):
    config = load_config(locations["config"])
    if config.get("preload_wallpapers") and not (locations["background_plugin"] / "ProjectScene.qml").is_file():
        raise ProjectError("Run scripts/install.py once to install the preloaded background plugin")
    original_config = locations["config"].read_text()
    before = json.dumps(config, sort_keys=True)
    scene_path = locations["state"] / "scene.json"
    original_scene = scene_path.read_text() if scene_path.exists() else None
    scene = prepare_assets(config, locations, write=False)
    generated = locations["state"] / "config.lua"
    previous = generated.read_text() if generated.exists() else None
    try:
        if json.dumps(config, sort_keys=True) != before:
            atomic_write(locations["config"], json.dumps(config, indent=2, ensure_ascii=False) + "\n")
        if scene is not None and (original_scene is None or json.loads(original_scene) != scene):
            atomic_write(scene_path, json.dumps(scene, indent=2, ensure_ascii=False) + "\n")
        atomic_write(generated, compile_config(config, locations))
        hyprctl("reload")
        errors = hyprctl("configerrors")
        if errors:
            raise ProjectError(errors)
    except ProjectError:
        atomic_write(locations["config"], original_config)
        if original_scene is not None:
            atomic_write(scene_path, original_scene)
        else:
            scene_path.unlink(missing_ok=True)
        if previous is not None:
            atomic_write(generated, previous)
            hyprctl("reload")
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Named projects across your Omarchy monitors")
    parser.add_argument("--config", type=Path, help="override projects.json (list/check only)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list project ids, slots, and names")
    commands.add_parser("check", help="validate your project configuration")
    status = commands.add_parser("status", help="read the current monitor/project views")
    status.add_argument("--json", action="store_true")
    for name in ("switch", "move"):
        command = commands.add_parser(name, help="switch project" if name == "switch" else "move the active window to a project")
        command.add_argument("project", help="project id or slot number")
        if name == "move":
            command.add_argument("--silent", action="store_true", help="keep the current project visible")
    for name in ("next", "prev", "back", "reload"):
        commands.add_parser(name)
    transition = commands.add_parser("transition", help="choose vertical or horizontal workspace scrolling")
    transition.add_argument("direction", nargs="?", choices=["horizontal", "vertical", "fade"])
    transition.add_argument("--duration-ms", type=int, help="animation duration, 80–300 milliseconds")
    icon = commands.add_parser("icon", help="configure a project's favicon/image label")
    icon.add_argument("project")
    icon.add_argument("file", nargs="?", help="local image to copy into project data")
    icon.add_argument("--label", choices=["text", "icon", "both"], help="display mode (defaults to icon with a new image)")
    icon.add_argument("--clear", action="store_true", help="remove the icon and show the project name")
    monitor = commands.add_parser("monitor", help="move the active window to a neighboring screen in the same project")
    monitor.add_argument("direction", choices=["l", "r", "u", "d"])
    appearance = commands.add_parser("appearance", help="configure each project's theme and wallpaper")
    appearance_actions = appearance.add_subparsers(dest="appearance_action", required=True)
    appearance_actions.add_parser("apply", help="apply the latest queued project appearance")
    generate = appearance_actions.add_parser("generate", help="prepare project palettes using installed Aether")
    generate.add_argument("project", nargs="?")
    generate.add_argument("--all", action="store_true", help="generate each configured project's palette")
    generate.add_argument("--variant", help="Aether extraction mode, default colorful")
    generate.add_argument("--wallpaper", help="replace one project's wallpaper and regenerate its palette")
    for name in ("save", "menu", "set"):
        action = appearance_actions.add_parser(name)
        action.add_argument("project", nargs=None if name == "set" else "?", help="defaults to the focused project")
        if name == "set":
            action.add_argument("--theme", required=True)
            action.add_argument("--wallpaper", required=True)
    args = parser.parse_args(argv)
    locations = paths()
    try:
        if args.config and args.command not in {"list", "check"}:
            raise ProjectError("--config is only supported by list and check; install to activate a config")
        config = load_config(args.config or locations["config"])
        if args.command == "icon":
            icon_command(args, config, locations)
        elif args.command == "transition":
            current = config.get("workspace_transition", {"style": "slide", "duration_ms": 200})
            direction = args.direction or {"slide": "horizontal", "slidevert": "vertical", "fade": "fade"}[current["style"]]
            if args.direction or args.duration_ms is not None:
                set_transition(config, locations, direction, args.duration_ms)
            else:
                print("Workspace transition: " + direction + " (" + str(current["duration_ms"]) + " ms)")
        elif args.command == "appearance":
            appearance_command(args, config, locations)
        elif args.command == "list":
            for project in config["projects"]:
                print(f'{project["slot"]:2}  {project["id"]:16} {project["name"]}')
        elif args.command == "check":
            print(f'Valid: {len(config["projects"])} projects')
        elif args.command == "reload":
            reload_config(locations)
            print("Project configuration reloaded")
        elif args.command == "status":
            call("publish")
            view = json.loads((locations["state"] / "view.json").read_text())
            monitors = json.loads(hyprctl("-j", "monitors"))
            active = {m["name"]: m["activeWorkspace"]["id"] for m in monitors}
            rows = []
            for monitor in view["monitors"]:
                ident = next((key for key, value in monitor["workspaces"].items()
                              if value == active.get(monitor["name"])), None)
                rows.append({"monitor": monitor["name"], "project": ident,
                             "workspace": active.get(monitor["name"])})
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for row in rows:
                    print(f'{row["monitor"]}: {row["project"] or "other workspace"} ({row["workspace"]})')
        elif args.command in {"switch", "move"}:
            project = select_project(config, args.project)
            if args.command == "switch":
                call("show", project["id"])
            else:
                call("move", project["id"], not args.silent)
        elif args.command == "monitor":
            call("move_monitor", args.direction)
        else:
            method = {"next": "step", "prev": "step", "back": "back"}[args.command]
            call(method, *([1 if args.command == "next" else -1] if method == "step" else []))
        return 0
    except (ProjectError, OSError, ValueError) as exc:
        print(f"omarchy-projects: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
