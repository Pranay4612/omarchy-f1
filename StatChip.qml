import QtQuick
import qs.Commons

// A single labelled value. Used for lap, weather, track status.
Item {
  id: root
  property string label: ""
  property string value: ""
  property color valueColor: Color.foreground
  property bool mono: true

  // Line heights come from the font tokens rather than from the Text items.
  // A Text reports an implicitHeight of zero until it has been given a width,
  // so summing the items yields a zero-height chip and the panel silently
  // loses a whole row of layout.
  readonly property real lineHeight: Style.font.caption * 1.3 + Style.font.bodySmall * 1.35

  implicitWidth: Math.max(labelItem.implicitWidth, valueItem.implicitWidth) + Style.space(2)
  implicitHeight: Math.round(lineHeight)

  Column {
    anchors.fill: parent
    spacing: 0
    Text {
      id: labelItem
      text: root.label
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      font.capitalization: Font.AllUppercase
    }
    Text {
      id: valueItem
      width: parent.width
      text: root.value
      color: root.valueColor
      font.family: root.mono ? Style.font.family : Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.bold: true
      elide: Text.ElideRight
    }
  }
}
