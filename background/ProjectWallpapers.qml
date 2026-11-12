import QtQuick
import qs.Commons
import "ProjectMotion.js" as Motion

Item {
  id: root
  required property var scene
  required property var display
  property int warmFrames: 0
  property int loadEvents: 0
  property alias images: frames
  property var heldAsset: ({path: "", width: 0, height: 0})
  readonly property bool decoded: {
    if (frames.count === 0) return false
    for (var i = 0; i < frames.count; i++) {
      if (!frames.itemAt(i) || frames.itemAt(i).status !== Image.Ready) return false
    }
    return true
  }
  readonly property bool warmed: decoded && warmFrames >= 2
  clip: true
  z: scene.active ? 4 : -1
  visible: scene.active || !warmed

  function readyFor(key) {
    for (var i = 0; i < frames.count; i++) {
      var frame = frames.itemAt(i)
      if (frame && frame.modelData.key === key) return frame.status === Image.Ready && warmed
    }
    return false
  }

  function rememberCurrent() {
    for (var i = 0; i < scene.assets.length; i++) {
      if (scene.assets[i].key === scene.toAsset) { heldAsset = scene.assets[i]; return }
    }
  }

  Connections {
    target: root.scene
    function onToAssetChanged() { root.rememberCurrent() }
  }

  // Retain the previous frame while a configuration edit replaces the image
  // model. New assets warm behind it rather than flashing over the desktop.
  Image {
    anchors.fill: parent
    z: 2
    visible: !root.warmed && root.scene.active
    source: root.heldAsset.path ? Util.fileUrl(root.heldAsset.path) : ""
    sourceSize.width: root.heldAsset.width > 0 ? Math.min(root.heldAsset.width, Math.ceil(width * (root.display ? root.display.devicePixelRatio : 1))) : Math.ceil(width)
    sourceSize.height: root.heldAsset.height > 0 ? Math.min(root.heldAsset.height, Math.ceil(height * (root.display ? root.display.devicePixelRatio : 1))) : Math.ceil(height)
    asynchronous: true; cache: true; retainWhileLoading: true
    fillMode: Image.PreserveAspectCrop
  }

  FrameAnimation {
    running: root.decoded && root.warmFrames < 2
    onTriggered: {
      root.warmFrames++
      if (root.warmFrames >= 2) root.scene.checkReady()
    }
  }

  Repeater {
    id: frames
    model: root.scene.assets
    Image {
      required property var modelData
      width: root.width
      height: root.height
      readonly property real pixelScale: root.display ? root.display.devicePixelRatio : 1
      sourceSize.width: modelData.width > 0 ? Math.min(modelData.width, Math.ceil(width * pixelScale)) : Math.ceil(width * pixelScale)
      sourceSize.height: modelData.height > 0 ? Math.min(modelData.height, Math.ceil(height * pixelScale)) : Math.ceil(height * pixelScale)
      source: width > 0 && height > 0 ? Util.fileUrl(modelData.path) : ""
      asynchronous: true
      cache: true
      retainWhileLoading: true
      z: modelData.key === root.scene.toAsset ? 1 : 0
      fillMode: Image.PreserveAspectCrop
      smooth: true
      // Keep decoded image objects alive. Warm them behind the stock background
      // for two frames before exposing any project transition.
      visible: !root.warmed || modelData.key === root.scene.toAsset
        || (root.scene.moving && modelData.key === root.scene.fromAsset)
      x: root.scene.style === "slide" ? Motion.offset(modelData.key, root.scene.fromAsset,
        root.scene.toAsset, root.scene.direction, root.scene.progress, width) : 0
      y: root.scene.style === "slidevert" ? Motion.offset(modelData.key, root.scene.fromAsset,
        root.scene.toAsset, root.scene.direction, root.scene.progress, height) : 0
      opacity: root.scene.style !== "fade" || !root.scene.moving ? 1
        : (modelData.key === root.scene.toAsset ? root.scene.progress : 1 - root.scene.progress)
      onStatusChanged: {
        if (status === Image.Loading) root.loadEvents++
        root.warmFrames = 0
        Qt.callLater(root.scene.checkReady)
      }
    }
  }
}
