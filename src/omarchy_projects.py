"""Configuration and CLI for Omarchy Projects. Standard library only."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")


class ProjectError(Exception):
    pass


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
        "data": xdg("XDG_DATA_HOME", ".local/share") / "omarchy-projects",
        "state": xdg("XDG_STATE_HOME", ".local/state") / "omarchy-projects",
        "bin": base / ".local/bin/omarchy-projects",
    }


def validate(value):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ProjectError("projects.json must be an object with version 1")
    unknown = set(value) - {"version", "projects", "monitors", "follow_focus"}
    if unknown:
        raise ProjectError("unknown config keys: " + ", ".join(sorted(unknown)))
    projects = value.get("projects")
    if not isinstance(projects, list) or not 1 <= len(projects) <= 10:
        raise ProjectError("define between 1 and 10 projects")
    ids, slots, result = set(), set(), []
    for project in projects:
        if not isinstance(project, dict) or set(project) != {"id", "name", "slot"}:
            raise ProjectError("each project needs exactly id, name, and slot")
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
    return {"version": 1, "projects": result, "monitors": monitors, "follow_focus": follow}


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
    data = dict(config, state_file=str(locations["state"] / "view.json"))
    return "-- Generated from projects.json; run omarchy-projects reload after editing.\nreturn " + lua(data) + "\n"


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
    generated = locations["state"] / "config.lua"
    previous = generated.read_text() if generated.exists() else None
    atomic_write(generated, compile_config(config, locations))
    try:
        hyprctl("reload")
        errors = hyprctl("configerrors")
        if errors:
            raise ProjectError(errors)
    except ProjectError:
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
    monitor = commands.add_parser("monitor", help="move the active window to a neighboring screen in the same project")
    monitor.add_argument("direction", choices=["l", "r", "u", "d"])
    args = parser.parse_args(argv)
    locations = paths()
    try:
        if args.config and args.command not in {"list", "check"}:
            raise ProjectError("--config is only supported by list and check; install to activate a config")
        config = load_config(args.config or locations["config"])
        if args.command == "list":
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
            project = next((p for p in config["projects"]
                            if p["id"] == args.project or str(p["slot"]) == args.project), None)
            if project is None:
                raise ProjectError(f"unknown project: {args.project}")
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

