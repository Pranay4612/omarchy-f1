import QtQuick
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Ui
// Sibling types come from components/qmldir, not a per-file import:
// a .qml file import does not register a type.

// Live race control, straight from the feed's RaceControlMessages topic.
//
// Severity is derived from the message's own Category/Flag, not guessed from
// wording, so a safety car and a cleared sector cannot look the same.
Item {
  id: root

  property var messages: []
  property int maxRows: 12

  readonly property int rowCount: Math.min(messages ? messages.length : 0, maxRows)
  readonly property int rowHeight: Math.round(Style.font.bodySmall * 1.75)

  implicitWidth: parent ? parent.width : 0
  // Declared rather than left to the default. The bar sizes the popup from the
  // panel's implicit height, and a feed whose height is whatever its children
  // happen to measure produces a popup with a large empty region under it.
  implicitHeight: head.implicitHeight
                   + Style.space(3)
                   + Math.max(1, rowCount) * rowHeight
                   + Style.space(3)

  function severityFor(m) {
    if (!m) return 0
    if (m.Category === "Flag") {
      var f = String(m.Flag || "")
      if (f === "RED" || f === "YELLOW RED") return 3
      if (f === "SC" || f === "VSC") return 2
      if (f === "YELLOW" || f === "DOUBLE YELLOW" || f === "PURPLE") return 1
      return 0
    }
    if (m.Category === "Penalty" || m.Category === "Steward" || m.Category === "Race" || m.Category === "Other") return 2
    return 1
  }

  function labelFor(m) {
    if (!m) return ""
    if (m.Message) return String(m.Message)
    var parts = []
    if (m.Flag) parts.push(m.Flag)
    if (m.Scope && m.Scope !== "Track") parts.push(m.Scope + (m.Sector ? " " + m.Sector : ""))
    return parts.join(" ") || String(m.Category || "")
  }

  function colourFor(m) {
    var s = severityFor(m)
    if (s <= 0) return Color.muted
    if (s === 1) return Color.foreground
    if (s === 2) return Color.accent
    return Color.urgent
  }

  SectionLabel {
    id: head
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    text: "Race control"
  }

  Column {
    id: feed
    anchors.top: head.bottom
    anchors.topMargin: Style.space(3)
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: Style.spacing.xxs

    Repeater {
      model: root.rowCount > 0 ? root.messages.slice(0, root.maxRows) : []

      delegate: Row {
        required property var modelData
        required property int index
        width: feed.width
        height: root.rowHeight
        spacing: Style.space(4)
        opacity: index === 0 ? 1.0 : Math.max(0.45, 1.0 - index * 0.13)

        Rectangle {
          width: Style.space(2)
          height: parent.height
          color: root.colourFor(modelData)
          radius: width / 2
        }

        Text {
          width: Math.max(0, parent.width - Style.space(2) - Style.space(34))
          text: root.labelFor(modelData)
          color: root.severityFor(modelData) >= 3 ? root.colourFor(modelData) : Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideRight
        }

        Text {
          width: Style.space(30)
          horizontalAlignment: Text.AlignRight
          text: modelData && modelData.Lap ? "L" + modelData.Lap : ""
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  Text {
    anchors.top: feed.bottom
    anchors.topMargin: Style.space(3)
    visible: root.messages.length === 0
    text: "No messages"
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
}
