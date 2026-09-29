import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons

// The plugin's single data engine.
//
// Everything the UI shows comes from here, and here only. The QML layer never
// opens a socket, never calls a paid API and never holds a credential: it reads
// two files that the local Python service writes.
//
//   state.json      standings, calendar, race control, session metadata.
//                   Low rate: about once a second.
//   positions.json  where each car is. Small, rewritten at up to 10 Hz so the
//                   track map can move markers smoothly.
//
// Keeping positions in their own small file matters: re-parsing a 30 kB
// snapshot with 40 race-control messages ten times a second to move twenty
// dots would be wasteful, and the split keeps the map responsive.
Item {
  id: root

  // The shell injects these; `shell` is how the panel reaches this service.
  property var shell: null
  property var manifest: null

  readonly property string home: Quickshell.env("HOME")
  readonly property string cacheHome: {
    var x = Quickshell.env("XDG_CACHE_HOME")
    return (x && x.length > 0) ? x : home + "/.cache"
  }
  readonly property string stateDir: cacheHome + "/omarchy/f1"
  readonly property string statePath: stateDir + "/state.json"
  readonly property string positionsPath: stateDir + "/positions.json"

  // Set once the cache directory is known to exist; gates the FileView paths.
  property bool cacheReady: false

  // Absolute path to this plugin folder, derived from this file's own location
  // rather than an assumed install prefix. The shell does not inject a plugin
  // directory, and the plugin may be a git checkout anywhere.
  readonly property string pluginDir: Qt.resolvedUrl(".")

  // F1_PYTHON lets a user point at a specific interpreter without the plugin
  // assuming a virtualenv; the default is whatever `python3` resolves to.
  readonly property string pythonBin: {
    var override = Quickshell.env("F1_PYTHON")
    return (override && override.length > 0) ? override : "python3"
  }
  readonly property string serviceScript: Qt.resolvedUrl("bin/f1-service")

  // ------------------------------------------------------------- data model
  property var snapshot: ({})
  property var drivers: []
  property var championship: ({})
  property var outline: null

  // Live car positions, kept separate and deliberately small.
  property var positions: []
  property int positionsRevision: -1

  property bool serviceRunning: false
  property int restarts: 0
  property string lastError: ""

  // Set by the bar widget so a capture can be replayed without restarting.
  property string replayCapture: ""

  // The end-to-end test and the design harness both mount this service against
  // a prepared snapshot and must not spawn a second F1 process.
  property bool autoStart: true

  readonly property bool hasData: Object.keys(snapshot).length > 0
  readonly property bool stale: !hasData
  readonly property string mode: snapshot.mode || "offline"
  readonly property bool isLive: mode === "live"
  readonly property bool isReplay: mode === "replay"
  readonly property bool isIdle: mode === "idle" || mode === "offline"

  readonly property string sessionLabel: snapshot.sessionLabel || ""
  readonly property string sessionType: snapshot.session || ""
  readonly property string sessionStatus: snapshot.sessionStatus || ""
  readonly property string meeting: snapshot.meeting || ""
  readonly property string officialName: snapshot.officialName || ""
  readonly property string circuit: snapshot.circuit || ""
  readonly property string country: snapshot.country || ""
  readonly property int lap: snapshot.lap || 0
  readonly property int totalLaps: snapshot.totalLaps || 0
  readonly property string trackStatus: snapshot.trackStatus || ""
  readonly property string trackFlag: snapshot.trackFlag || ""
  readonly property string airTemp: snapshot.airTemp || ""
  readonly property string trackTemp: snapshot.trackTemp || ""
  readonly property string rainfall: snapshot.rainfall || ""
  readonly property string windSpeed: snapshot.windSpeed || ""
  readonly property var raceControl: snapshot.raceControl || []

  readonly property string nextRace: {
    var n = championship.next
    return n ? n.name : ""
  }
  readonly property var nextRaceRow: championship.next || null
  readonly property var previousRaceRow: championship.previous || null

  // ------------------------------------------------------------- file reads
  // Both files are written by this plugin's own service, into a per-user cache
  // directory, with atomic replaces and 0600 permissions. They are preloaded so
  // the panel is populated on the first frame rather than after the service's
  // first write, which is what makes a cold shell start instant.
  //
  // The path stays empty until the directory exists. A FileView that binds a
  // path under a directory that is not there yet sets up its watcher against
  // nothing, and then silently never sees the file when the service creates it
  // seconds later -- which looks exactly like a dead service.
  //
  // Every read is still treated as untrusted input: ingestState and
  // ingestPositions parse inside try/catch, ignore anything that is not an
  // object with the expected shape, and never let a field through unchecked.
  FileView {
    id: stateFile
    path: root.cacheReady ? root.statePath : ""
    preload: true
    watchChanges: true
    printErrors: false
    blockLoading: true

    // fileChanged only fires on a *change*, so the initial load is picked up
    // separately; without onLoaded a snapshot that already existed at shell
    // start (a warm start, or the test harness) would never be read.
    onLoaded: root.ingestState(text())
    onFileChanged: root.ingestState(text())
    onLoadFailed: {}
  }

  FileView {
    id: positionsFile
    path: root.cacheReady ? root.positionsPath : ""
    preload: true
    watchChanges: true
    printErrors: false
    blockLoading: true

    onLoaded: root.ingestPositions(text())
    onFileChanged: root.ingestPositions(text())
    onLoadFailed: {}
  }

  function ingestState(raw) {
    if (!raw || raw.length === 0) return
    var data
    try { data = JSON.parse(raw) } catch (e) { return }
    if (!data || typeof data !== "object") return
    snapshot = data
    drivers = Array.isArray(data.drivers) ? data.drivers : []
    championship = (data.championship && typeof data.championship === "object") ? data.championship : {}
    outline = (data.outline && typeof data.outline === "object") ? data.outline : null
    ageTick++
  }

  function ingestPositions(raw) {
    if (!raw || raw.length === 0) return
    var data
    try { data = JSON.parse(raw) } catch (e) { return }
    if (!data || !Array.isArray(data.drivers)) return
    positions = data.drivers
    positionsRevision = data.revision || 0
    liveTrackFlag = data.trackFlag || liveTrackFlag
    liveTrackStatus = data.trackStatus || liveTrackStatus
    positionAgeTick++
  }

  // Track status arrives on the high-rate file so the flag updates the instant
  // it changes, without waiting for the slow snapshot.
  property string liveTrackStatus: ""
  property string liveTrackFlag: ""
  readonly property string effectiveTrackStatus: liveTrackStatus || trackStatus
  readonly property string effectiveTrackFlag: liveTrackFlag || trackFlag

  // ------------------------------------------------------------- supervision
  property bool started: false
  property int ageTick: 0
  property int positionAgeTick: 0

  function startService() {
    if (root.serviceScript.length === 0) {
      root.lastError = "service script not found"
      return
    }
    var args = [root.pythonBin, root.serviceScript]
    if (root.replayCapture && root.replayCapture.length > 0) {
      args.push("--replay")
      args.push(root.replayCapture)
    }
    root.serviceRunning = true
    var proc = Quickshell.execDetached(args)
    root.lastError = ""
  }

  function stopService() {
    // Matched on the resolved script path, so this can never match an
    // unrelated process that merely shares the name.
    Quickshell.execDetached(["pkill", "-f", root.serviceScript])
  }

  function restartService() {
    root.stopService()
    root.serviceRunning = false
    startTimer.restart()
  }

  Timer {
    id: startTimer
    interval: 600
    repeat: false
    onTriggered: {
      if (!root.serviceRunning) {
        root.restarts++
        root.startService()
      }
    }
  }

  // The service is deliberately allowed to be long-lived, but not immortal: if
  // it dies (crash, reboot of a laptop mid-race, an exception escaping the
  // reader loop) the widget must not sit there showing a frozen snapshot.
  Timer {
    interval: 60000
    repeat: true
    running: root.started
    onTriggered: {
      // The service only publishes on startup, every few minutes while idle,
      // and at telemetry rate during a session. A snapshot that is merely old
      // is therefore not a fault, and restarting on that basis just kills a
      // healthy process and starts another. Only a live session that has gone
      // silent for a long time is a real failure.
      var saved = Number(root.snapshot.savedAt || 0)
      var age = saved > 0 ? (Date.now() / 1000 - saved) : -1
      if (root.isLive && age > 600 && root.restarts < 20) root.restartService()
    }
  }

  // --------------------------------------------------------------- freshness
  // Drives the "stale" styling and the countdown. A plain 1 Hz tick is enough:
  // the values come from the snapshot, so nothing is recomputed here.
  property int nowTick: 0
  Timer {
    interval: 1000
    repeat: true
    running: true
    onTriggered: root.nowTick++
  }
  readonly property real nowMs: nowTick > 0 ? Date.now() : 0
  readonly property int savedAgeSec: {
    var s = Number(root.snapshot.savedAt || 0)
    return s > 0 ? Math.max(0, Math.floor((Date.now() / 1000) - s)) : -1
  }

  // ------------------------------------------------------------------ lookups
  function driverById(id) {
    for (var i = 0; i < root.drivers.length; i++) {
      if (root.drivers[i].id === id) return root.drivers[i]
    }
    return null
  }

  function positionFor(id) {
    for (var i = 0; i < root.positions.length; i++) {
      if (root.positions[i][0] === id) return root.positions[i]
    }
    return null
  }

  // Normalised track bounds, computed once per outline so the map and the
  // markers agree on where (0,0) and (1,1) are.
  function trackGeometry(points) {
    if (!points || points.length < 3) return null
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    for (var i = 0; i < points.length; i++) {
      var p = points[i]
      if (p[0] < minX) minX = p[0]
      if (p[0] > maxX) maxX = p[0]
      if (p[1] < minY) minY = p[1]
      if (p[1] > maxY) maxY = p[1]
    }
    var w = Math.max(maxX - minX, 1e-6)
    var h = Math.max(maxY - minY, 1e-6)
    var side = Math.max(w, h)
    return {
      minX: minX, minY: minY, side: side,
      cx: (minX + maxX) / 2, cy: (minY + maxY) / 2,
      aspect: w / h
    }
  }

  // --------------------------------------------------------------- lifecycle
  Component.onCompleted: {
    root.started = true
    mkdirProc.running = true
    if (root.autoStart) startTimer.start()
  }

  Process {
    id: mkdirProc
    command: ["mkdir", "-p", root.stateDir]
    // Re-arm the readers whether or not the service is going to be started:
    // an already-populated cache should display on a cold shell regardless.
    onExited: (exitCode, exitStatus) => {
      if (exitCode === 0) {
        root.cacheReady = true
      } else {
        root.lastError = "could not create " + root.stateDir
      }
    }
  }

  onReplayCaptureChanged: {
    if (root.started) root.restartService()
  }

  // ------------------------------------------------------------------- IPC
  IpcHandler {
    target: "io.github.pranay4612.omarchy-f1"

    function refresh(): string { root.restartService(); return "ok" }
    function openPanel(): string {
      if (root.shell) root.shell.summon("io.github.pranay4612.omarchy-f1", {})
      return "ok"
    }
    function status(): string {
      return JSON.stringify({
        cacheReady: root.cacheReady,
        statePath: root.statePath,
        mode: root.mode,
        connected: !!(root.snapshot && root.snapshot.connected),
        session: root.sessionLabel,
        circuit: root.circuit,
        lap: root.lap,
        totalLaps: root.totalLaps,
        drivers: root.drivers.length,
        positioned: root.positions.length,
        trackStatus: root.effectiveTrackStatus,
        restarts: root.restarts,
        error: root.lastError
      })
    }
  }
}
