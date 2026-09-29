import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
// Sibling types come from components/qmldir, not a per-file import:
// a .qml file import does not register a type.

// Championship mode: what the panel shows when no session is running.
//
// Standings come from Jolpica, the free public mirror of the Ergast dataset.
// Nothing here is hard-coded, and team colours are not invented: the bar is
// neutral unless the standings row carries a colour, because Jolpica does not
// publish one and guessing would be a fabrication.
Item {
  id: root

  property var championship: ({})
  property string nowLabel: ""
  readonly property var drivers: championship && championship.drivers ? championship.drivers : []
  readonly property var constructors: championship && championship.constructors ? championship.constructors : []
  readonly property var next: championship && championship.next ? championship.next : null
  readonly property var previous: championship && championship.previous ? championship.previous : null
  readonly property var previousResults: championship && championship.previousResults ? championship.previousResults : []

  implicitWidth: parent ? parent.width : 0
  // The height the content actually needs: the next-race card, the last result
  // and the two full championship tables. The panel scrolls, so this is
  // measured rather than fixed.
  implicitHeight: {
    var h = (nextCard.visible ? nextCard.height : 0)
    h += (prevCard.visible ? prevCard.height : 0)
    h += (nextCard.visible || prevCard.visible) ? Style.space(10) * ((nextCard.visible ? 1 : 0) + (prevCard.visible ? 1 : 0)) : 0
    h += tables.height + ((nextCard.visible || prevCard.visible) ? Style.space(12) : 0)
    return h
  }

  readonly property real rowHeight: Math.round(Style.spacing.sm + Style.font.bodySmall * 1.7)

  // ---- next race ---------------------------------------------------------
  Item {
    id: nextCard
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    height: nextCol.implicitHeight + Style.space(10)
    visible: root.next !== null

    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius > 0 ? Style.cornerRadius : 0
      color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.05)
      border.width: 1
      border.color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.12)
    }

    Column {
      id: nextCol
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: Style.space(8)
      spacing: Style.spacing.xxs

      SectionLabel { text: "Next race" }

      Text {
        width: parent.width
        text: root.next ? root.next.name : ""
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.subtitle
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        text: root.next ? root.next.circuitName : ""
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        elide: Text.ElideRight
      }

      Row {
        spacing: Style.space(8)
        visible: root.nowLabel.length > 0
        Text {
          text: root.next ? (root.next.date + " " + (root.next.time || "").substring(0, 5) + " UTC") : ""
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }
      }

      Text {
        visible: root.nowLabel.length > 0
        text: "starts in " + root.nowLabel
        color: Color.accent
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }
    }
  }

  // ---- last race result --------------------------------------------------
  Item {
    id: prevCard
    anchors.top: nextCard.visible ? nextCard.bottom : parent.top
    anchors.topMargin: Style.space(10)
    anchors.left: parent.left
    anchors.right: parent.right
    height: prevCol.implicitHeight + Style.space(10)
    visible: root.previous !== null && root.previousResults.length > 0

    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius > 0 ? Style.cornerRadius : 0
      color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.05)
      border.width: 1
      border.color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.12)
    }

    Column {
      id: prevCol
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: Style.space(8)
      spacing: Style.spacing.xxs

      SectionLabel { text: root.previous ? ("Last race \u00b7 " + root.previous.name) : "Last race" }

      Repeater {
        model: root.previousResults.slice(0, 3)
        delegate: Row {
          required property var modelData
          width: prevCol.width
          spacing: Style.space(6)
          Text {
            width: Style.space(16); horizontalAlignment: Text.AlignRight
            text: "P" + (modelData.position || "")
            color: Color.muted; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
          }
          Text {
            width: Style.space(30)
            text: modelData.code || ""
            color: Color.foreground; font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall; font.bold: true
          }
          Text {
            width: parent.width - Style.space(52)
            text: modelData.name || ""
            color: Color.muted; font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight
          }
        }
      }
    }
  }

  // ---- championship tables ----------------------------------------------
  Item {
    id: tables
    anchors.top: prevCard.visible ? prevCard.bottom : (nextCard.visible ? nextCard.bottom : parent.top)
    anchors.topMargin: Style.space(12)
    anchors.left: parent.left
    anchors.right: parent.right
    // Sized to its contents rather than filling: the panel scrolls, and a
    // stretched table would leave a gap under the last row.
    height: Math.max(driverCol.implicitHeight, teamCol.implicitHeight)

    // Drivers
    Column {
      id: driverCol
      anchors.top: parent.top
      anchors.left: parent.left
      width: (parent.width - Style.space(12)) / 2
      spacing: Style.spacing.xxs

      SectionLabel { text: "Drivers" }

      Repeater {
        // Every row, not a truncated few: the panel scrolls, so there is no reason
        // to hide the bottom of the championship.
        model: root.drivers
        delegate: Row {
          required property var modelData
          required property int index
          width: driverCol.width
          height: root.rowHeight
          Text {
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(14); horizontalAlignment: Text.AlignRight
            text: String(modelData.position)
            color: index < 3 ? Color.accent : Color.muted
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
          }
          Text {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - Style.space(50)
            leftPadding: Style.space(4)
            text: (modelData.name || "").toUpperCase()
            color: Color.foreground
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
            elide: Text.ElideRight
          }
          Text {
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            width: Style.space(32)
            text: String(Math.round(modelData.points))
            color: Color.foreground
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
        }
      }
    }

    // Constructors
    Column {
      id: teamCol
      anchors.top: parent.top
      anchors.left: driverCol.right
      anchors.leftMargin: Style.space(12)
      anchors.right: parent.right
      spacing: Style.spacing.xxs

      SectionLabel { text: "Constructors" }

      Repeater {
        model: root.constructors
        delegate: Row {
          required property var modelData
          required property int index
          width: teamCol.width
          height: root.rowHeight
          Text {
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(14); horizontalAlignment: Text.AlignRight
            text: String(modelData.position)
            color: index < 3 ? Color.accent : Color.muted
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
          }
          Text {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - Style.space(50)
            leftPadding: Style.space(4)
            text: (modelData.name || "").toUpperCase()
            color: Color.foreground
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
            elide: Text.ElideRight
          }
          Text {
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            width: Style.space(32)
            text: String(Math.round(modelData.points))
            color: Color.foreground
            font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
        }
      }
    }
  }
}
