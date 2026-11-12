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
        (state / "view.json").write_text(json.dumps({
            "version": 1, "projects": [
                {"id": "atlas", "name": "Atlas", "slot": 1},
                {"id": "literal", "name": '<img src="https://invalid.test/x">', "slot": 2},
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
      var labels=[]
      function scan(item) {
        if (item.textFormat !== undefined && item.text !== undefined) {
          if (item.textFormat !== Text.PlainText) throw new Error("Non-plain label")
          labels.push(item.text)
        }
        if (item.children) for (var i=0;i<item.children.length;i++) scan(item.children[i])
      }
      scan(projects)
      if (labels.indexOf("Atlas")<0 || labels.indexOf('<img src="https://invalid.test/x">')<0)
        throw new Error("Missing literal labels: "+JSON.stringify(labels))
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
        if result.returncode or "PROJECTS_QML_PASS" not in output:
            raise SystemExit(output)
        print("PASS native QML loading and literal markup labels")


if __name__ == "__main__":
    main()
