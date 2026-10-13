import Combine
import CryptoKit
import Darwin
import Foundation

struct LocalServer: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let pid: Int
    let process: String
    let cwd: String
    let project: String
    let host: String
    let port: Int
    let startedAt: String
    let state: String
    let firstSeen: String
    let lastSeen: String
    let stoppedAt: String?

    var isRunning: Bool { state == "running" }
    var address: String { "localhost:\(port)" }
    var location: String { project.isEmpty ? process : project }
    var displayDetails: String { project.isEmpty ? address : "\(address) · \(process)" }
}

private struct LocalServerPayload: Codable, Sendable {
    let updatedAt: String
    let servers: [LocalServer]
}

@MainActor
final class LocalServerMonitor: ObservableObject {
    @Published private(set) var servers: [LocalServer] = []
    @Published private(set) var errorMessage: String?
    @Published private(set) var isRefreshing = false

    private weak var backend: BackendController?
    private var statusSubscription: AnyCancellable?
    private var pollingTask: Task<Void, Never>?

    var runningServers: [LocalServer] { servers.filter(\.isRunning) }
    var recentlyStopped: [LocalServer] { servers.filter { !$0.isRunning } }

    func connect(to backend: BackendController) {
        guard self.backend !== backend else { return }
        self.backend = backend
        statusSubscription = backend.$status.sink { [weak self] _ in
            Task { @MainActor [weak self] in await self?.refresh() }
        }
        pollingTask?.cancel()
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                guard !Task.isCancelled else { return }
                await self?.refresh()
            }
        }
        Task { await refresh() }
    }

    func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }

        if let backend, backend.isReady, let payload = await fetchFromBackend(backend) {
            servers = payload.servers
            errorMessage = nil
            return
        }

        do {
            let payload = try await Task.detached(priority: .utility) {
                try LocalServerStore.snapshot()
            }.value
            servers = payload.servers
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func stop(_ server: LocalServer) async throws {
        if let backend, backend.isReady {
            var request = URLRequest(url: backend.dashboardURL.appendingPathComponent("api/local-servers/stop"))
            request.httpMethod = "POST"
            request.timeoutInterval = 10
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["id": server.id])
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw LocalServerError.requestFailed("The local service returned no response.")
            }
            if http.statusCode == 404 {
                try await Task.detached(priority: .userInitiated) {
                    try LocalServerStore.stop(id: server.id)
                }.value
            } else if http.statusCode != 200 {
                let body = (try? JSONDecoder().decode([String: String].self, from: data))
                throw LocalServerError.requestFailed(body?["error"] ?? "Could not stop that server.")
            }
        } else {
            try await Task.detached(priority: .userInitiated) {
                try LocalServerStore.stop(id: server.id)
            }.value
        }
        await refresh()
    }

    private func fetchFromBackend(_ backend: BackendController) async -> LocalServerPayload? {
        do {
            let (data, response) = try await URLSession.shared.data(
                from: backend.dashboardURL.appendingPathComponent("api/local-servers")
            )
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
            return try JSONDecoder().decode(LocalServerPayload.self, from: data)
        } catch {
            return nil
        }
    }
}

private enum LocalServerError: LocalizedError {
    case requestFailed(String)
    case scanFailed
    case changed
    case unavailable

    var errorDescription: String? {
        switch self {
        case let .requestFailed(message): return message
        case .scanFailed: return "Could not inspect local listening ports."
        case .changed: return "The process changed since this list was loaded. Refresh and try again."
        case .unavailable: return "That server has already stopped."
        }
    }
}

private enum LocalServerStore {
    private struct Draft {
        let pid: Int
        let process: String
        let cwd: String
        let host: String
        let port: Int
        let startedAt: String
    }

