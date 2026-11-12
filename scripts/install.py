#!/usr/bin/env python3
"""Install/remove the local layer without replacing dotfile symlinks."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from omarchy_projects import ProjectError, atomic_write, compile_config, hyprctl, load_config, lua, paths

START = "-- >>> omarchy-projects >>>"
END = "-- <<< omarchy-projects <<<"
PLUGIN = "diegoeche.projects"


class Transaction:
    def __init__(self, directory):
        self.directory = directory
        self.before = {}

    def write(self, path, content, mode=0o600):
        target = path.resolve()
        if target not in self.before:
            original = target.read_text() if target.exists() else None
            mode_before = target.stat().st_mode & 0o777 if target.exists() else None
            self.before[target] = (original, mode_before)
            if original is not None:
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                atomic_write(self.directory / f"{len(self.before):02}-{target.name}", original)
        atomic_write(path, content, mode)

    def remove(self, path):
        target = path.resolve()
        if target.exists():
            self.write(path, target.read_text())
            target.unlink()

    def rollback(self):
        for path, (original, mode) in reversed(list(self.before.items())):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, original, mode)


def strip_loader(text):
    if START not in text and END not in text:
        return text
    if text.count(START) != 1 or text.count(END) != 1:
        raise ProjectError("ambiguous omarchy-projects loader markers; inspect hyprland.lua")
    before, remainder = text.split(START, 1)
    if END not in remainder:
        raise ProjectError("incomplete omarchy-projects loader block")
    _, after = remainder.split(END, 1)
    return before + after.removeprefix("\n")


def loader(text, locations):
    base = strip_loader(text).rstrip() + "\n\n"
    return (base + START + "\n"
            + "dofile(" + lua(str(locations["data"] / "controller.lua")) + ").setup(dofile("
            + lua(str(locations["state"] / "config.lua")) + "))\n" + END + "\n")


def clone_ids(locations):
    ids = {"omarchy.workspaces"}
    for manifest in locations["plugin"].parent.glob("*/manifest.json"):
        try:
            data = json.loads(manifest.read_text())
            if data.get("omarchy", {}).get("clonedFrom") == "omarchy.workspaces":
                ids.add(data["id"])
        except (OSError, ValueError, KeyError):
            continue
    return ids


def install_bar(shell, ids):
    layout = shell.setdefault("bar", {}).setdefault("layout", {})
    replaced, present = [], False
    for section, rows in layout.items():
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            if row.get("id") == PLUGIN:
                present = True
            elif row.get("id") in ids:
                replaced.append({"section": section, "original": row})
                rows[index] = {"id": PLUGIN}
                present = True
    if not present:
        layout.setdefault("left", []).append({"id": PLUGIN})
    return replaced


def remove_bar(shell, replacements):
    pending = list(replacements)
    for section, rows in shell.get("bar", {}).get("layout", {}).items():
        if not isinstance(rows, list):
            continue
        updated = []
        for row in rows:
            if not isinstance(row, dict) or row.get("id") != PLUGIN:
                updated.append(row)
                continue
            replacement = next((item for item in pending if item["section"] == section),
                               pending[0] if pending else None)
            if replacement:
                original = replacement["original"]
                if not any(isinstance(item, dict) and item.get("id") == original.get("id") for item in rows):
                    updated.append(original)
                pending.remove(replacement)
        rows[:] = updated


def install(locations, config_path=None, no_bar=False, no_reload=False, uninstall=False):
    if not locations["hypr"].is_file():
        raise ProjectError(f'Hyprland Lua config not found: {locations["hypr"]}')
    if not no_reload:
        errors = hyprctl("configerrors")
        if errors:
            raise ProjectError("fix the existing Hyprland config errors before installing:\n" + errors)
    record_path = locations["state"] / "install.json"
    record = json.loads(record_path.read_text()) if record_path.exists() else {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    transaction = Transaction(locations["state"] / "backups" / stamp)
    locations["state"].mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if uninstall:
            transaction.write(locations["hypr"], strip_loader(locations["hypr"].read_text()))
            if record.get("bar") and locations["shell"].exists():
                shell = json.loads(locations["shell"].read_text())
                remove_bar(shell, record.get("bar_replacements", []))
                transaction.write(locations["shell"], json.dumps(shell, indent=2) + "\n")
            for name in ("manifest.json", "Projects.qml"):
                transaction.remove(locations["plugin"] / name)
            for name in ("controller.lua", "omarchy_projects.py", "project_appearance.py"):
                transaction.remove(locations["data"] / name)
            transaction.remove(locations["bin"])
            transaction.remove(record_path)
        else:
            source_config = config_path or (locations["config"] if locations["config"].exists()
                                           else ROOT / "examples/projects.json")
            config = load_config(source_config)
            transaction.write(locations["config"], json.dumps(config, indent=2, ensure_ascii=False) + "\n")
            transaction.write(locations["state"] / "config.lua", compile_config(config, locations))
            transaction.write(locations["data"] / "controller.lua", (ROOT / "hypr/controller.lua").read_text())
            transaction.write(locations["data"] / "omarchy_projects.py", (ROOT / "src/omarchy_projects.py").read_text())
            transaction.write(locations["data"] / "project_appearance.py", (ROOT / "src/project_appearance.py").read_text())
            launcher = ("#!/usr/bin/env python3\nimport sys\nsys.path.insert(0, "
                        + repr(str(locations["data"])) + ")\nfrom omarchy_projects import main\nsys.exit(main())\n")
            transaction.write(locations["bin"], launcher, 0o755)
            if not no_bar:
                if not locations["shell"].is_file():
                    raise ProjectError(f'Omarchy shell config not found: {locations["shell"]}; use --no-bar')
                shell = json.loads(locations["shell"].read_text())
                replaced = install_bar(shell, clone_ids(locations))
                if not record.get("bar"):
                    record["bar_replacements"] = replaced
                record["bar"] = True
                for name in ("manifest.json", "Projects.qml"):
                    transaction.write(locations["plugin"] / name, (ROOT / "plugin" / name).read_text())
                transaction.write(locations["shell"], json.dumps(shell, indent=2) + "\n")
            record["version"] = 1
            transaction.write(record_path, json.dumps(record, indent=2) + "\n")
            # Install the loader last, once every required file is present.
            transaction.write(locations["hypr"], loader(locations["hypr"].read_text(), locations))
        if not no_reload:
            hyprctl("reload")
            errors = hyprctl("configerrors")
            if errors:
                raise ProjectError(errors)
    except Exception:
        transaction.rollback()
        if not no_reload:
            try:
                hyprctl("reload")
            except ProjectError:
                pass
        raise
    return transaction.directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="install a private project config")
    parser.add_argument("--home", type=Path, help="use another home directory (packaging/tests)")
    parser.add_argument("--no-bar", action="store_true", help="install only the controller and CLI")
    parser.add_argument("--no-reload", action="store_true", help="skip explicit reload/check (files may still auto-reload)")
    parser.add_argument("--uninstall", action="store_true", help="remove the layer, retaining projects.json and backups")
    args = parser.parse_args()
    if args.home and args.home.resolve() != Path.home().resolve() and not args.no_reload:
        parser.error("use --no-reload with --home to avoid reloading an unrelated desktop")
    try:
        backup = install(paths(args.home), args.config, args.no_bar, args.no_reload, args.uninstall)
        print("Removed Omarchy Projects" if args.uninstall else "Installed Omarchy Projects")
        print(f"Backups: {backup}")
        return 0
    except (ProjectError, OSError, ValueError) as exc:
        print(f"install: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
