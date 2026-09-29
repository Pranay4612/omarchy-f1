import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// The bar widget.
//
// The bar shows a chequered flag and nothing else — no race name, no
// countdown, no lap. Everything it used to spell out is in the tooltip on
// hover and in the panel, which is where text belongs; a bar is for telling
// you at a glance whether anything is happening, and the flag turning
// urgent-coloured is that signal.
//
// Middle click restarts the data service, which is the first thing to try when
// the numbers look wrong. Right click refreshes the championship data.
BarWidget {
  id: root
  moduleName: "io.github.pranay4612.omarchy-f1"

  readonly property var svc: bar && bar.shell ? bar.shell.serviceFor("io.github.pranay4612.omarchy-f1") : null

  // Icon edge length. Declared here rather than left to the icon's own
  // implicit size: the button is sized from this and the icon is then centred
  // in the button, and letting one be derived from the other while it is
  // anchored to it is a binding cycle that silently drops the widget.
  readonly property int iconSize: Math.round((bar ? bar.barSize : 30) * 0.52)

  // The bar carries the flag and nothing else: no race name, no countdown, no
  // lap. With the widget reduced to an icon there is no text left to elide or
  // measure, and the information that used to sit here lives in the tooltip and
  // the panel. What the bar is for is telling you at a glance whether anything
  // is happening -- and the flag turning urgent-coloured is that signal.
  function leaderLabel() {
    if (!svc || !svc.drivers || svc.drivers.length === 0) return ""
    for (var i = 0; i < svc.drivers.length; i++) {
      if (svc.drivers[i].position === 1) return "P1 " + (svc.drivers[i].tla || "")
    }
    return ""
  }

  function countdown() {
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
    if (d > 0) return d + "d " + h + "h"
    if (h > 0) return h + "h " + (mins % 60) + "m"
    return (mins % 60) + "m"
  }

  // With no text in the bar the tooltip is the only place the next race, the
  // countdown or the live lap is visible, so it carries the full detail.
  readonly property string displayText: ""

  function tooltipText() {
    if (!svc) return "Formula 1"
    if (svc.isLive) {
      var s = svc.sessionLabel + " \u00b7 " + (svc.circuit || "")
      if (svc.totalLaps > 0) s += "\nLap " + svc.lap + " of " + svc.totalLaps
      if (svc.effectiveTrackStatus) s += "\n" + svc.effectiveTrackStatus
      s += "\n" + svc.positions.length + " cars located"
      s += "\nClick: panel \u00b7 Middle: restart service"
      return s
    }
    if (svc.nextRaceRow) {
      var r = svc.nextRaceRow
      return r.name + "\n" + r.circuitName + "\n" + r.date + " " + String(r.time || "").substring(0, 5) + " UTC"
        + "\nstarts in " + countdown()
        + "\nClick: panel \u00b7 Middle: restart service \u00b7 Right: refresh data"
    }
    return "Formula 1\nClick: panel"
  }

  // ---- Panel lifecycle contract expected by the bar's popout coordinator.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }

  readonly property real openPanelIndicatorWidth: button.implicitWidth
  readonly property real openPanelIndicatorHeight: Math.max(Style.space(10), Math.round(Style.bar.iconSlot * 0.55))

  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: {
    // A capture path in the widget's settings means "replay this instead of
    // live", which the service needs before it starts.
    if (svc) {
      var capture = root.setting("replayCapture", "")
      if (capture && svc.replayCapture !== capture) svc.replayCapture = capture
    }
    injectPanel()
  }

  Component.onCompleted: {
    if (svc) {
      var capture = root.setting("replayCapture", "")
      if (capture) svc.replayCapture = capture
    }
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  IpcHandler {
    target: "io.github.pranay4612.omarchy-f1.widget"

    function open() { root.open() }
    function close() { root.close() }
    function toggle() { root.togglePanel() }

    // Reports whether the panel is actually mounted. A bar widget that renders
    // but whose panel silently fails to load looks identical to a broken click
    // handler, and this says which it is.
    function status(): string {
      var item = panelLoader.item
      return JSON.stringify({
        panelLoaded: item !== null && item !== undefined,
        panelSize: item ? (item.implicitWidth + "x" + item.implicitHeight) : null,
        panelOpened: item ? item.opened === true : null,
        hasService: root.svc !== null,
        mode: root.svc ? root.svc.mode : null,
        text: root.displayText,
        geometry: panelLoader.item ? panelLoader.item.geometryReport : null
      })
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // The button keeps its own behaviour -- click registration, tooltip, press
    // handling -- but not its label: the pill is an icon plus text, and the
    // built-in Text is centred on its own and cannot be joined to an icon.
    // keepSpace holds the button visible with an empty text.
    text: ""
    keepSpace: true
    // WidgetButton dims itself to zero when its own text is empty, on the
    // assumption that an empty button has nothing to show. This one does -- the
    // pill is drawn below as an icon plus text -- so the visibility flag is
    // overridden rather than left to the text.
    hasVisualContent: true
    horizontalMargin: 9
    verticalPadding: 8.75
    implicitWidth: root.iconSize + Style.spaceReal(horizontalMargin) * 2
    tooltipText: root.tooltipText()

    // Live is the one state that should stand out in the bar, so the flag takes
    // the urgent colour then and the ordinary foreground otherwise.
    readonly property color labelColour: (root.svc && root.svc.isLive)
      ? Color.urgent
      : (bar ? bar.barForeground : Color.foreground)

    F1FlagIcon {
      id: pill
      anchors.centerIn: parent
      // Sized through iconSize, and the button is sized from root.iconSize too,
      // so nothing here is derived from the button it is anchored to.
      iconSize: root.iconSize
      colour: button.labelColour

      Behavior on colour {
        enabled: !bar || bar.foregroundAnimationEnabled
        ColorAnimation { duration: 200 }
      }
    }

    onPressed: function(b) {
      if (!root.svc) { root.togglePanel(); return }
      if (b === Qt.MiddleButton) {
        root.svc.restartService()
      } else if (b === Qt.RightButton) {
        root.svc.restartService()
      } else {
        root.togglePanel()
      }
    }
  }
}
