import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// The F1 panel.
//
// Two modes, chosen by what the service reports rather than by the clock:
// a live session shows the circuit map, the classification and race control;
// with nothing running it shows the next race, the last result and the
// championship tables. Replay is a third, visibly-labelled mode.
//
// Three structural notes, all of them load-bearing and all learned the hard way:
//
//   qs.Ui.Panel is a plain Item. It has no contentItem, and the bar's popout
//   coordinator sizes a panel from its children.
//
//   A Panel with no KeyboardPanel inside it never appears. Panel is only the
//   open/close state machine; KeyboardPanel is the layer-shell surface that
//   actually gets mapped. With content as direct children of Panel the widget
//   reported itself open, created a surface, and drew nothing.
//
//   The components sit next to this file rather than in a subdirectory, so
//   they resolve through the implicit same-directory import. A directory import
//   with a qmldir resolved unreliably: Quickshell's AOT scanner registered the
//   types progressively, so the Loader the bar widget uses to open this panel
//   could fail on whichever type it had not reached yet.
Panel {
  id: root
  moduleName: "f1.omarchy"
  ipcTarget: "f1.omarchy"
  manageIpc: false

  // Injected by the bar widget. KeyboardPanel needs the anchor to place itself
  // under the widget; the identity is what the bar's popout coordinator keys on.
  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property var svc: bar && bar.shell ? bar.shell.serviceFor("f1.omarchy") : null

  readonly property bool live: svc ? (svc.isLive || svc.isReplay) : false
  readonly property bool replay: svc ? svc.isReplay : false
  property int selectedNumber: -1

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  // Width tracks the user's font scale, so a larger base font gives more room
  // rather than cramped columns.
  readonly property int bodyWidth: Math.round(700 * Style.fontScale)
  readonly property int mapHeight: Math.round(300 * Style.fontScale)

  // The panel is a compact window onto the data, not a printout: it is capped
  // and the rest is reached by scrolling. Without the cap the idle view grows
  // to the full height of both championship tables -- nearly 900px -- which is
  // most of the screen and leaves the popup looking like a document.
  //
  // The cap is set so the live layout's important part still fits above the
  // fold: header, status strip and the full map and classification, with race
  // control just below.
  readonly property int maxBodyHeight: Math.round(560 * Style.fontScale)

  // Section heights, published so the surface can be sized from what the
  // content needs. An id declared inside a child component is not reachable
  // from the root, so each section publishes its own.
  readonly property real headerHeight: header.implicitHeight
  readonly property real statusHeight: statusStrip.height
  readonly property real raceControlHeight: visible ? raceControl.implicitHeight : 0

  // Geometry report for the bar widget's debug IPC, so a panel that fails to
  // appear can be diagnosed without attaching a debugger to the shell.
  readonly property string geometryReport: JSON.stringify({
    bodyWidth: bodyWidth,
    bodyHeight: Math.round(content.implicitHeight),
    cardWidth: surface.contentWidth,
    cardHeight: surface.contentHeight,
    hasAnchor: root.anchorItem !== null,
    hasBar: root.bar !== null,
    opened: root.opened,
    scrollContent: Math.round(scroll.contentHeight),
    scrollViewport: Math.round(scroll.height),
    scrollBarPolicy: scrollBar.policy,
    scrollBarWidth: Math.round(scrollBar.width),
    scrollBarVisible: scrollBar.visible
  })

  // ---- scrolling ---------------------------------------------------------
  //
  // Exposed as functions rather than reached into: the content lives inside
  // the surface's own window, so it is not traversable from outside the
  // component. These also give the keyboard a way to page the panel.
  function scrollMetrics() {
    return {
      contentHeight: scroll.contentHeight,
      viewport: scroll.height,
      y: scroll.contentY
    }
  }

  function scrollBy(dy) {
    var max = Math.max(0, scroll.contentHeight - scroll.height)
    scroll.contentY = Math.max(0, Math.min(scroll.contentY + dy, max))
    return scroll.contentY
  }

  // ---- selection ---------------------------------------------------------
  function firstNumber() {
    if (!svc || !svc.drivers || svc.drivers.length === 0) return -1
    return svc.drivers[0].number
  }

  function selectedIndex() {
    if (!svc || !svc.drivers || root.selectedNumber <= 0) return -1
    for (var i = 0; i < svc.drivers.length; i++) {
      if (svc.drivers[i].number === root.selectedNumber) return i
    }
    return -1
  }

  function step(delta) {
    if (!svc || !svc.drivers || svc.drivers.length === 0) return
    var list = svc.drivers
    var idx = selectedIndex()
    if (idx < 0) idx = 0
    var next = idx + delta
    if (next < 0) next = 0
    if (next >= list.length) next = list.length - 1
    root.selectedNumber = list[next].number
  }

  // ---- countdown ---------------------------------------------------------
  // Recomputed here rather than in the service so it keeps ticking even if the
  // service is restarting.
  property int tick: 0
  Timer {
    interval: 30000
    repeat: true
    running: true
    onTriggered: root.tick++
  }

  function countdownLabel() {
    if (!svc) return ""
    var n = svc.nextRaceRow
    if (!n || !n.date) return ""
    var parts = String(n.time || "00:00:00Z").split(":")
    var utc = Date.UTC(
      Number(n.date.substring(0, 4)),
      Number(n.date.substring(5, 7)) - 1,
      Number(n.date.substring(8, 10)),
      Number(parts[0]), Number(parts[1]), 0)
    var ms = utc - Date.now()
    if (ms <= 0) return "now"
    var mins = Math.floor(ms / 60000)
    var d = Math.floor(mins / 1440)
    var h = Math.floor((mins % 1440) / 60)
    var m = mins % 60
    if (d > 0) return d + "d " + h + "h"
    if (h > 0) return h + "h " + m + "m"
    return m + "m"
  }

  // ---- surface -----------------------------------------------------------
  KeyboardPanel {
    id: surface
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    // The surface is as tall as the content, up to the screen; beyond that the
    // Flickable scrolls, which is how the bottom of the standings is reached.
    contentWidth: surface.fittedContentWidth(root.bodyWidth)
    contentHeight: surface.fittedContentHeight(content.implicitHeight, root.maxBodyHeight)

    // PanelKeyCatcher owns keyboard focus inside the surface, so the
    // classification's keys arrive here rather than on a focused list row.
    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) {
        if (root.live) root.step(-dy)
      }
      onActivateRequested: {
        if (!root.live) return
        root.selectedNumber = root.selectedNumber > 0 ? -1 : root.firstNumber()
      }
      onReturnRequested: onActivateRequested()
    }

    // One Flickable owns vertical scrolling for the panel, so the bottom of the
    // championship tables is always reachable with the wheel. The live
    // classification keeps its own inner ListView; a wheel gesture goes to
    // whichever of the two is under the pointer.
    Flickable {
      id: scroll
      // Named so the end-to-end harness can find it and prove the content
      // actually scrolls, rather than only proving it is taller than the card.
      objectName: "panelScroll"
      anchors.fill: parent
      contentWidth: width
      contentHeight: content.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      // Slow enough that one flick travels a readable distance over twenty
      // rows, rather than slingshotting past the end.
      flickDeceleration: 4000
      maximumFlickVelocity: 1400

      // Left at the shell's default width and colour, so it looks like every
      // other Omarchy scrollbar rather than a custom one.
      ScrollBar.vertical: ScrollBar {
        id: scrollBar
        policy: scroll.contentHeight > scroll.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
      }

      // One Column owns the vertical rhythm through its own `spacing`; QML
      // positioners skip invisible children entirely, so hiding a section is
      // enough and no manual margin bookkeeping is needed.
      Column {
        id: content
        width: scroll.width - (scrollBar.policy === ScrollBar.AlwaysOff ? 0 : scrollBar.width)
        spacing: Style.spacing.lg

        // ===== header =====
        Column {
          id: header
          width: parent.width
          spacing: Style.spacing.xxs

          Item {
            width: parent.width
            height: Math.max(replayBadge.height, eyebrowText.implicitHeight)

            F1FlagIcon {
              id: brandIcon
              anchors.verticalCenter: parent.verticalCenter
              iconSize: Math.max(8, Math.round(eyebrowText.implicitHeight * 1.1))
              colour: root.live ? Color.urgent : Color.muted
            }

            Text {
              id: eyebrowText
              anchors.left: brandIcon.right
              anchors.leftMargin: Style.space(4)
              anchors.verticalCenter: parent.verticalCenter
              text: "Formula 1"
              color: root.live ? Color.urgent : Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              font.capitalization: Font.AllUppercase
              font.letterSpacing: 1.2
            }

            Rectangle {
              id: replayBadge
              visible: root.replay
              width: replayText.width + Style.space(6)
              height: Style.font.caption + Style.space(2)
              radius: height / 2
              color: Qt.rgba(Color.urgent.r, Color.urgent.g, Color.urgent.b, 0.2)
              anchors.left: eyebrowText.right
              anchors.leftMargin: Style.spacing.sm
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
            text: {
              if (root.live && root.svc) {
                if (root.svc.meeting.length > 0) return root.svc.meeting
                if (root.svc.circuit.length > 0) return root.svc.circuit
                return root.svc.sessionLabel
              }
              if (root.svc && root.svc.nextRaceRow) return root.svc.nextRaceRow.name
              return "No session"
            }
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.heading
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            text: {
              if (root.live && root.svc) return root.svc.circuit
              if (root.svc && root.svc.nextRaceRow) return root.svc.nextRaceRow.circuitName
              return ""
            }
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
          }
        }

        // ===== live: session status strip =====
        Item {
          id: statusStrip
          width: parent.width
          height: visible ? chips.implicitHeight : 0
          visible: root.live && root.svc !== null

          Row {
            id: chips
            anchors.fill: parent
            spacing: Style.spacing.xl

            StatChip {
              label: "Session"
              value: root.svc ? root.svc.sessionLabel : ""
              visible: value.length > 0
            }
            StatChip {
              label: "Lap"
              value: root.svc && root.svc.totalLaps > 0
                ? (root.svc.lap + " / " + root.svc.totalLaps)
                : (root.svc ? String(root.svc.lap) : "")
              visible: root.svc && root.svc.lap > 0
            }
            StatChip {
              label: "Track"
              value: root.svc ? (root.svc.effectiveTrackStatus || "–") : ""
              valueColor: root.svc && root.svc.effectiveTrackStatus === "Green"
                ? Color.accent : Color.foreground
            }
            StatChip {
              label: "Air"
              value: root.svc && root.svc.airTemp.length > 0 ? (root.svc.airTemp + "°C") : ""
              visible: value.length > 0
            }
            StatChip {
              label: "Track"
              value: root.svc && root.svc.trackTemp.length > 0 ? (root.svc.trackTemp + "°C") : ""
              visible: value.length > 0
            }
            StatChip {
              label: "Wind"
              value: root.svc && root.svc.windSpeed.length > 0 ? root.svc.windSpeed : ""
              visible: value.length > 0
            }
          }
        }

        // ===== live: circuit map + classification =====
        Item {
          id: liveBody
          width: parent.width
          height: visible ? root.mapHeight : 0
          visible: root.live

          // The map is square; the classification takes the rest of the row and
          // scrolls its own rows.
          Item {
            width: root.mapHeight
            height: root.mapHeight

            TrackMap {
              anchors.fill: parent
              service: root.svc
              outline: root.svc ? root.svc.outline : null
              positions: root.svc ? root.svc.positions : []
              circuitName: root.svc ? root.svc.circuit : ""
            }
          }

          Item {
            anchors.left: parent.left
            anchors.leftMargin: root.mapHeight + Style.spacing.xl
            anchors.right: parent.right
            height: root.mapHeight

            DriverList {
              anchors.fill: parent
              drivers: root.svc ? root.svc.drivers : []
              selectedNumber: root.selectedNumber
              // Lets the list keep the keyboard-selected row on screen.
              selectedIndex: root.selectedIndex()
              onSelected: function(number) {
                root.selectedNumber = root.selectedNumber === number ? -1 : number
              }
            }
          }
        }

        // ===== live: race control =====
        RaceControl {
          id: raceControl
          width: parent.width
          height: visible ? implicitHeight : 0
          visible: root.live
          messages: root.svc ? root.svc.raceControl : []
        }

        // ===== idle: championship =====
        Item {
          id: idleBody
          width: parent.width
          height: visible ? championship.implicitHeight : 0
          visible: !root.live

          Championship {
            id: championship
            anchors.fill: parent
            championship: root.svc ? root.svc.championship : ({})
            nowLabel: root.svc && !root.live ? root.countdownLabel() : ""
          }
        }

        // Shortcut hint, so the keys are discoverable without the README. It
        // lives in the scroll content rather than floating over it, so it never
        // sits on top of the rows.
        Item {
          width: parent.width
          height: visible ? hintText.implicitHeight : 0
          visible: root.live

          Text {
            id: hintText
            anchors.right: parent.right
            text: "↑↓ select · enter highlight · scroll · esc close"
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            opacity: 0.7
          }
        }
      }
    }
  }
}
