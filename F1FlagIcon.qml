import QtQuick
import qs.Commons

// The logo: a chequered flag, drawn rather than typed.
//
// A racing glyph would be the obvious choice, but the shell's Nerd Font
// (JetBrains Mono NF) has no car, flag or gauge in its Material Design range --
// verified against the font's own cmap. Depending on a glyph that may be
// missing would render a tofu box on someone's bar.
//
// Shapes also mean the logo is theme-coloured rather than a fixed ink, so it
// follows a theme change for free, and it can carry state: the flag takes the
// urgent colour while a session is live, which is the one moment the bar
// should be shouting.
//
// Sized by `iconSize` rather than by its own width and height. An implicit
// size derived from `height`, on an item that is then sized from its implicit
// size and anchored to its parent, is a binding cycle -- and it drops the
// widget out of the bar entirely rather than showing a warning.
Item {
  id: root

  property real iconSize: 14
  property color colour: Color.foreground

  // A third of the icon, which at bar scale gives 4px cells: large enough that
  // the pattern still reads as a chequered flag, small enough not to shout.
  readonly property real cell: Math.max(1, Math.round(iconSize * 0.28))
  readonly property int cells: 3
  readonly property real fieldSize: cell * cells
  readonly property real poleWidth: Math.max(1, Math.round(iconSize * 0.11))

  implicitWidth: iconSize
  implicitHeight: iconSize

  // Pole
  Rectangle {
    anchors.left: parent.left
    anchors.verticalCenter: parent.verticalCenter
    width: root.poleWidth
    height: root.iconSize
    radius: width / 2
    color: root.colour
    opacity: 0.75
  }

  // Chequered field
  Item {
    anchors.left: parent.left
    anchors.leftMargin: root.poleWidth
    anchors.verticalCenter: parent.verticalCenter
    width: root.fieldSize
    height: root.fieldSize

    Repeater {
      model: root.cells * root.cells
      delegate: Rectangle {
        required property int index
        // The classic pattern: filled where column and row differ in parity.
        readonly property int col: index % root.cells
        readonly property int row: Math.floor(index / root.cells)
        x: col * root.cell
        y: row * root.cell
        width: root.cell
        height: root.cell
        color: (col + row) % 2 === 0 ? root.colour : "transparent"
      }
    }
  }
}
