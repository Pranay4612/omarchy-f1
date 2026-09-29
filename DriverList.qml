import QtQuick
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Ui
// Sibling types come from components/qmldir, not a per-file import:
// a .qml file import does not register a type.

// The live classification. Scrollable, keyboard-navigable, and a selector for
// the track map: picking a row highlights that car on the circuit.
Item {
  id: root

  property var drivers: []
  property int selectedNumber: -1
  // Row index of the keyboard selection, so it can be scrolled into view.
  property int selectedIndex: -1

  // Highlighting the selection with the keyboard has to also move the
  // viewport, or the highlight ends up off-screen on a twenty-row tower.
  onSelectedIndexChanged: {
    if (selectedIndex >= 0) list.positionViewAtIndex(selectedIndex, ListView.Contain)
  }
  readonly property int rowHeight: Math.round(Style.spacing.lg + Style.font.body * 1.9)
  signal selected(int number)

  implicitWidth: parent ? parent.width : 0
  implicitHeight: parent ? parent.height : 0

  // Header
  Item {
    id: header
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    height: Style.font.caption + Style.space(6)

    Row {
      anchors.fill: parent
      anchors.leftMargin: Style.space(6)
      anchors.rightMargin: Style.space(6)
      spacing: Style.space(4)
      Text {
        width: Style.space(20); horizontalAlignment: Text.AlignRight
        text: "POS"; color: Color.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
      }
      Text {
        width: Style.space(30); text: "DRV"; color: Color.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
      }
      Text {
        width: Style.space(58); horizontalAlignment: Text.AlignRight
        text: "GAP"; color: Color.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
      }
      Text {
        width: Style.space(50); horizontalAlignment: Text.AlignRight
        text: "INT"; color: Color.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
      }
      Item { width: Style.space(20) }
      Text {
        width: Style.space(36); horizontalAlignment: Text.AlignRight
        text: "TYRE"; color: Color.muted; font.family: Style.font.family; font.pixelSize: Style.font.caption
      }
    }

    Rectangle {
      anchors.bottom: parent.bottom
      width: parent.width
      height: 1
      color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.18)
    }
  }

  ListView {
    id: list
    anchors.top: header.bottom
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    clip: true
    model: root.drivers
    boundsBehavior: Flickable.StopAtBounds
    // A short flick keeps a twenty-row tower from feeling like a chore while
    // still making a single row reachable on a small panel.
    flickDeceleration: 4000
    maximumFlickVelocity: 1400
    ScrollBar.vertical: ScrollBar {
      policy: ScrollBar.AsNeeded
      width: Style.space(3)
    }

    delegate: DriverRow {
      // Declared rather than reached for implicitly: the ListView injects it,
      // and using it without declaring it is a ReferenceError at runtime.
      required property var modelData
      width: list.width
      rowHeight: root.rowHeight
      driver: modelData
      selected: root.selectedNumber > 0 && modelData.number === root.selectedNumber
      dimmed: modelData.retired === true
      onActivated: root.selected(modelData.number)
    }
  }

  Text {
    anchors.centerIn: parent
    visible: root.drivers.length === 0
    text: "No classification yet"
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
}
