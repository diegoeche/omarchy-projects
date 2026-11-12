import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "diegoeche.projects"
  property var view: ({ projects: [], monitors: [] })

  function readView(text) {
    try {
      var next = JSON.parse(text)
      if (next.version === 1 && Array.isArray(next.projects) && Array.isArray(next.monitors)) root.view = next
    } catch (error) { root.view = { projects: [], monitors: [] } }
  }

  FileView {
    path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/omarchy-projects/view.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.readView(text())
    onLoadFailed: root.readView("")
  }

  function monitorNamed(name) {
    var monitors = Hyprland.monitors.values
    for (var i = 0; i < monitors.length; i++) if (monitors[i].name === name) return monitors[i]
    return null
  }

  function workspaceById(id) {
    var workspaces = Hyprland.workspaces.values
    for (var i = 0; i < workspaces.length; i++) if (workspaces[i].id === id) return workspaces[i]
    return null
  }

  function activeProject(id) {
    var count = 0
    for (var i = 0; i < root.view.monitors.length; i++) {
      var row = root.view.monitors[i]
      var monitor = root.monitorNamed(row.name)
      if (!monitor) continue
      count++
      if (!monitor.activeWorkspace || monitor.activeWorkspace.id !== row.workspaces[id]) return false
    }
    return count > 0
  }

  function occupiedProject(id) {
    for (var i = 0; i < root.view.monitors.length; i++) {
      var workspace = root.workspaceById(root.view.monitors[i].workspaces[id])
      if (workspace && workspace.toplevels.values.length > 0) return true
    }
    return false
  }

  // Existing windows on unconfigured/guest workspaces stay reachable.
  function extraWorkspaces() {
    var known = {}, extras = [], workspaces = Hyprland.workspaces.values
    for (var i = 0; i < root.view.monitors.length; i++) {
      var ids = root.view.monitors[i].workspaces
      for (var key in ids) known[ids[key]] = true
    }
    for (var j = 0; j < workspaces.length; j++) {
      var workspace = workspaces[j]
      if (workspace.id > 0 && !known[workspace.id] && (workspace.active || workspace.toplevels.values.length > 0)) extras.push(workspace.id)
    }
    return extras.sort(function(a, b) { return a - b })
  }

  function run(expression) {
    if (root.bar) root.bar.run("hyprctl eval " + Util.shellQuote(expression))
  }

  implicitWidth: grid.implicitWidth
  implicitHeight: grid.implicitHeight

  GridLayout {
    id: grid
    columns: root.vertical ? 1 : Math.max(1, root.view.projects.length + root.extraWorkspaces().length)
    columnSpacing: root.vertical ? 0 : Style.space(1)
    rowSpacing: root.vertical ? Style.space(2) : 0

    Repeater {
      model: root.view.projects
      WidgetButton {
        required property var modelData
        bar: root.bar
        // WidgetButton uses PlainText. No project name enters a rich-text tooltip.
        text: modelData.name
        active: root.activeProject(modelData.id)
        opacity: active || root.occupiedProject(modelData.id) ? 1 : 0.5
        horizontalMargin: 9
        fixedHeight: root.barSize
        onPressed: function(button) {
          if (button === Qt.RightButton && root.bar) {
            root.bar.run("omarchy-projects appearance menu " + Util.shellQuote(modelData.id))
          } else {
            root.run("omarchy_projects.show(" + JSON.stringify(modelData.id) + ")")
          }
        }
      }
    }

    Repeater {
      model: root.extraWorkspaces()
      WidgetButton {
        required property int modelData
        bar: root.bar
        text: "WS " + modelData
        active: {
          var workspace = root.workspaceById(modelData)
          return workspace !== null && workspace.active
        }
        horizontalMargin: 6
        fixedHeight: root.barSize
        onPressed: root.run("hl.dispatch(hl.dsp.focus({ workspace = " + JSON.stringify(String(modelData)) + " }))")
      }
    }
  }
}
