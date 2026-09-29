// End-to-end harness. Not part of the shipped plugin.
//
// Mounts the real Service.qml and the real Panel.qml, with only the shell
// facade stubbed, so the panel is exercised exactly as Omarchy would drive it.
// This is the test that catches what a lint cannot: a wrong property name on a
// live object, a component that throws at runtime, a layout that does not fit.
//
// Panel.qml is loaded through a Loader by URL rather than by name on purpose.
// The harness also imports qs.Ui for its theme tokens, and an explicit import
// outranks the implicit same-directory one, so naming `Panel` here would
// silently resolve to qs.Ui.Panel -- the empty base class -- and the harness
// would pass while testing nothing. This is also the exact path the real bar
// widget uses to open the panel, so the harness exercises the same loader.
//
//   scripts/panel-test.sh          render, assert and report
//   scripts/panel-test.sh --shot   also write design/shots/panel-e2e.png
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

Item {
  id: root
  width: 820
  height: 760
  property string shotPath: Quickshell.env("F1_PANEL_SHOT") || ""
  property bool panelLoaded: false
  property bool ok: false
  property string failure: ""

  Rectangle {
    anchors.fill: parent
    color: Color.background
  }

  // --- the plugin's own service, unmodified -----------------------------
  Service {
    id: service
    // The harness supplies a prepared snapshot; do not start a second process.
    autoStart: false
  }

  // --- the smallest stand-in for the shell facade -----------------------
  // The panel reaches the service only through bar.shell.serviceFor(id), and
  // reads a few colours off the bar, so that is all the stub has to provide.
  QtObject {
    id: shellStub
    function serviceFor(id) { return id === "io.github.pranay4612.omarchy-f1" ? service : null }
  }
  QtObject {
    id: barStub
    property var shell: shellStub
    property color barForeground: Color.foreground
    property color foreground: Color.foreground
    property color background: Color.background
    property color urgent: Color.urgent
    property bool vertical: false
    property int barSize: 30
    property string position: "top"
    // KeyboardPanel calls these on open; the real PluginBarApi has them, so
    // the stub does too, or the harness fails for a reason production does not.
    property var activePopout: null
    function requestPopout(owner) {}
    function releasePopout(owner) {}
    function switchPanelFrom(owner, direction) { return false }
  }

  // --- the real panel, by URL ------------------------------------------
  Loader {
    id: panelLoader
    anchors.fill: parent
    // An explicit file URL, taken from the service's own resolved plugin
    // directory. Qt.resolvedUrl resolves against the QML import path in some
    // engine configurations -- it produced "qs:@/qs/Panel.qml" here -- and a
    // harness that quietly loads the wrong file is worse than no harness.
    source: service.pluginDir + "/Panel.qml"
    onLoaded: {
      var p = item
      if (!p) return
      if ("bar" in p) p.bar = barStub
      if ("settings" in p) p.settings = ({})
      // The bar widget injects the button it anchors under; without it the
      // surface has nothing to place itself against.
      if ("anchorItem" in p) p.anchorItem = root
      if ("hostWidget" in p) p.hostWidget = root
      // Open it: a closed panel would render nothing and prove nothing.
      if (typeof p.open === "function") p.open()
      root.panelLoaded = true
    }
  }

  // The Loader reports failures through status, not the log, so surface them.
  Connections {
    target: panelLoader
    function onStatusChanged() {
      console.log("PANEL_LOADER status=" + panelLoader.status +
                  " error=" + (panelLoader.status === Loader.Error ? panelLoader.errorString : "none") +
                  " url=" + panelLoader.source)
    }
  }

  Component.onCompleted: Qt.callLater(function() { settle.restart() })

  Timer {
    id: settle
    interval: 1500
    repeat: false
    onTriggered: root.check()
  }

  function check() {
    var missing = []
    if (!panelLoaded) missing.push("Panel.qml did not load")
    if (!service.hasData) missing.push("service has no data")
    if (service.drivers.length === 0) missing.push("no drivers in the snapshot")
    if (service.positions.length === 0) missing.push("no car positions")
    if (!service.effectiveTrackStatus.length) missing.push("no track status")
    if (service.lap <= 0) missing.push("no lap count")
    if (service.raceControl.length === 0) missing.push("no race control")

    var p = panelLoader.item
    // Sizing lives on the KeyboardPanel surface, not on the Panel's implicit
    // size: qs.Ui.Panel is a bare Item whose content is hosted in the surface.
    var size = p ? (p.bodyWidth + "x" + Math.round(p.bodyHeight)) : "n/a"
    if (p && p.bodyWidth <= 0) missing.push("panel has no width")
    if (p && p.bodyHeight <= 0) missing.push("panel has no height")
    if (p && !p.anchorItem) missing.push("panel has no anchorItem")

    // Scrolling has to be demonstrated, not inferred from a clipped card: the
    // standings are the whole point of reaching the bottom.
    // The service's script path has to be a real filesystem path. When it was
    // left as a file:// URL the plugin looked perfectly healthy -- it read its
    // cached snapshot, the panel rendered, every assertion here passed -- while
    // the service it was supposed to launch never started at all. Checking the
    // path is what makes that class of failure visible.
    if (!service.serviceScript || service.serviceScript.indexOf("://") !== -1) {
      missing.push("serviceScript is not a filesystem path: " + service.serviceScript)
    }
    // Existence is not checkable from QML here -- this Quickshell build has no
    // FileIO singleton -- so scripts/panel-test.sh takes the path this harness
    // reports and actually launches it. Between the two, a service that cannot
    // be started fails the suite instead of being masked by a warm cache.
    console.log("PANEL_SERVICE " + service.serviceScript)

    if (p && typeof p.scrollMetrics === "function" && typeof p.scrollBy === "function") {
      var m = p.scrollMetrics()
      if (!(m.contentHeight > m.viewport)) missing.push("content is not scrollable")
      else {
        var to = p.scrollBy(140)
        if (to <= 0) missing.push("scrolling did not move the content")
        else {
          console.log("PANEL_SCROLL content=" + Math.round(m.contentHeight) +
                      " viewport=" + Math.round(m.viewport) + " scrolled 0 -> " + Math.round(to))
          p.scrollBy(-140)
        }
      }
    } else {
      missing.push("panel exposes no scroll API")
    }

    root.failure = missing.join("; ")
    root.ok = missing.length === 0
    console.log("PANEL_SIZE implicit=" + size + (pz ? "" : " (panel did not load)") +
                " loaded=" + panelLoaded +
                " drivers=" + service.drivers.length +
                " located=" + service.positions.length +
                " lap=" + service.lap + "/" + service.totalLaps +
                " track=" + service.effectiveTrackStatus +
                " rc=" + service.raceControl.length +
                " outline=" + (service.outline ? "yes" : "no"))
    var pz = panelLoader.item
    console.log("PANEL_TEST " + (root.ok ? "PASS" : "FAIL") +
                (root.failure.length ? " missing[" + root.failure + "]" : ""))
    if (root.shotPath.length > 0) shot.start()
    else Qt.callLater(Qt.quit)
  }

  Timer {
    id: shot
    interval: 400
    onTriggered: root.grabToImage(function(result) {
      result.saveToFile(root.shotPath)
      Qt.callLater(Qt.quit)
    })
  }
}
