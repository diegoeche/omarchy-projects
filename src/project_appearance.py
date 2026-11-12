"""Apply project looks using Omarchy's existing theme and background commands."""
import fcntl
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


class AppearanceError(ValueError):
    pass


def validate_appearance(value):
    if (not isinstance(value, dict) or not {"theme", "wallpaper"} <= set(value)
            or set(value) - {"theme", "wallpaper", "aether_variant"}):
        raise AppearanceError("appearance needs theme and wallpaper, with optional aether_variant")
    if "aether_variant" in value and (not isinstance(value["aether_variant"], str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", value["aether_variant"])):
        raise AppearanceError("appearance.aether_variant must be an Aether extraction mode")
    theme, wallpaper = value["theme"], value["wallpaper"]
    if not isinstance(theme, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,119}", theme):
        raise AppearanceError("appearance.theme must be an installed theme slug")
    if not isinstance(wallpaper, str) or not wallpaper or len(wallpaper) > 4096 or any(ord(c) < 32 for c in wallpaper):
        raise AppearanceError("appearance.wallpaper must be a local file path")
    return dict(value)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def current_look(locations):
    current = locations["home"] / ".local/state/omarchy/current"
    return {"theme": (current / "theme.name").read_text().strip(),
            "wallpaper": str((current / "background").resolve(strict=True))}


def resolve_look(look, locations):
    validate_appearance(look)
    roots = [locations["home"] / ".config/omarchy/themes",
             Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "themes"]
    if not any((root / look["theme"]).is_dir() for root in roots):
        raise AppearanceError("Project theme is not installed: " + look["theme"])
    wallpaper = Path(look["wallpaper"]).expanduser().resolve(strict=True)
    if not wallpaper.is_file():
        raise AppearanceError("Project wallpaper is not a file: " + str(wallpaper))
    return dict(look, wallpaper=str(wallpaper))


def snapshot_look(project_id, look, locations):
    """Keep wallpapers outside Omarchy's disposable current/theme directory."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", project_id):
        raise AppearanceError("Invalid project id")
    look = resolve_look(look, locations)
    source = Path(look["wallpaper"])
    directory = locations["data"] / "wallpapers"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    suffix = source.suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        raise AppearanceError("The wallpaper needs a media file extension")
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    target = directory / (project_id + '-' + digest.hexdigest()[:16] + suffix)
    if source != target:
        descriptor, temporary = tempfile.mkstemp(prefix=".wallpaper-", dir=directory)
        os.close(descriptor)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return dict(look, wallpaper=str(target))


def run(command, **kwargs):
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=60, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppearanceError(str(exc)) from exc
    if result.returncode:
        raise AppearanceError((result.stderr or result.stdout or "Appearance command failed").strip())
    return result.stdout


@contextmanager
def pause_theme_autoreload():
    """Replacing a watched theme file must not restart a workspace animation."""
    option = json.loads(run(["hyprctl", "-j", "getoption", "misc:disable_autoreload"]))
    original = option.get("bool")
    if type(original) is not bool:
        raise AppearanceError("Cannot determine Hyprland's auto-reload setting")
    def set_disabled(value):
        expression = ('hl.config({ misc = { disable_autoreload = ' + value
                      + ' } }); hl.exec_scheduled_prop_refresh_immediately()')
        response = run(["hyprctl", "eval", expression])
        if response.strip() != "ok":
            raise AppearanceError(response.strip() or "Could not update config auto-reload")
    if not original:
        set_disabled("true")
    try:
        yield
    finally:
        if not original:
            set_disabled("false")


def set_wallpaper(wallpaper, locations, managed=False):
    current = locations["home"] / ".local/state/omarchy/current"
    pending = current / (".project-background-" + str(os.getpid()))
    try:
        pending.symlink_to(wallpaper)
        pending.replace(current / "background")
    finally:
        pending.unlink(missing_ok=True)
    if not managed:
        run(["omarchy", "shell", "background", "setInstant", wallpaper])


def apply_look(look, locations, renderer=None):
    look = resolve_look(look, locations)
    previous = current_look(locations)
    try:
        if previous["wallpaper"] != look["wallpaper"]:
            set_wallpaper(look["wallpaper"], locations, managed=renderer is not None)
        if previous["theme"] != look["theme"]:
            environment = dict(os.environ, OMARCHY_THEME_SKIP_BACKGROUND="1")
            if renderer is not None:
                environment["OMARCHY_PROJECTS_RENDERER"] = "1"
                environment["OMARCHY_PROJECTS_TARGET"] = renderer["project"]
                environment["OMARCHY_PROJECTS_TEMPLATE_CACHE"] = renderer.get("cache", "")
            # Keep Omarchy's complete application retint, but apply its newly
            # generated border colors directly instead of reloading Hyprland.
            # This PATH override belongs only to this invocation and its children.
            environment["PATH"] = str(locations["data"] / "theme-bin") + os.pathsep + os.environ.get("PATH", os.defpath)
            environment.pop("OMARCHY_THEME_HEADLESS", None)
            environment.pop("OMARCHY_THEME_OFFLINE", None)
            environment.pop("OMARCHY_THEME_WAIT", None)
            with pause_theme_autoreload():
                run(["omarchy", "theme", "set", look["theme"]], env=environment)
        if current_look(locations)["theme"] != look["theme"]:
            raise AppearanceError("Omarchy did not apply the project's theme")
    except Exception:
        # A failed palette update should not leave the previous project with
        # the next project's wallpaper. Keep rollback best-effort and local.
        try:
            set_wallpaper(previous["wallpaper"], locations)
        except (OSError, AppearanceError):
            pass
        raise


def fingerprint(look):
    if look is None:
        return None
    stat = Path(look["wallpaper"]).stat()
    data = [look, stat.st_size, stat.st_mtime_ns]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def apply_requested(locations, load_config):
    """Short-lived serialized worker; queued requests converge to the latest."""
    state = locations["state"]
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    request_path, applied_path = state / "appearance-request.json", state / "appearance-applied.json"
    with (state / "appearance.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        while True:
            if not request_path.exists():
                return
            request = json.loads(request_path.read_text())
            config = load_config(locations["config"])
            project = next((p for p in config["projects"] if p["id"] == request.get("project")), None)
            if project is None:
                raise AppearanceError("Appearance request refers to an unknown project")
            look = project.get("appearance")
            if look is not None:
                look = resolve_look(look, locations)
            desired = {"project": project["id"], "fingerprint": fingerprint(look)}
            applied = json.loads(applied_path.read_text()) if applied_path.exists() else None
            if applied == desired:
                # Aether may have changed this project's current look. A
                # compositor reload must not undo that while it is being edited.
                return
            if json.loads(request_path.read_text()) != request:
                continue
            if look is not None:
                if request.get("wallpaper_managed") and config.get("preload_wallpapers"):
                    scene = json.loads((state / "scene.json").read_text())
                    prepared = scene.get("themes", {}).get(look["theme"], {})
                    apply_look(look, locations, renderer={"project": project["id"],
                                                         "cache": prepared.get("cache", "")})
                else:
                    apply_look(look, locations)
            write_json(applied_path, desired)
            if json.loads(request_path.read_text()) == request:
                return
