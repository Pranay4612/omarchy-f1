// Preview harness. Not part of the shipped plugin. (name must be a valid QML type)
//
// Renders the real panel components against mock data so the visual design can
// be checked without a live session. Run with scripts/preview.sh.
import QtQuick
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Ui

// Components live alongside this file; the implicit same-directory import is
// what the real Panel.qml uses too.

import "dev-preview.js" as Mock

Item {
  id: root
  width: Mock.width
  height: Mock.height
  visible: true

  Rectangle {
    anchors.fill: parent
    color: Color.background
  }

  // Offscreen render path: with a save path in the environment, grab this item
  // to a PNG and exit. Used by scripts/preview.sh so design shots do not need a
  // layer-shell surface on the compositor.
  property string shotPath: Quickshell.env("F1_PREVIEW_SHOT") || ""
  Component.onCompleted: {
    if (shotPath.length > 0) shotTimer.start()
  }
  Timer {
    id: shotTimer
    interval: 900
    repeat: false
    onTriggered: root.grabToImage(function(result) {
      result.saveToFile(root.shotPath)
      Qt.callLater(Qt.quit)
    })
  }

  readonly property bool liveMode: Mock.mode === "live"
  property int selectedNumber: -1

  Column {
    id: column
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.spacing.panelPadding
    spacing: Style.spacing.lg

    Column {
      width: parent.width
      spacing: Style.spacing.xxs

      Row {
        width: parent.width
        spacing: Style.spacing.sm
        Text {
          text: "Formula 1"
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.capitalization: Font.AllUppercase
          font.letterSpacing: 1.2
          anchors.verticalCenter: parent.verticalCenter
        }
        Rectangle {
          visible: Mock.mode === "replay"
          width: replayText.width + Style.space(6)
          height: Style.font.caption + Style.space(2)
          radius: height / 2
          color: Qt.rgba(Color.urgent.r, Color.urgent.g, Color.urgent.b, 0.2)
          anchors.verticalCenter: parent.verticalCenter
          Text {
            id: replayText
            anchors.centerIn: parent
            text: "REPLAY"
            color: Color.urgent
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            font.capitalization: Font.AllUppercase
            font.bold: true
          }
        }
      }

      Text {
        width: parent.width
        text: Mock.headingFor()
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.display
        font.bold: true
        elide: Text.ElideRight
      }
      Text {
        width: parent.width
        text: Mock.subheadingFor()
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
      }
    }

    Row {
      width: parent.width
      spacing: Style.spacing.xl
      visible: root.liveMode

      StatChip { label: "Session"; value: Mock.sessionLabel }
      StatChip { label: "Lap"; value: Mock.lapText }
      StatChip { label: "Track"; value: Mock.trackStatus; valueColor: Mock.trackStatus === "Green" ? Color.accent : Color.foreground }
      StatChip { label: "Air"; value: Mock.airTemp }
      StatChip { label: "Track"; value: Mock.trackTemp }
      StatChip { label: "Wind"; value: Mock.windSpeed }
    }

    Row {
      width: parent.width
      spacing: Style.spacing.xl
      visible: root.liveMode
      height: Math.round(340 * Style.fontScale)

      Item { width: parent.height; height: parent.height
        TrackMap {
          anchors.fill: parent
          outline: Mock.outline
          positions: Mock.positions
          circuitName: Mock.circuit
        }
      }
      Item {
        width: parent.width - parent.height - Style.spacing.xl
        height: parent.height
        DriverList {
          anchors.fill: parent
          drivers: Mock.drivers
          selectedNumber: root.selectedNumber
          onSelected: function(n) { root.selectedNumber = root.selectedNumber === n ? -1 : n }
        }
      }
    }

    RaceControl {
      width: parent.width
      height: implicitHeight
      visible: root.liveMode
      messages: Mock.raceControl
    }

    Item {
      width: parent.width
      height: Math.round(360 * Style.fontScale)
      visible: !root.liveMode
      Championship {
        anchors.fill: parent
        championship: Mock.championship
        nowLabel: Mock.countdown
      }
    }
  }
}
