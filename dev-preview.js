// Mock data for the design preview. Not part of the shipped plugin.
//
// Every value here is fabricated for layout purposes only and is never shown
// as live data: the preview is a separate entry point that the service never
// loads, and the real panel only ever renders what the service wrote to the
// cache. The driver names are real 2026 entries so the columns are the right
// width; the gaps, coordinates and circuit are made up.

var width = 760
var height = 470
var mode = "idle"

// The header follows the mode, the way the real panel does: the live session
// when one is running, otherwise the next race.
var heading = "Azerbaijan Grand Prix"
var subheading = "Baku"
var sessionLabel = "RACE"
var circuit = "Baku"
var lapText = "32 / 57"
var trackStatus = "Yellow"
var airTemp = "24\u00b0C"
var trackTemp = "31\u00b0C"
var windSpeed = "12"
var countdown = "5d 14h"

function headingFor() {
  if (mode !== "live") return "Bahrain Grand Prix in Malaysia"
  return "Azerbaijan Grand Prix"
}
function subheadingFor() {
  if (mode !== "live") return "Sepang International Circuit"
  return "Baku"
}

function driver(number, tla, name, team, colour, pos, gap, interval, tyre, age, x, y) {
  return {
    id: String(number), number: String(number), tla: tla, name: name,
    team: team, colour: colour, position: pos,
    gap: gap, interval: interval, tyre: tyre, tyreAge: age,
    pit: "", retired: false, stopped: false,
    lastLap: "1:44.916", bestLap: "1:44.916", sectors: [],
    speed: 312, x: x, y: y, z: 0, posStatus: "OnTrack", posAge: 0.2,
    hasPosition: true, grid: pos, throttle: 200, brake: 0, newTyre: false,
    penalties: []
  }
}

// Stored as [x, y] pairs, which is the format the service writes. The map
// flattens to the interleaved form PathPolyline wants.
var outlinePoints = (function () {
  var pts = []
  var n = 140
  for (var i = 0; i <= n; i++) {
    var t = (i / n) * Math.PI * 2
    var r = 2400 + 620 * Math.sin(3 * t) + 180 * Math.cos(5 * t)
    pts.push([2400 + r * Math.cos(t), 1100 + 0.68 * r * Math.sin(t)])
  }
  return pts
})()

var outline = ({ key: "Baku", points: outlinePoints, length: 6003, learnedAt: 0 })

// [number, tla, name, team, colour, gap, interval, tyre, tyreAge]
var driverSpecs = [
  [1, "NOR", "Lando Norris", "McLaren", "#F47600", 0.0, null, "SOFT", 12],
  [3, "VER", "Max Verstappen", "Red Bull", "#4781D7", 1.842, 1.842, "MEDIUM", 9],
  [16, "LEC", "Charles Leclerc", "Ferrari", "#ED1131", 4.721, 2.879, "MEDIUM", 7],
  [81, "PIA", "Oscar Piastri", "McLaren", "#F47600", 7.103, 2.382, "HARD", 18],
  [44, "HAM", "Lewis Hamilton", "Ferrari", "#ED1131", 11.201, 4.098, "HARD", 21],
  [63, "RUS", "George Russell", "Mercedes", "#00D7B6", 15.887, 4.686, "SOFT", 5],
  [12, "ANT", "Kimi Antonelli", "Mercedes", "#00D7B6", 19.004, 3.117, "MEDIUM", 11],
  [43, "COL", "Esteban Ocon", "Alpine", "#00A1E8", 24.551, 5.547, "HARD", 24],
  [10, "GAS", "Pierre Gasly", "Alpine", "#00A1E8", 28.220, 3.669, "MEDIUM", 6],
  [23, "ALB", "Alexander Albon", "Williams", "#1868DB", 33.901, 5.681, "SOFT", 8],
  [5, "BOR", "Oliver Bearman", "Audi", "#F50537", 38.774, 4.873, "MEDIUM", 14],
  [55, "SAI", "Carlos Sainz", "Williams", "#1868DB", 43.120, 4.346, "HARD", 19],
  [30, "LAW", "Liam Lawson", "Racing Bulls", "#6C98FF", 48.339, 5.219, "SOFT", 4],
  [87, "BEA", "Oliver Bearman", "Haas", "#9C9FA2", 52.118, 3.779, "MEDIUM", 16],
  [31, "OCO", "Esteban Ocon", "Haas", "#9C9FA2", 57.902, 5.784, "HARD", 22],
  [6, "HAD", "Isack Hadjar", "Red Bull", "#4781D7", 62.551, 4.649, "MEDIUM", 10],
  [27, "HUL", "Nico Hulkenberg", "Audi", "#F50537", 68.004, 5.453, "SOFT", 3],
  [41, "LIN", "Liam Lawson", "Racing Bulls", "#6C98FF", 73.881, 5.877, "MEDIUM", 13],
  [11, "PER", "Oscar Piastri", "Cadillac", "#909090", 80.226, 6.345, "HARD", 20],
  [14, "ALO", "Fernando Alonso", "Aston Martin", "#229971", 86.994, 6.768, "MEDIUM", 9]
]

