#!/usr/bin/env python3
"""Compile the real widget offscreen against the installed Omarchy shell.

Creates no desktop window and dispatches no compositor commands. Requires the
Omarchy/Quickshell installation; intentionally separate from portable unit tests.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SHELL = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"


def main():
    with tempfile.TemporaryDirectory(prefix="omarchy-projects-qml-") as temporary:
        target = Path(temporary)
        for name in ("Commons", "Ui"):
            (target / name).symlink_to(SHELL / name)
        (target / "plugin").symlink_to(ROOT / "plugin")
        state = target / "state/omarchy-projects"
        state.mkdir(parents=True)
        icon = target / 'fixture " icon.svg'
        icon.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16" fill="#aabbcc"/></svg>')
        (state / "view.json").write_text(json.dumps({
            "version": 1, "projects": [
                {"id": "atlas", "name": "Atlas", "slot": 1},
                {"id": "literal", "name": '<img src="https://invalid.test/x">', "slot": 2, "icon": str(icon), "label": "both"},
                {"id": "badge", "name": "Icon only", "slot": 3, "icon": str(icon), "label": "icon"},
                {"id": "missing", "name": "Missing icon", "slot": 4, "icon": str(target / 'missing.svg'), "label": "icon"},
                {"id": "remote", "name": "Blocked remote", "slot": 5, "icon": "https://invalid.test/icon.png", "label": "icon"},
                {"id": "tooltip", "name": '<img src="https://invalid.test/x">', "slot": 6, "icon": str(icon), "label": "icon"},
                {"id": "sunflower", "name": "Sunflower", "slot": 7, "emoji": "🌻", "label": "icon"},
                {"id": "composed", "name": "Composed", "slot": 8, "emoji": "👩‍💻", "label": "both"},
            ], "monitors": [],
        }))
        (target / "shell.qml").write_text('''import QtQuick
import Quickshell
import "plugin" as Projects
Scope {
  Projects.Projects { id: projects }
  Timer {
    interval: 500; running: true
    onTriggered: {
      var labels=[], objects={}
      function scan(item) {
        if (item.objectName) objects[item.objectName] = item
        if (item.textFormat !== undefined && item.text !== undefined) {
          if (item.textFormat !== Text.PlainText) throw new Error("Non-plain label")
          labels.push(item.text)
        }
        if (item.children) for (var i=0;i<item.children.length;i++) scan(item.children[i])
      }
      scan(projects)
      if (labels.indexOf("Atlas")<0 || labels.indexOf('<img src="https://invalid.test/x">')<0)
        throw new Error("Missing literal labels: "+JSON.stringify(labels))
      if (objects["project-label-badge"].visible || !objects["project-icon-badge"].visible
          || objects["project-icon-badge"].status !== Image.Ready) throw new Error("Icon-only label failed")
      if (!objects["project-label-literal"].visible || !objects["project-icon-literal"].visible)
        throw new Error("Combined icon/text label failed")
      if (!objects["project-label-missing"].visible || objects["project-icon-missing"].visible)
        throw new Error("Missing image did not fall back to text")
      if (String(objects["project-icon-remote"].source) !== "" || !objects["project-label-remote"].visible)
        throw new Error("An untrusted icon URL reached the image loader")
      var tooltip = objects["project-icon-tooltip"].parent.parent.tooltipText
      if (tooltip !== '<img src="https://invalid.test/x">') throw new Error("Icon-only tooltip lost its literal name")
      if (!objects["project-emoji-sunflower"].visible || objects["project-emoji-sunflower"].text !== "🌻"
          || objects["project-label-sunflower"].visible || String(objects["project-icon-sunflower"].source) !== "")
        throw new Error("Emoji-only label failed")
      if (!objects["project-emoji-composed"].visible || !objects["project-label-composed"].visible
          || objects["project-emoji-composed"].text !== "👩‍💻") throw new Error("Composed emoji and text label failed")
      console.log("PROJECTS_QML_PASS")
      Qt.quit()
    }
  }
}''')
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", GSETTINGS_BACKEND="memory",
                           XDG_STATE_HOME=str(target / "state"))
        result = subprocess.run(["quickshell", "--no-color", "-p", str(target)],
                                env=environment, capture_output=True, text=True, timeout=10)
        output = result.stdout + result.stderr
        if result.returncode or "PROJECTS_QML_PASS" not in output or "Binding loop detected" in output:
            raise SystemExit(output)
        print("PASS native QML: text/image/emoji labels, Unicode sequences, local sources, and fallback")


if __name__ == "__main__":
    main()
