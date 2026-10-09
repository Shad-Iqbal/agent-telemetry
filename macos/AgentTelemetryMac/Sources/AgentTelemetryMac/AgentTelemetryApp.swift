import AppKit
import SwiftUI

@main
@MainActor
struct AgentTelemetryApp: App {
    @Environment(\.openWindow) private var openWindow
    @StateObject private var settings: AppSettings
    @StateObject private var backend: BackendController

    init() {
        let settings = AppSettings()
        let backend = BackendController(settings: settings)
        _settings = StateObject(wrappedValue: settings)
        _backend = StateObject(wrappedValue: backend)
        if settings.startMonitoringAutomatically {
            Task { @MainActor in backend.start() }
        }
    }

    var body: some Scene {
        WindowGroup("AgentTelemetry", id: "dashboard") {
            DashboardWindow(backend: backend, settings: settings)
        }

        MenuBarExtra(content: {
            StatusMenu(
                backend: backend,
                settings: settings,
                openDashboard: { openDashboard() },
                quit: { backend.stop { NSApp.terminate(nil) } }
            )
        }, label: {
            menuBarLabel
        })
        .menuBarExtraStyle(.window)
    }

    @ViewBuilder
    private var menuBarLabel: some View {
        if settings.menuBarDisplay == .numbers {
            Image(nsImage: menuBarNumbersImage)
                .renderingMode(.original)
                .accessibilityLabel(backend.summary.date.isEmpty
                    ? "AgentTelemetry; today's summary is not available"
                    : "AgentTelemetry; \(backend.summary.tokens) tokens today; estimated spend \(backend.summary.spend) dollars")
        } else {
            Image(systemName: menuBarSymbol)
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(menuBarTint)
                .accessibilityLabel("AgentTelemetry; \(backend.status.title)")
        }
    }

    private var menuBarSymbol: String {
        switch backend.status {
        case .starting, .stopping: return "ellipsis.circle"
        case .needsAttention: return "exclamationmark.triangle.fill"
        case .stopped, .running, .connectedToExisting: return "chart.bar.fill"
        }
    }

    private var menuBarTint: Color {
        switch backend.status {
        case .stopped: return .secondary
        case .starting, .stopping: return .blue
        case .running, .connectedToExisting: return .green
        case .needsAttention: return .orange
        }
    }

    private var menuBarNumbersImage: NSImage {
        let tokenText = backend.summary.date.isEmpty ? "—" : compactTokens(backend.summary.tokens)
        let spendText = backend.summary.date.isEmpty
            ? "—"
            : String(format: "$%.2f", backend.summary.spend)
        let size = NSSize(width: 60, height: 22)
        let font = NSFont.monospacedDigitSystemFont(ofSize: 9, weight: .semibold)
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = .right

        func line(_ text: String, color: NSColor) -> NSAttributedString {
            NSAttributedString(string: text, attributes: [
                .font: font,
                .foregroundColor: color,
                .paragraphStyle: paragraph
            ])
        }

        let image = NSImage(size: size, flipped: false) { rect in
            NSColor.clear.setFill()
            rect.fill()
            line(tokenText, color: .labelColor)
                .draw(in: NSRect(x: 0, y: 11, width: size.width, height: 11))
            line(spendText, color: .secondaryLabelColor)
                .draw(in: NSRect(x: 0, y: 0, width: size.width, height: 11))
            return true
        }
        image.isTemplate = false
        return image
    }

    private func openDashboard() {
        backend.start(openDashboard: { openWindow(id: "dashboard") })
    }

    private func compactTokens(_ value: Int) -> String {
        if value >= 1_000_000 { return String(format: "%.1fM", Double(value) / 1_000_000) }
        if value >= 1_000 { return String(format: "%.1fk", Double(value) / 1_000) }
        return value.formatted()
    }
}