    private static var dataDirectory: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("AgentTelemetry", isDirectory: true)
    }

    static func snapshot() throws -> LocalServerPayload {
        try withLock {
            try scanAndStore()
        }
    }

    static func stop(id: String) throws {
        try withLock {
            let payload = try scanAndStore()
            guard let server = payload.servers.first(where: { $0.id == id && $0.isRunning }) else {
                throw LocalServerError.unavailable
            }
            guard processStartTimes(for: [server.pid])[server.pid] == server.startedAt else {
                throw LocalServerError.changed
            }
            guard Darwin.kill(pid_t(server.pid), SIGTERM) == 0 else {
                if errno == ESRCH { throw LocalServerError.unavailable }
                throw LocalServerError.requestFailed("macOS denied permission to stop that process.")
            }
        }
    }

    private static func withLock<T>(_ body: () throws -> T) throws -> T {
        try FileManager.default.createDirectory(at: dataDirectory, withIntermediateDirectories: true)
        let lockURL = dataDirectory.appendingPathComponent(".local_servers.json.lock")
        let descriptor = open(lockURL.path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw LocalServerError.requestFailed("Could not open the local server inventory.") }
        defer { close(descriptor) }
        guard setFileLock(descriptor, type: Int16(F_WRLCK), command: F_SETLKW) else {
            throw LocalServerError.requestFailed("Could not lock the local server inventory.")
        }
        defer { _ = setFileLock(descriptor, type: Int16(F_UNLCK), command: F_SETLK) }
        return try body()
    }

    private static func setFileLock(_ descriptor: Int32, type: Int16, command: Int32) -> Bool {
        var lock = Darwin.flock()
        lock.l_type = type
        lock.l_whence = Int16(SEEK_SET)
        lock.l_start = 0
        lock.l_len = 0
        return Darwin.fcntl(descriptor, command, &lock) == 0
    }

    private static func scanAndStore() throws -> LocalServerPayload {
        let now = ISO8601DateFormatter().string(from: Date())
        let old = readPayload()
        var byID = Dictionary(uniqueKeysWithValues: old.servers.map { ($0.id, $0) })
        let drafts = try scanListeners()
        var seen = Set<String>()

        for draft in drafts {
            let identity = "\(draft.pid):\(draft.startedAt):\(draft.port)"
            let digest = SHA256.hash(data: Data(identity.utf8))
            let id = digest.prefix(10).map { String(format: "%02x", $0) }.joined()
            seen.insert(id)
            let previous = byID[id]
            let project = draft.cwd.split(separator: "/").last.map(String.init) ?? ""
            byID[id] = LocalServer(
                id: id,
                pid: draft.pid,
                process: draft.process,
                cwd: draft.cwd,
                project: project,
                host: draft.host,
                port: draft.port,
                startedAt: draft.startedAt,
                state: "running",
                firstSeen: previous?.firstSeen ?? now,
                lastSeen: now,
                stoppedAt: nil
            )
        }

        for (id, server) in byID where !seen.contains(id) && server.isRunning {
            byID[id] = LocalServer(
                id: server.id,
                pid: server.pid,
                process: server.process,
                cwd: server.cwd,
                project: server.project,
                host: server.host,
                port: server.port,
                startedAt: server.startedAt,
                state: "stopped",
                firstSeen: server.firstSeen,
                lastSeen: server.lastSeen,
                stoppedAt: now
            )
        }

        let cutoff = Calendar.current.date(byAdding: .day, value: -30, to: Date()) ?? .distantPast
        let formatter = ISO8601DateFormatter()
        let kept = byID.values.filter { server in
            guard let date = formatter.date(from: server.lastSeen) else { return false }
            return date >= cutoff
        }.sorted {
            if $0.isRunning != $1.isRunning { return $0.isRunning }
            return $0.lastSeen > $1.lastSeen
        }.prefix(100)
        let payload = LocalServerPayload(updatedAt: now, servers: Array(kept))
        let data = try JSONEncoder().encode(payload)
        let inventoryURL = dataDirectory.appendingPathComponent(".local_servers.json")
        try data.write(to: inventoryURL, options: .atomic)
        _ = chmod(inventoryURL.path, mode_t(S_IRUSR | S_IWUSR))
        return payload
    }

    private static func readPayload() -> LocalServerPayload {
        let url = dataDirectory.appendingPathComponent(".local_servers.json")
        guard let data = try? Data(contentsOf: url),
              let payload = try? JSONDecoder().decode(LocalServerPayload.self, from: data) else {
            return LocalServerPayload(updatedAt: "", servers: [])
        }
        return payload
    }

    private static func scanListeners() throws -> [Draft] {
        let uid = String(getuid())
        let listing = run("/usr/sbin/lsof", ["-a", "-u", uid, "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn"])
        guard let listing else { throw LocalServerError.scanFailed }
        var processes: [Int: (name: String, endpoints: [(String, Int)])] = [:]
        var currentPID: Int?
        let portPattern = try NSRegularExpression(pattern: "^(.*):(\\d+)$")

        for line in listing.components(separatedBy: .newlines) {
            guard let first = line.first else { continue }
            let value = String(line.dropFirst())
            switch first {
            case "p":
                currentPID = Int(value)
                if let currentPID { processes[currentPID] = ("", []) }
            case "c":
                if let currentPID, var row = processes[currentPID] {
                    row.name = value
                    processes[currentPID] = row
                }
            case "n":
                guard let currentPID, var row = processes[currentPID],
                      let match = portPattern.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)),
                      let hostRange = Range(match.range(at: 1), in: value),
                      let portRange = Range(match.range(at: 2), in: value),
                      let port = Int(value[portRange]) else { continue }
                let host = String(value[hostRange]).trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
                if !row.endpoints.contains(where: { $0.0 == host && $0.1 == port }) {
                    row.endpoints.append((host, port))
                }
                processes[currentPID] = row
            default:
                continue
            }
        }

        let starts = processStartTimes(for: Array(processes.keys))
        guard processes.isEmpty || !starts.isEmpty else { throw LocalServerError.scanFailed }
        let directories = workingDirectories(uid: uid)
        var rows: [String: Draft] = [:]
        for (pid, process) in processes {
            guard let startedAt = starts[pid] else { continue }
            for (host, port) in process.endpoints {
                let key = "\(pid):\(startedAt):\(port)"
                if rows[key] == nil || ["*", "0.0.0.0", "::"].contains(host) {
                    rows[key] = Draft(
                        pid: pid,
                        process: process.name.isEmpty ? "Unknown process" : process.name,
                        cwd: directories[pid] ?? "",
                        host: host,
                        port: port,
                        startedAt: startedAt
                    )
                }
            }
        }
        return Array(rows.values)
    }

    private static func processStartTimes(for pids: [Int]) -> [Int: String] {
        guard !pids.isEmpty,
              let result = run("/bin/ps", ["-p", pids.sorted().map(String.init).joined(separator: ","), "-o", "pid=,lstart="]) else {
            return [:]
        }
        var starts: [Int: String] = [:]
        for line in result.components(separatedBy: .newlines) {
            let fields = line.split(maxSplits: 1, whereSeparator: \.isWhitespace)
            if fields.count == 2, let pid = Int(fields[0]) {
                starts[pid] = String(fields[1])
            }
        }
        return starts
    }

    private static func workingDirectories(uid: String) -> [Int: String] {
        guard let result = run("/usr/sbin/lsof", ["-a", "-u", uid, "-d", "cwd", "-Fpn"]) else { return [:] }
        var directories: [Int: String] = [:]
        var pid: Int?
        for line in result.components(separatedBy: .newlines) {
            if line.first == "p" { pid = Int(line.dropFirst()) }
            else if line.first == "n", let pid { directories[pid] = String(line.dropFirst()) }
        }
        return directories
    }

    private static func run(_ executable: String, _ arguments: [String]) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.environment = ProcessInfo.processInfo.environment.merging(["LC_ALL": "C"]) { _, new in new }
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            guard process.terminationStatus == 0 || process.terminationStatus == 1 else { return nil }
            return String(data: data, encoding: .utf8)
        } catch {
            return nil
        }
    }
}