// Cars are spread around the circuit in position order, so the markers
// exercise real separation and real label placement.
var drivers = (function () {
  var n = outlinePoints.length
  var out = []
  for (var i = 0; i < driverSpecs.length; i++) {
    var d = driverSpecs[i]
    var p = outlinePoints[Math.floor((i / driverSpecs.length) * n) % n]
    out.push(driver(d[0], d[1], d[2], d[3], d[4], i + 1, d[5], d[6], d[7], d[8], p[0], p[1]))
  }
  return out
})()

// Marker rows use the compact array form the service writes.
var positions = (function () {
  var out = []
  for (var i = 0; i < drivers.length; i++) {
    var d = drivers[i]
    out.push([d.id, d.number, d.tla, d.colour, d.x, d.y, d.posAge, d.position])
  }
  return out
})()

var raceControl = [
  { Utc: "2026-09-26T12:44:02", Lap: 31, Category: "Flag", Flag: "YELLOW", Scope: "Sector", Sector: 2, Message: "YELLOW IN TRACK SECTOR 2" },
  { Utc: "2026-09-26T12:44:19", Lap: 31, Category: "Flag", Flag: "CLEAR", Scope: "Track", Message: "CLEAR TRACK" },
  { Utc: "2026-09-26T12:31:55", Lap: 29, Category: "Penalty", Message: "TIME PENALTY 5 SEC - CAR 3 - TIME TO CROSS LINE 2" },
  { Utc: "2026-09-26T12:20:04", Lap: 28, Category: "Other", Message: "PIT LANE OPEN" }
]

var championship = ({
  drivers: [
    { position: 1, name: "Andrea Kimi Antonelli", code: "ANT", points: 302, team: "Mercedes" },
    { position: 2, name: "George Russell", code: "RUS", points: 236, team: "Mercedes" },
    { position: 3, name: "Lewis Hamilton", code: "HAM", points: 199, team: "Ferrari" },
    { position: 4, name: "Lando Norris", code: "NOR", points: 186, team: "McLaren" },
    { position: 5, name: "Charles Leclerc", code: "LEC", points: 179, team: "Ferrari" },
    { position: 6, name: "Max Verstappen", code: "VER", points: 168, team: "Red Bull" },
    { position: 7, name: "Oscar Piastri", code: "PIA", points: 154, team: "McLaren" },
    { position: 8, name: "Isack Hadjar", code: "HAD", points: 131, team: "Red Bull" }
  ],
  constructors: [
    { position: 1, name: "Mercedes", points: 538 },
    { position: 2, name: "Ferrari", points: 378 },
    { position: 3, name: "McLaren", points: 306 },
    { position: 4, name: "Red Bull", points: 263 },
    { position: 5, name: "RB F1 Team", points: 83 },
    { position: 6, name: "Williams", points: 71 },
    { position: 7, name: "Alpine", points: 54 },
    { position: 8, name: "Aston Martin", points: 41 }
  ],
  next: {
    name: "Bahrain Grand Prix in Malaysia",
    circuitName: "Sepang International Circuit",
    date: "2026-10-04",
    time: "07:00:00Z"
  },
  previous: { name: "Azerbaijan Grand Prix", date: "2026-09-26" },
  previousResults: [
    { position: "1", code: "RUS", name: "George Russell" },
    { position: "2", code: "VER", name: "Max Verstappen" },
    { position: "3", code: "HAD", name: "Isack Hadjar" }
  ]
})
