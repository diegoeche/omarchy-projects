import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Commons
import "ProjectMotion.js" as Motion

Item {
  id: root
  required property var panels
  property bool live: Quickshell.env("OMARCHY_PROJECTS_TESTING") !== "1"
  property var manifest: ({ projects: [], assets: [], duration: 200, style: "slide" })
  readonly property var assets: manifest.assets
  readonly property string style: manifest.style || "slide"
  property var workspaceMap: ({ monitors: [] })
  property string currentProject: ""
  property string previousProject: ""
  property string pendingProject: ""
  property string queuedProject: ""
  property bool pendingCommit: true
  property bool queuedCommit: true
  property string fromAsset: ""
  property string toAsset: ""
  property int direction: 1
  property real progress: 1
  property bool active: false
  property bool initialized: false
  property var palette: null
  property string finalColors: ""
  property string finalShell: ""
  readonly property bool moving: motion.running
  property string lastDispatch: ""

  function project(id) {
    for (var i = 0; i < manifest.projects.length; i++) if (manifest.projects[i].id === id) return manifest.projects[i]
    return null
  }
  function focusedProject() {
    var focused = Hyprland.focusedMonitor
    if (!focused || !focused.activeWorkspace) return ""
    for (var i = 0; i < workspaceMap.monitors.length; i++) {
      var row = workspaceMap.monitors[i]
      if (row.name !== focused.name) continue
      for (var key in row.workspaces) if (row.workspaces[key] === focused.activeWorkspace.id) return key
    }
    return ""
  }
  function dispatch(method, id) {
    lastDispatch = "omarchy_projects.action(" + JSON.stringify(method)
      + (id === undefined ? "" : "," + JSON.stringify(id)) + ")"
    if (live) Hyprland.dispatch(lastDispatch)
  }
  function announce() { if (live && manifest.projects.length) dispatch("renderer_ready", true) }
  function readyFor(key) {
    if (panels.length === 0) return false
    for (var i = 0; i < panels.length; i++) {
      if (!panels[i].projectWallpapers || !panels[i].projectWallpapers.readyFor(key)) return false
    }
    return true
  }
  function checkReady() {
    if (!initialized) {
      var initial = project(focusedProject())
      if (initial && readyFor(initial.asset)) {
        currentProject = initial.id
        toAsset = initial.asset
        fromAsset = initial.asset
        active = true
        initialized = true
      }
    }
    if (pendingProject && !moving) {
      var target = project(pendingProject)
      if (target && readyFor(target.asset)) begin(target)
    }
  }
  function request(id, commit) {
    commit = commit !== false
    var target = project(id)
    if (!target) { active = false; if (commit) dispatch("commit", id); return }
    if (moving) { queuedProject = id; queuedCommit = commit; return }
    if (id === currentProject) { if (commit) dispatch("commit", id); return }
    if (!target.asset) {
      previousProject = currentProject
      currentProject = id
      if (commit) dispatch("commit", id)
      return
    }
    pendingProject = id
    pendingCommit = commit
    checkReady()
  }
  function step(direction) {
    if (!manifest.projects.length) return
    var id = queuedProject || pendingProject || currentProject
    var index = manifest.projects.findIndex(function(row) { return row.id === id })
    request(manifest.projects[(index + direction + manifest.projects.length) % manifest.projects.length].id)
  }
  function begin(target) {
    var old = project(currentProject)
    previousProject = currentProject
    currentProject = target.id
    pendingProject = ""
    readinessTimeout.stop()
    direction = old && target.slot < old.slot ? -1 : 1
    fromAsset = toAsset || target.asset
    toAsset = target.asset
    active = true
    finalColors = target.colors
    finalShell = target.shell
    var source = {}
    ;["foreground", "background", "accent", "urgent", "muted"].forEach(function(key) { source[key] = String(Commons.Color[key]) })
    var targetBase = Motion.parseBase(target.colors, source)
    var shell = Object.assign({}, Commons.Color.parseShell(target.shell), Commons.Color.userShellValues)
    palette = Motion.palettePlan(source, Commons.Color.shellValues, targetBase, shell)
    progress = 0
    motion.start()
    if (pendingCommit) dispatch("commit", target.id)
  }
  function applyPalette() {
    if (!palette) return
    var frame = Motion.paletteFrame(palette, progress)
    for (var key in frame.base) Commons.Color[key] = frame.base[key]
    // Update color roles only. Font/spacing configuration is applied once at
    // the end, rather than rebuilding shell metrics on every animation frame.
    Commons.Color.shellValues = frame.shell
  }
  function finish() {
    if (finalColors) Commons.Color.loadColors(finalColors)
    Commons.Color.loadShell(finalShell)
    palette = null
    fromAsset = toAsset
    if (queuedProject) {
      var next = queuedProject
      var commit = queuedCommit
      queuedProject = ""
      Qt.callLater(function() { root.request(next, commit) })
    }
  }
  function acceptPalette(id, colors, shell) {
    if (id !== currentProject) return
    finalColors = Util.decodeBase64(colors)
    finalShell = Util.decodeBase64(shell)
    if (!moving) {
      Commons.Color.loadColors(finalColors)
      Commons.Color.loadShell(finalShell)
    }
  }
  function manualBackground(path) {
    for (var i = 0; i < assets.length; i++) {
      if (assets[i].key === toAsset && assets[i].path === path) return
    }
    motion.stop()
    palette = null
    pendingProject = queuedProject = ""
    active = false
  }
  function status() {
    var ready = []
    for (var i = 0; i < assets.length; i++) if (readyFor(assets[i].key)) ready.push(assets[i].key)
    var loads = 0
    for (var p = 0; p < panels.length; p++) loads += panels[p].projectWallpapers.loadEvents
    return JSON.stringify({ current: currentProject, moving: moving, loaded: ready.length, imageLoads: loads,
      uniqueWallpapers: assets.length, active: active,
      color: String(Commons.Color.background), progress: progress })
  }
  onProgressChanged: applyPalette()
  onPendingProjectChanged: { if (pendingProject) readinessTimeout.restart() }
  Component.onDestruction: { if (live) dispatch("renderer_ready", false) }

  Timer {
    id: readinessTimeout
    interval: 2000
    onTriggered: {
      var id = root.pendingProject
      root.pendingProject = ""
      root.active = false
      root.dispatch("renderer_ready", false)
      if (root.pendingCommit) root.dispatch("commit", id)
      console.warn("Project wallpaper could not be prepared; using normal workspace switching")
    }
  }

  NumberAnimation {
    id: motion
    target: root
    property: "progress"
    from: 0; to: 1
    duration: Style.duration(root.manifest.duration || 200)
    easing.type: Easing.Bezier
    easing.bezierCurve: Style.easeOut
    onFinished: root.finish()
  }
  FileView {
    path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/omarchy-projects/scene.json"
    watchChanges: true; printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        var data = JSON.parse(text())
        if (!Motion.validManifest(data)) throw new Error("Invalid scene")
        motion.stop()
        root.palette = null
        root.pendingProject = root.queuedProject = ""
        root.progress = 1
        root.manifest = data
        root.initialized = false
        Qt.callLater(root.announce)
        Qt.callLater(root.checkReady)
      } catch (error) { console.warn("Project wallpaper manifest unavailable") }
    }
  }
  FileView {
    path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/omarchy-projects/view.json"
    watchChanges: true; printErrors: false
    onFileChanged: reload()
    onLoaded: { try { root.workspaceMap = JSON.parse(text()); Qt.callLater(root.checkReady) } catch (error) {} }
  }
  Variants {
    model: root.live ? root.manifest.projects : []
    Scope {
      required property var modelData
      GlobalShortcut {
        appid: "omarchy-projects"
        name: "show-" + modelData.slot
        description: "Switch project " + modelData.slot
        onPressed: root.request(modelData.id)
      }
      GlobalShortcut {
        appid: "omarchy-projects"
        name: "look-" + modelData.slot
        onPressed: root.request(modelData.id, false)
      }
    }
  }
  Variants {
    model: root.live ? ["next", "prev", "back"] : []
    GlobalShortcut {
      required property string modelData
      appid: "omarchy-projects"; name: modelData
      onPressed: {
        if (modelData === "next") root.step(1)
        else if (modelData === "prev") root.step(-1)
        else root.request(root.previousProject || root.currentProject)
      }
    }
  }
  Connections {
    target: Hyprland
    function onRawEvent(event) { if (event.name === "configreloaded") Qt.callLater(root.announce) }
  }
}
