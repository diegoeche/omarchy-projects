#!/usr/bin/env python3
"""Exercise preloaded images and rapid navigation without desktop dispatches."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
SHELL = Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy')) / 'shell'


def png(red, green, blue):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 16, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + bytes([red, green, blue]) * 16) * 16)) + chunk(b'IEND', b''))


def main():
    with tempfile.TemporaryDirectory(prefix='omarchy-projects-scene-') as temporary:
        target = Path(temporary)
        for name in ('Commons', 'Ui'):
            (target / name).symlink_to(SHELL / name)
        (target / 'background').symlink_to(ROOT / 'background')
        state = target / 'state/omarchy-projects'
        state.mkdir(parents=True)
        assets = []
        projects = []
        for index, name in enumerate(('atlas', 'boreal', 'personal')):
            data = png(255 if index == 0 else 0, 255 if index == 1 else 0, 255 if index == 2 else 0)
            path = target / (name + '.png')
            path.write_bytes(data)
            key = hashlib.sha256(data).hexdigest()
            assets.append({'key': key, 'path': str(path), 'width': 16, 'height': 16})
            projects.append({'id': name, 'slot': index + 1, 'asset': key,
                             'colors': 'foreground = "#ffffff"\nbackground = "#111111"\n',
                             'shell': '[bar]\nbackground = "#111111"\n'})
        (state / 'scene.json').write_text(json.dumps({'version': 1, 'duration': 200, 'style': 'slide',
                                                     'projects': projects, 'assets': assets}))
        (state / 'view.json').write_text('{"monitors":[]}')
        (target / 'shell.qml').write_text('''import QtQuick
import QtQuick.Window
import Quickshell
import "background" as Background
Window {
  id: host
  visible: true; width: 320; height: 200
  property int stage: 0
  property int ticks: 0
  property int loads: 0
  property bool sawMidpoint: false
  property var original: []
  Background.ProjectScene { id: scene; panels: [{projectWallpapers: wallpapers}]; live: false }
  Background.ProjectWallpapers { id: wallpapers; anchors.fill: parent; scene: scene; display: null }
  Timer {
    interval: 10; running: true; repeat: true
    onTriggered: {
      if (++host.ticks > 500) { console.error("Timed out waiting for preloaded scene: " + scene.status()); Qt.quit(); return }
      if (host.stage === 1 && scene.currentProject === "boreal" && scene.progress > 0.05 && scene.progress < 0.95) {
        var a = wallpapers.images.itemAt(0), b = wallpapers.images.itemAt(1)
        if (!(a.x < 0 && b.x > 0 && Math.abs(b.x - a.x - 320) < 0.01)) {
          console.error("Wallpaper planes do not share a moving edge"); Qt.quit(); return
        }
        host.sawMidpoint = true
      }
      if (host.stage === 0 && wallpapers.warmed) {
        scene.initialized = true
        scene.currentProject = "atlas"
        scene.fromAsset = scene.manifest.projects[0].asset
        scene.toAsset = scene.fromAsset
        host.loads = wallpapers.loadEvents
        for (var i=0;i<3;i++) host.original.push(wallpapers.images.itemAt(i))
        host.stage = 1
        scene.request("boreal")
        // Rapid input must keep only the latest destination after the current slide.
        scene.request("atlas")
        scene.request("personal")
      } else if (host.stage === 1 && scene.currentProject === "personal" && !scene.moving) {
        if (!host.sawMidpoint) throw new Error("No intermediate wallpaper frame")
        if (wallpapers.loadEvents !== host.loads) throw new Error("Images reloaded during navigation")
        for (var j=0;j<3;j++) if (host.original[j] !== wallpapers.images.itemAt(j))
          throw new Error("Image objects recreated during navigation")
        console.log("PROJECT_SCENE_PASS " + scene.status())
        Qt.quit()
      }
    }
  }
}''')
        environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                           GSETTINGS_BACKEND='memory', OMARCHY_PROJECTS_TESTING='1',
                           XDG_STATE_HOME=str(target / 'state'))
        try:
            result = subprocess.run(['quickshell', '--no-color', '-p', str(target)], env=environment,
                                    capture_output=True, text=True, timeout=8)
        except subprocess.TimeoutExpired as error:
            raise SystemExit((error.stdout or b'').decode() + (error.stderr or b'').decode())
        output = result.stdout + result.stderr
        if result.returncode or 'PROJECT_SCENE_PASS' not in output:
            raise SystemExit(output)
        print('PASS native QML: resident images, moving edges, and latest destination')


if __name__ == '__main__':
    main()
