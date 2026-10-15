import AppKit

@MainActor
enum AgentTelemetryAppIcon {
    static let image: NSImage = {
        if let url = Bundle.main.url(forResource: "AppIcon", withExtension: "icns"),
           let image = NSImage(contentsOf: url) {
            image.isTemplate = false
            image.accessibilityDescription = "AgentTelemetry"
            return image
        }

        let fallback = NSApplication.shared.applicationIconImage.copy() as? NSImage
            ?? NSImage(size: NSSize(width: 512, height: 512))
        fallback.isTemplate = false
        fallback.accessibilityDescription = "AgentTelemetry"
        return fallback
    }()
}
