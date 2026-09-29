// Development-only entry point. Not part of the shipped plugin.
//
// Quickshell runs a configuration from a directory containing shell.qml, so
// this file exists to render the panel during design and test work. Both
// harnesses mount the *real* Plugin QML; only the shell facade is stubbed.
// install.sh copies an explicit list of runtime files and never ships this,
// PanelHarness.qml, DevPreview.qml or dev-preview.js.
//
//   scripts/preview.sh              design, against mock data
//   scripts/panel-test.sh           end to end, against a real snapshot
//
// F1_HARNESS picks which one: "panel" (default) or "design".
import QtQuick
import Quickshell
import Quickshell.Wayland

ShellRoot {
  id: shell

  readonly property bool designMode:
    (Quickshell.env("F1_HARNESS") || "panel") === "design"

  PanelWindow {
    id: win
    anchors { top: true; left: true }
    implicitWidth: designMode ? 800 : 800
    implicitHeight: designMode ? 640 : 720
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "f1-harness"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Loader {
      anchors.fill: parent
      source: shell.designMode ? "DevPreview.qml" : "PanelHarness.qml"
    }
  }
}
