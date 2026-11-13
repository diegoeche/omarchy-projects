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
  property bool opened: false
  readonly property var appsProject: root.currentProject()
  readonly property bool hasApps: appsProject !== null && appsProject.app_count > 0
  onAppsProjectChanged: close()

  function open() {
    if (!root.bar || !appsProject || appsProject.app_count <= 0) return
    if (!appsMenuLoader.item) {
      appsMenuLoader.setSource(Qt.resolvedUrl("ProjectApps.qml"), {
        anchorItem: appsButton, bar: root.bar, owner: root,
        open: Qt.binding(function() { return root.opened }),
        project: Qt.binding(function() { return root.appsProject }),
        title: Qt.binding(function() {
          return root.appsProject ? strings.t("apps.title").arg(root.appsProject.name) : strings.t("apps.accessible")
        })
      })
    }
    if (appsMenuLoader.item) opened = true
  }
  function close() { opened = false }
  function toggle() { opened ? close() : open() }

  Translations {
    id: strings
    directory: Qt.resolvedUrl("i18n")
  }

  function iconSource(value) {
    if (typeof value !== "string" || value.length > 4096 || /[\u0000-\u001f]/.test(value)) return ""
    var path = value.indexOf("~/") === 0 ? Quickshell.env("HOME") + value.slice(1) : value
    return path.indexOf("/") === 0 ? Util.fileUrl(path) : ""
  }

  function labelMode(project) {
    return ["text", "icon", "both"].indexOf(project.label) >= 0
      ? project.label : (project.icon || project.emoji ? "both" : "text")
  }

  function emojiText(value) {
    return typeof value === "string" && value.length <= 32 && !/[\s\u0000-\u001f\u007f-\u009f]/.test(value) ? value : ""
  }

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

  function currentProject() {
    for (var i = 0; i < root.view.projects.length; i++) {
      if (root.activeProject(root.view.projects[i].id)) return root.view.projects[i]
    }
    return null
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
    columns: root.vertical ? 1 : Math.max(1, root.view.projects.length + root.extraWorkspaces().length + (root.hasApps ? 1 : 0))
    columnSpacing: root.vertical ? 0 : Style.space(1)
    rowSpacing: root.vertical ? Style.space(2) : 0

    Repeater {
      model: root.view.projects
      WidgetButton {
        id: projectButton
        required property var modelData
        readonly property string displayMode: root.labelMode(modelData)
        readonly property bool showEmoji: displayMode !== "text" && root.emojiText(modelData.emoji) !== ""
        readonly property bool showIcon: showEmoji || (projectIcon.source.toString() !== "" && projectIcon.status !== Image.Error)
        readonly property bool showText: displayMode !== "icon" || !showIcon
        bar: root.bar
        text: modelData.name
        labelVisible: false
        // Omarchy's bar tooltip and our label both use PlainText.
        tooltipText: showText ? "" : modelData.name
        Accessible.name: modelData.name
        Accessible.role: Accessible.Button
        implicitWidth: showText ? labelRow.implicitWidth + scaledHorizontalMargin * 2
          : Math.max(Style.bar.iconSlot, labelRow.implicitWidth + Style.space(8))
        active: root.activeProject(modelData.id)
        opacity: active || root.occupiedProject(modelData.id) ? 1 : 0.5
        horizontalMargin: 9
        fixedHeight: root.barSize
        Row {
          id: labelRow
          anchors.centerIn: parent
          spacing: Style.space(5)
          scale: projectButton.pressScale

          Image {
            id: projectIcon
            objectName: "project-icon-" + projectButton.modelData.id
            // Use the full bar canvas for legible project images and emoji.
            width: Style.bar.iconCanvas
            height: width
            anchors.verticalCenter: parent.verticalCenter
            visible: projectIcon.source.toString() !== "" && projectIcon.status !== Image.Error
            source: projectButton.displayMode === "text" || projectButton.showEmoji ? "" : root.iconSource(projectButton.modelData.icon)
            sourceSize.width: Math.ceil(width * 2)
            sourceSize.height: Math.ceil(width * 2)
            asynchronous: true
            cache: true
            fillMode: Image.PreserveAspectFit
          }
          Text {
            objectName: "project-emoji-" + projectButton.modelData.id
            visible: projectButton.showEmoji
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: root.emojiText(projectButton.modelData.emoji)
            font.family: "emoji"
            font.pixelSize: Style.bar.iconCanvas
            color: projectButton.foreground
            renderType: Text.NativeRendering
          }
          Text {
            objectName: "project-label-" + projectButton.modelData.id
            visible: projectButton.showText
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: projectButton.modelData.name
            font.family: projectButton.fontFamily
            font.pixelSize: projectButton.fontSize
            renderType: Text.NativeRendering
            color: projectButton.active ? projectButton.activeColor : projectButton.foreground
            Behavior on color {
              enabled: !root.bar || root.bar.foregroundAnimationEnabled
              ColorAnimation { duration: Style.duration(160) }
            }
          }
        }
        Rectangle {
          visible: projectButton.active && !projectButton.showText
          anchors.horizontalCenter: parent.horizontalCenter
          anchors.bottom: parent.bottom
          anchors.bottomMargin: Style.space(2)
          width: Style.space(5)
          height: Style.space(2)
          radius: height / 2
          color: projectButton.activeColor
        }
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

    WidgetButton {
      id: appsButton
      objectName: "project-apps-button"
      readonly property var project: root.appsProject
      readonly property bool available: project !== null && project.app_count > 0
      visible: available
      bar: root.bar
      text: "󰀻"
      tooltipText: !project ? strings.t("apps.chooseProject")
        : available ? strings.t("apps.title").arg(project.name) : strings.t("apps.empty").arg(project.name)
      Accessible.name: project ? strings.t("apps.title").arg(project.name) : strings.t("apps.accessible")
      Accessible.role: Accessible.Button
      interactive: available
      horizontalMargin: 7
      fixedHeight: root.barSize
      onPressed: {
        if (available) root.toggle()
      }
    }
  }

  Loader {
    id: appsMenuLoader
    onLoaded: {
      item.chosen.connect(function(projectId, appId) {
        root.close()
        if (root.bar) root.bar.run("omarchy-projects apps launch " + Util.shellQuote(appId)
          + " --project " + Util.shellQuote(projectId))
      })
    }
  }
}
