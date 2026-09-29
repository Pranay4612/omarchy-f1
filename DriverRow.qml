import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

// One row of the live classification: position, code, gap, tyre, plus a
// throttle trace that makes a live tower feel alive.
//
// Team colour is a thin bar, not a flood: the text has to stay the thing you
// read, and a row of twenty solid blocks would out-shout the data.
Item {
  id: root

  required property var driver
  required property bool selected
  required property bool dimmed
  required property real rowHeight

  signal activated()

  readonly property var d: driver
  readonly property string posText: d && d.position ? String(d.position) : "\u2013"
  readonly property string code: d ? (d.tla || d.name || "") : ""
  readonly property bool isLeader: d && d.position === 1
  readonly property bool hasGap: d && d.gap !== null && d.gap !== undefined

  function gapText() {
    if (!d) return "\u2013"
    // The feed sends an empty string for the leader, which parses to null.
    // Treat a zero gap as the leader too, so a normalised snapshot that
    // carries 0.0 does not render the leader as "+0.000".
    if (d.position === 1) return "LEADER"
    if (d.gap === null || d.gap === undefined) {
      if (d.interval !== null && d.interval !== undefined) return "+" + d.interval.toFixed(3)
      return "\u2013"
    }
    return "+" + d.gap.toFixed(3)
  }

  function intervalText() {
    if (!d) return ""
    if (d.interval === null || d.interval === undefined) return ""
    if (d.position === 1) return ""
    return "+" + d.interval.toFixed(3)
  }

  function tyreText() {
    if (!d) return ""
    if (d.pit) return "PIT"
    if (!d.tyre) return ""
    var c = d.tyre.charAt(0) + d.tyre.charAt(1)
    return d.tyreAge > 0 ? c + " " + d.tyreAge : c
  }

  implicitWidth: parent ? parent.width : 0
  height: rowHeight

  Rectangle {
    anchors.fill: parent
    radius: Style.cornerRadius > 0 ? Math.min(Style.cornerRadius, Style.space(6)) : 0
    color: root.selected
      ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.16)
      : "transparent"
    Behavior on color { ColorAnimation { duration: 120 } }
  }

  // Team colour as a left-edge accent. anchors.fill would fight the explicit
  // width and paint the whole row, which drowns the text.
  Rectangle {
    anchors.left: parent.left
    anchors.leftMargin: -1
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(2)
    height: parent.height * 0.62
    radius: width / 2
    color: root.d && root.d.colour ? root.d.colour : "transparent"
  }

  Row {
    anchors.fill: parent
    anchors.leftMargin: Style.space(6)
    anchors.rightMargin: Style.space(6)
    spacing: Style.space(4)

    // position
    Item {
      width: Style.space(20)
      height: parent.height
      Text {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        horizontalAlignment: Text.AlignRight
        text: root.posText
        color: root.selected ? Color.accent : Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
      }
    }

    // driver code
    Item {
      width: Style.space(30)
      height: parent.height
      Text {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        text: root.code
        color: root.dimmed ? Color.muted : Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }
    }

    // gap to leader
    Item {
      width: Style.space(58)
      height: parent.height
      Text {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        horizontalAlignment: Text.AlignRight
        text: root.gapText()
        color: root.dimmed ? Color.muted : Color.foreground
        font.family: Style.font.family
        font.pixelSize: root.isLeader ? Style.font.caption : Style.font.body
        opacity: root.isLeader ? 0.7 : 1.0
        elide: Text.ElideRight
      }
    }

    // interval to the car ahead
    Item {
      width: Style.space(50)
      height: parent.height
      visible: !root.isLeader
      Text {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        horizontalAlignment: Text.AlignRight
        text: root.intervalText()
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
    Item {
      width: Style.space(50)
      height: parent.height
      visible: root.isLeader
    }

    // throttle / brake trace
    Item {
      width: Style.space(20)
      height: parent.height
      visible: root.d && (root.d.throttle !== null && root.d.throttle !== undefined)
      Rectangle {
        id: thr
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.space(4)
        height: Style.space(3)
        radius: height / 2
        color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.14)
      }
      Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.space(4)
        height: Style.space(3)
        radius: height / 2
        width: parent.width * (root.d && root.d.throttle ? root.d.throttle / 255 : 0)
        color: Color.accent
        opacity: 0.75
        Behavior on width { NumberAnimation { duration: 90 } }
      }
    }

    // tyre
    Item {
      width: Style.space(36)
      height: parent.height
      Text {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        horizontalAlignment: Text.AlignRight
        text: root.tyreText()
        color: root.d && root.d.pit ? Color.urgent : Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        elide: Text.ElideRight
      }
    }
  }

  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.LeftButton
    cursorShape: Qt.PointingHandCursor
    onClicked: root.activated()
  }
}
