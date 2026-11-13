import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

KeyboardPanel {
  id: root
  property var project: null
  readonly property var apps: project && Array.isArray(project.apps) ? project.apps.slice(0, 24) : []
  property int selectedIndex: 0
  property string title: ""
  signal chosen(string projectId, string appId)

  function iconSource(app) {
    var id = String(app.desktop || "")
    if (id.length > 255 || /[\/\\\u0000-\u001f]/.test(id)) return ""
    if (id.slice(-8) === ".desktop") id = id.slice(0, -8)
    // Read the live desktop-entry model so newly installed launchers are seen.
    var entries = DesktopEntries.applications.values
    var entry = DesktopEntries.byId(id)
    var icon = entry ? String(entry.icon || "") : ""
    if (icon.length > 4096 || /[\u0000-\u001f]/.test(icon) || /^[a-z][a-z0-9+.-]*:/i.test(icon)) return ""
    if (icon.indexOf("/") === 0) return Util.fileUrl(icon)
    return Quickshell.iconPath(icon || "application-x-executable", true)
  }

  function choose(index) {
    if (!project || index < 0 || index >= apps.length) return
    var app = apps[index]
    if (!/^[a-z][a-z0-9_-]{0,39}$/.test(String(project.id))
        || !/^[a-z][a-z0-9_-]{0,39}$/.test(String(app.id))) return
    chosen(project.id, app.id)
  }

  function moveSelection(delta) {
    if (apps.length > 0) selectedIndex = (selectedIndex + delta + apps.length) % apps.length
    if (loadedContent) loadedContent.list.positionViewAtIndex(selectedIndex, ListView.Contain)
  }

  onOpenChanged: if (open) selectedIndex = 0
  focusTarget: loadedContent
  contentWidth: fittedContentWidth(Style.space(280))
  contentHeight: fittedContentHeight(loadedContentHeight, Style.space(480))

  content: PanelKeyCatcher {
    id: keys
    property alias list: list
    implicitHeight: header.implicitHeight + Style.space(12) + list.height
    anchors.fill: parent
    onCloseRequested: root.close()
    onMoveRequested: function(dx, dy) { if (dy !== 0) root.moveSelection(dy) }
    onActivateRequested: root.choose(root.selectedIndex)

    Column {
      width: parent.width
      spacing: Style.space(12)

      Text {
        id: header
        objectName: "project-apps-title"
        textFormat: Text.PlainText
        text: root.title
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        color: Util.alpha(Commons.Color.foreground, 0.7)
        width: parent.width
        elide: Text.ElideRight
      }

      ListView {
        id: list
        width: parent.width
        height: Math.min(root.apps.length * Style.space(42), Style.space(360))
        clip: true
        model: root.apps
        boundsBehavior: Flickable.StopAtBounds
        delegate: Rectangle {
          id: row
          required property int index
          required property var modelData
          width: ListView.view.width
          height: Style.space(42)
          radius: Style.cornerRadius
          color: root.selectedIndex === index ? Util.alpha(Commons.Color.foreground, 0.12) : "transparent"
          Accessible.role: Accessible.Button
          Accessible.name: String(modelData.name || "").slice(0, 48)
          Accessible.onPressAction: root.choose(index)

          Image {
            id: appIcon
            objectName: "project-app-icon-" + row.modelData.id
            x: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(24)
            height: width
            source: root.iconSource(row.modelData)
            sourceSize.width: Math.ceil(width * Screen.devicePixelRatio)
            sourceSize.height: Math.ceil(height * Screen.devicePixelRatio)
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            cache: true
          }
          Text {
            anchors.centerIn: appIcon
            visible: appIcon.status === Image.Error || appIcon.source.toString() === ""
            textFormat: Text.PlainText
            text: "󰀻"
            font.family: Style.font.family
            font.pixelSize: Style.font.iconLarge
            color: Commons.Color.foreground
          }
          Text {
            objectName: "project-app-name-" + row.modelData.id
            x: appIcon.x + appIcon.width + Style.space(12)
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - x - Style.space(10)
            textFormat: Text.PlainText
            text: String(row.modelData.name || "").slice(0, 48)
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            color: Commons.Color.foreground
            elide: Text.ElideRight
          }
          MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: root.selectedIndex = row.index
            onClicked: root.choose(row.index)
          }
        }
      }
    }
  }
}
