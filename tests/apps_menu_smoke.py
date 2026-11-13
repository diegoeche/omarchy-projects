#!/usr/bin/env python3
"""Inspect real dropdown icons on Wayland without opening a desktop surface."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SHELL = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"


def main():
    with tempfile.TemporaryDirectory(prefix="project-app-menu-") as temporary:
        target = Path(temporary)
        for name in ("Commons", "Ui"):
            (target / name).symlink_to(SHELL / name)
        (target / "plugin").symlink_to(ROOT / "plugin")
        applications = target / "data/applications"
        applications.mkdir(parents=True)
        icon = target / 'fixture " icon.svg'
        icon.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" fill="#aabbcc"/></svg>')
        (applications / "Chat Atlas.desktop").write_text(
            '[Desktop Entry]\nType=Application\nName=Fixture Chat\nExec=true\nIcon=' + str(icon) + '\n')
        (applications / "Remote.desktop").write_text(
            '[Desktop Entry]\nType=Application\nName=Remote\nExec=true\nIcon=https://invalid.test/icon.svg\n')
        (target / "shell.qml").write_text('''import QtQuick
import Quickshell
import "plugin" as Projects
Scope {
  property var choices: []
  Projects.ProjectApps {
    id: menu
    anchorItem: null
    bar: null
    title: '<img src="https://invalid.test/title"> apps'
    project: ({ id: "atlas", apps: [
      { id: "chat", name: '<img src="https://invalid.test/name">', desktop: "Chat Atlas.desktop" },
      { id: "remote", name: "Remote", desktop: "Remote.desktop" }
    ] })
    onChosen: function(projectId, appId) { choices.push([projectId, appId]) }
  }
  Timer {
    property int attempts: 0
    interval: 100; running: true; repeat: true
    onTriggered: {
      attempts++
      if (!menu.loadedContent) { menu.ensureContent(); return }
      menu.loadedContent.list.forceLayout()
      var objects = {}
      function scan(item) {
        if (item.objectName) objects[item.objectName] = item
        if (item.textFormat !== undefined && item.text !== undefined && item.textFormat !== Text.PlainText)
          throw new Error("Non-plain app text")
        if (item.children) for (var i=0; i<item.children.length; i++) scan(item.children[i])
      }
      scan(menu.loadedContent)
      var icon = objects["project-app-icon-chat"]
      if (!icon || icon.status !== Image.Ready) {
        if (attempts < 20) return
        throw new Error("Desktop launcher icon did not load")
      }
      if (String(icon.source).indexOf("file:") !== 0 || String(icon.source).indexOf("fixture") < 0)
        throw new Error("Wrong desktop icon source: " + icon.source)
      if (objects["project-app-name-chat"].text !== '<img src="https://invalid.test/name">')
        throw new Error("App name lost literal markup")
      if (String(objects["project-app-icon-remote"].source) !== "")
        throw new Error("Remote desktop icon reached the image loader")
      menu.choose(0)
      menu.moveSelection(1)
      menu.choose(menu.selectedIndex)
      menu.choose(-1)
      if (JSON.stringify(choices) !== '[["atlas","chat"],["atlas","remote"]]')
        throw new Error("App selection lost its namespace or id: " + JSON.stringify(choices))
      if (menu.open) throw new Error("Smoke test mapped a desktop panel")
      console.log("PROJECT_APPS_MENU_PASS")
      Qt.quit()
    }
  }
}''')
        original_runtime = Path(os.environ["XDG_RUNTIME_DIR"])
        display = Path(os.environ.get("WAYLAND_DISPLAY", "wayland-1"))
        if not display.is_absolute():
            display = original_runtime / display
        runtime = target / "runtime"
        runtime.mkdir(mode=0o700)
        (runtime / "hypr").symlink_to(original_runtime / "hypr")
        environment = dict(os.environ, QT_QPA_PLATFORM="wayland", QT_QUICK_BACKEND="software",
                           GSETTINGS_BACKEND="memory", XDG_DATA_HOME=str(target / "data"),
                           XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY=str(display))
        result = subprocess.run(["quickshell", "--no-color", "-p", str(target)],
                                env=environment, capture_output=True, text=True, timeout=10)
        output = result.stdout + result.stderr
        if result.returncode or "PROJECT_APPS_MENU_PASS" not in output or "Binding loop detected" in output:
            raise SystemExit(output)
        print("PASS native app menu: desktop icons, literal labels, blocked remote icons, and namespaced selection")


if __name__ == "__main__":
    main()
