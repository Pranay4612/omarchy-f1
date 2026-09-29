import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

// The live circuit map.
//
// The outline and the car coordinates come from the same feed in the same
// per-circuit frame, so a marker is drawn exactly where the feed said the car
// is. There is no mapping, projection or best-guess step between the two.
//
// Performance shape, which is the whole trick:
//
//   * the track is a Canvas that is repainted only when the outline or the
//     size changes -- a few times per session, not per frame;
//   * the cars are ordinary Items on top, moved by QML's own property
//     animations, so they glide between telemetry samples at display rate
//     without the track being redrawn underneath them.
//
// A Canvas alone would have been too slow if markers were painted into it, and
// a Shape alone would have coupled the track's repaint to every car move. This
// keeps them independent.
//
// When no outline exists for a circuit the map says so. It does not draw a
// placeholder shape, because a plausible-looking loop with no data behind it is
// the one thing that would make this panel lie.
Item {
  id: root

  property var service: null
  property var outline: null
  property var positions: []
  property string circuitName: ""

  property int markerRadius: 7
  property bool showNumbers: true
  property bool showAbbreviations: true

  // Geometry in the feed's own coordinate frame, recomputed when the outline
  // changes. Both track and markers are scaled through it, so they cannot
  // disagree about where the circuit is.
  property var geometry: root.computeGeometry(outline && outline.points ? outline.points : null)
  readonly property bool hasOutline: geometry !== null

  function computeGeometry(points) {
    if (!points || points.length < 3) return null
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    for (var i = 0; i < points.length; i++) {
      var p = points[i]
      if (!p) continue
      if (p[0] < minX) minX = p[0]
      if (p[0] > maxX) maxX = p[0]
      if (p[1] < minY) minY = p[1]
      if (p[1] > maxY) maxY = p[1]
    }
    var side = Math.max(maxX - minX, maxY - minY)
    if (!(side > 0)) return null
    return { minX: minX, minY: minY, side: side, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 }
  }

  // The circuit box is fitted into the available space, preserving aspect.
  function boxSize() {
    var pad = Style.space(8)
    return Math.max(1, Math.min(width - pad * 2, height - pad * 2))
  }

  // Repaint the track only on a real change. The canvas is a separate item from
  // the markers precisely so that cars moving does not dirty it; without these
  // guards it would repaint on every binding re-evaluation.
  onOutlineChanged: if (track) track.requestPaint()
  onWidthChanged: if (track) track.requestPaint()
  onHeightChanged: if (track) track.requestPaint()

  // ---- the track ---------------------------------------------------------
  Item {
    id: stage
    anchors.centerIn: parent
    width: root.boxSize()
    height: root.boxSize()

    Canvas {
      id: track
      anchors.fill: parent
      antialiasing: true

      onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        if (!root.hasOutline) return

        var pts = root.outline.points
        if (!pts || pts.length < 3) return

        var s = stage.width / root.geometry.side
        var cx = stage.width / 2
        var cy = stage.height / 2

        // A closed circuit fills its bounding box, so a uniform scale is
        // correct here: stretching the two axes independently would distort
        // the shape.
        function toX(x) { return cx + (x - root.geometry.cx) * s }
        function toY(y) { return cy - (y - root.geometry.cy) * s }

        var fg = Color.foreground

        // Halo, then the line itself. Both derive from the theme's foreground
        // with an alpha, so neither needs a colour token of its own and both
        // follow a theme change for free.
        ctx.lineJoin = "round"
        ctx.lineCap = "round"

        ctx.beginPath()
        for (var i = 0; i < pts.length; i++) {
          var x = toX(pts[i][0])
          var y = toY(pts[i][1])
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
        }
        if (pts[0][0] !== pts[pts.length - 1][0] || pts[0][1] !== pts[pts.length - 1][1]) {
          ctx.lineTo(toX(pts[0][0]), toY(pts[0][1]))
        }
        ctx.strokeStyle = Qt.rgba(fg.r, fg.g, fg.b, 0.16)
        ctx.lineWidth = Math.max(6, Style.space(7))
        ctx.stroke()

        ctx.beginPath()
        for (var j = 0; j < pts.length; j++) {
          var px = toX(pts[j][0])
          var py = toY(pts[j][1])
          if (j === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
        }
        ctx.closePath()
        ctx.strokeStyle = fg
        ctx.lineWidth = Math.max(2, Style.space(2))
        ctx.stroke()
      }
    }

    // ---- the cars -------------------------------------------------------
    Repeater {
      id: markers
      model: root.hasOutline ? root.positions : []

      delegate: Item {
        id: marker
        required property var modelData
        required property int index
        parent: stage

        readonly property var row: modelData
        readonly property string tla: row && row[2] ? row[2] : ""
        readonly property string number: row && row[1] !== null && row[1] !== undefined ? String(row[1]) : ""
        readonly property real age: row && row[6] !== null && row[6] !== undefined ? Number(row[6]) : -1
        // A stale sample means the feed stopped telling us about this car:
        // red flag, garage, or a dropped packet. It is dimmed rather than
        // hidden, and never left looking current.
        readonly property bool stale: age > 8

        readonly property real scale: stage.width / root.geometry.side

        x: row && row[4] !== null && row[5] !== null
           ? stage.width / 2 + (row[4] - root.geometry.cx) * scale - width / 2
           : -4000
        y: row && row[4] !== null && row[5] !== null
           ? stage.height / 2 - (row[5] - root.geometry.cy) * scale - height / 2
           : -4000

        // Raw samples arrive several times a second; the car should glide
        // between them rather than teleport. This is the only smoothing, and
        // it interpolates between two positions the feed actually reported --
        // it never invents one.
        Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutQuad } }
        Behavior on y { NumberAnimation { duration: 150; easing.type: Easing.OutQuad } }

        width: root.markerRadius * 2
        height: root.markerRadius * 2
        visible: x > -3000 && y > -3000
        opacity: stale ? 0.35 : 1.0
        Behavior on opacity { NumberAnimation { duration: 220 } }

        Rectangle {
          anchors.centerIn: parent
          width: parent.width
          height: parent.height
          radius: width / 2
          // Team colours come from the feed's own DriverList.TeamColour, so a
          // livery or entrant change needs no plugin update and nothing is
          // hard-coded per season. The accent is the fallback.
          color: marker.row && marker.row[3] ? marker.row[3] : Color.accent
          border.width: 1
          border.color: Color.foreground
        }

        Text {
          anchors.centerIn: parent
          text: root.showNumbers ? marker.number : ""
          // The dot is the team's colour, so the label is knocked out of it
          // rather than themed, which keeps contrast on both light and dark
          // liveries.
          color: "#000000"
          font.family: Style.font.family
          font.pixelSize: Math.round(root.markerRadius * 1.2)
          font.bold: true
        }

        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          anchors.top: parent.top
          anchors.topMargin: -Style.space(5)
          text: root.showAbbreviations ? marker.tla : ""
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }
    }
  }

  // ---- unlearned-circuit state -------------------------------------------
  Column {
    anchors.centerIn: parent
    spacing: Style.space(4)
    visible: !root.hasOutline
    width: parent.width - Style.space(20)

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: root.circuitName.length > 0 ? root.circuitName : "No circuit"
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }

    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
      text: "No track outline for this circuit yet. It is learned from the cars' own position data during a live session."
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      lineHeight: 1.25
    }
  }
}
