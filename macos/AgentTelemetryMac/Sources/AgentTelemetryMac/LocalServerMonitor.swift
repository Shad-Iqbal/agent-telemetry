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
    let profileID: String?
    let isConfigured: Bool
    let isPinned: Bool

    var isRunning: Bool { state == "running" }
    var address: String { "localhost:\(port)" }
    var location: String { project.isEmpty ? process : project }
    var displayDetails: String { project.isEmpty ? address : "\(address) · \(process)" }

    private enum CodingKeys: String, CodingKey {
        case id, pid, process, cwd, project, host, port, startedAt, state, firstSeen, lastSeen, stoppedAt
        case profileID = "profileId"
        case isConfigured, isPinned
    }

    init(
        id: String,
        pid: Int,
        process: String,
        cwd: String,
        project: String,
        host: String,
        port: Int,
        startedAt: String,
        state: String,
        firstSeen: String,
        lastSeen: String,
        stoppedAt: String?,
        profileID: String?,
        isConfigured: Bool,
        isPinned: Bool
    ) {
        self.id = id
        self.pid = pid
        self.process = process
        self.cwd = cwd
        self.project = project
        self.host = host
        self.port = port
        self.startedAt = startedAt
        self.state = state
        self.firstSeen = firstSeen
        self.lastSeen = lastSeen
        self.stoppedAt = stoppedAt
        self.profileID = profileID
        self.isConfigured = isConfigured
        self.isPinned = isPinned
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        pid = try values.decode(Int.self, forKey: .pid)
        process = try values.decode(String.self, forKey: .process)
        cwd = try values.decode(String.self, forKey: .cwd)
        project = try values.decode(String.self, forKey: .project)
        host = try values.decode(String.self, forKey: .host)
        port = try values.decode(Int.self, forKey: .port)
        startedAt = try values.decode(String.self, forKey: .startedAt)
        state = try values.decode(String.self, forKey: .state)
        firstSeen = try values.decode(String.self, forKey: .firstSeen)
        lastSeen = try values.decode(String.self, forKey: .lastSeen)
        stoppedAt = try values.decodeIfPresent(String.self, forKey: .stoppedAt)
        profileID = try values.decodeIfPresent(String.self, forKey: .profileID)
        isConfigured = try values.decodeIfPresent(Bool.self, forKey: .isConfigured) ?? false
        isPinned = try values.decodeIfPresent(Bool.self, forKey: .isPinned) ?? false
    }
}

struct LocalServerProfile: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let cwd: String
    let port: Int
    let command: String
    var isPinned: Bool
}

private struct LocalServerPayload: Codable, Sendable {
    let updatedAt: String
    let servers: [LocalServer]
    var profiles: [LocalServerProfile]

    init(updatedAt: String, servers: [LocalServer], profiles: [LocalServerProfile] = []) {
        self.updatedAt = updatedAt
        self.servers = servers
        self.profiles = profiles
    }

    private enum CodingKeys: String, CodingKey { case updatedAt, servers, profiles }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        updatedAt = try values.decodeIfPresent(String.self, forKey: .updatedAt) ?? ""
        servers = try values.decodeIfPresent([LocalServer].self, forKey: .servers) ?? []
        profiles = try values.decodeIfPresent([LocalServerProfile].self, forKey: .profiles) ?? []
    }
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
    var pinnedServers: [LocalServer] { servers.filter(\.isPinned) }

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
        do {
            if try await post("stop", body: ["id": server.id], timeout: 10) {
                await refresh()
                return
            }
            try await Task.detached(priority: .userInitiated) {
                try LocalServerStore.stop(id: server.id)
            }.value
            await refresh()
        } catch {
            await refresh()
            throw error
        }
    }

    func configure(_ server: LocalServer, command: String) async throws {
        do {
            if try await post("configure", body: ["id": server.id, "command": command], timeout: 10) {
                await refresh()
                return
            }
            try await Task.detached(priority: .userInitiated) {
                try LocalServerStore.configure(serverID: server.id, command: command)
            }.value
            await refresh()
        } catch {
            await refresh()
            throw error
        }
    }

    func setPinned(_ server: LocalServer, pinned: Bool) async throws {
        do {
            if try await post("pin", body: ["id": server.id, "pinned": pinned], timeout: 10) {
                await refresh()
                return
            }
            try await Task.detached(priority: .userInitiated) {
                try LocalServerStore.setPinned(serverID: server.id, pinned: pinned)
            }.value
            await refresh()
        } catch {
            await refresh()
            throw error
        }
    }

    func start(_ server: LocalServer) async throws {
        guard let profileID = server.profileID else { throw LocalServerError.profileUnavailable }
        do {
            if try await post("start", body: ["profileId": profileID], timeout: 35) {
                await refresh()
                return
            }
            try await Task.detached(priority: .userInitiated) {
                try LocalServerStore.start(profileID: profileID)
            }.value
            await refresh()
        } catch {
            await refresh()
            throw error
        }
    }

    func restart(_ server: LocalServer) async throws {
        guard let profileID = server.profileID else { throw LocalServerError.profileUnavailable }
        do {
            if try await post("restart", body: ["profileId": profileID], timeout: 40) {
                await refresh()
                return
            }
            try await Task.detached(priority: .userInitiated) {
                try LocalServerStore.restart(profileID: profileID)
            }.value
            await refresh()
        } catch {
            await refresh()
            throw error
        }
    }

    private func post(_ action: String, body: [String: Any], timeout: TimeInterval) async throws -> Bool {
        guard let backend, backend.isReady else { return false }
        var request = URLRequest(url: backend.dashboardURL.appendingPathComponent("api/local-servers/\(action)"))
        request.httpMethod = "POST"
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw LocalServerError.requestFailed("The local service returned no response.")
        }
        if http.statusCode == 404 { return false }
        guard http.statusCode == 200 else {
            let body = (try? JSONDecoder().decode([String: String].self, from: data))
            throw LocalServerError.requestFailed(body?["error"] ?? "Could not \(action) that server.")
        }
        return true
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
    case profileUnavailable

    var errorDescription: String? {
        switch self {
        case let .requestFailed(message): return message
        case .scanFailed: return "Could not inspect local listening ports."
        case .changed: return "The process changed since this list was loaded. Refresh and try again."
        case .unavailable: return "That server has already stopped."
        case .profileUnavailable: return "Configure a launch command for this server first."
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

    static func configure(serverID: String, command: String) throws {
        let cleaned = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty, cleaned.count <= 4096, !cleaned.contains("\0") else {
            throw LocalServerError.requestFailed("Enter a launch command of 1–4096 characters.")
        }
        try withLock {
            let payload = try scanAndStore()
            guard let server = payload.servers.first(where: { $0.id == serverID }) else {
                throw LocalServerError.unavailable
            }
            guard FileManager.default.fileExists(atPath: server.cwd) else {
                throw LocalServerError.requestFailed("The server folder is no longer available. Configure it again from a running server.")
            }
            guard (1...65535).contains(server.port) else {
                throw LocalServerError.requestFailed("The server port is invalid. Configure it again from a running server.")
            }
            let profileID = profileID(cwd: server.cwd, port: server.port)
            var profiles = profilesByID(payload.profiles)
            let old = profiles[profileID]
            profiles[profileID] = LocalServerProfile(
                id: profileID,
                cwd: canonicalPath(server.cwd),
                port: server.port,
                command: cleaned,
                isPinned: old?.isPinned ?? false
            )
            try write(LocalServerPayload(updatedAt: payload.updatedAt, servers: payload.servers,
                                          profiles: Array(profiles.values)))
        }
    }

    static func setPinned(serverID: String, pinned: Bool) throws {
        try withLock {
            let payload = try scanAndStore()
            guard let server = payload.servers.first(where: { $0.id == serverID }) else {
                throw LocalServerError.unavailable
            }
            let id = profileID(cwd: server.cwd, port: server.port)
            var profiles = profilesByID(payload.profiles)
            if let old = profiles[id] {
                if pinned || !old.command.isEmpty {
                    profiles[id] = LocalServerProfile(id: old.id, cwd: old.cwd, port: old.port,
                                                      command: old.command, isPinned: pinned)
                } else {
                    profiles.removeValue(forKey: id)
                }
            } else if pinned {
                profiles[id] = LocalServerProfile(id: id, cwd: canonicalPath(server.cwd), port: server.port,
                                                  command: "", isPinned: true)
            }
            try write(LocalServerPayload(updatedAt: payload.updatedAt, servers: payload.servers,
                                          profiles: Array(profiles.values)))
        }
    }

    static func start(profileID: String) throws {
        let bytes = profileID.utf8
        guard bytes.count == 20 && bytes.allSatisfy({ (0x30...0x39).contains($0) || (0x61...0x66).contains($0) }) else {
            throw LocalServerError.profileUnavailable
        }
        try withStartLock(profileID: profileID) {
            let profile: LocalServerProfile = try withLock {
                let payload = try scanAndStore()
                guard let saved = payload.profiles.first(where: { $0.id == profileID }), !saved.command.isEmpty else {
                    throw LocalServerError.profileUnavailable
                }
                guard !payload.servers.contains(where: { $0.profileID == profileID && $0.isRunning }) else {
                    throw LocalServerError.requestFailed("That server is already running.")
                }
                guard FileManager.default.fileExists(atPath: saved.cwd) else {
                    throw LocalServerError.requestFailed("The saved server folder no longer exists. Configure the launch command again.")
                }
                guard (1...65535).contains(saved.port) else {
                    throw LocalServerError.requestFailed("The saved server port is invalid. Configure the launch command again.")
                }
                guard Self.profileID(cwd: saved.cwd, port: saved.port) == profileID else {
                    throw LocalServerError.requestFailed("The saved server profile is invalid. Configure the launch command again.")
                }
                guard !payload.servers.contains(where: { $0.port == saved.port && $0.isRunning }) else {
                    throw LocalServerError.requestFailed("Port \(saved.port) is already used by another local server.")
                }
                return saved
            }

            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = ["-lc", profile.command]
            process.currentDirectoryURL = URL(fileURLWithPath: profile.cwd, isDirectory: true)
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
            } catch {
                throw LocalServerError.requestFailed("Could not launch the saved command: \(error.localizedDescription)")
            }

            let deadline = Date().addingTimeInterval(15)
            while Date() < deadline {
                let payload = try snapshot()
                if payload.servers.contains(where: { $0.profileID == profileID && $0.isRunning }) {
                    return
                }
                if !process.isRunning {
                    throw LocalServerError.requestFailed("The launch command exited before port \(profile.port) opened.")
                }
                Thread.sleep(forTimeInterval: 0.4)
            }
            throw LocalServerError.requestFailed("The launch command did not open port \(profile.port) within 15 seconds.")
        }
    }

    static func restart(profileID: String) throws {
        let payload = try snapshot()
        guard let server = payload.servers.first(where: { $0.profileID == profileID && $0.isRunning }) else {
            throw LocalServerError.unavailable
        }
        try stop(id: server.id)
        let deadline = Date().addingTimeInterval(15)
        while Date() < deadline {
            let updated = try snapshot()
            if !updated.servers.contains(where: { $0.profileID == profileID && $0.isRunning }) {
                try start(profileID: profileID)
                return
            }
            Thread.sleep(forTimeInterval: 0.3)
        }
        throw LocalServerError.requestFailed("The server did not stop in time, so it was not restarted.")
    }

    private static func canonicalPath(_ path: String) -> String {
        URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL.path
    }

    private static func profilesByID(_ profiles: [LocalServerProfile]) -> [String: LocalServerProfile] {
        profiles.reduce(into: [:]) { result, profile in result[profile.id] = profile }
    }

    private static func profileID(cwd: String, port: Int) -> String {
        let identity = "\(canonicalPath(cwd)):\(port)"
        return SHA256.hash(data: Data(identity.utf8)).prefix(10)
            .map { String(format: "%02x", $0) }.joined()
    }

    private static func write(_ payload: LocalServerPayload) throws {
        try FileManager.default.createDirectory(
            at: dataDirectory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        _ = chmod(dataDirectory.path, mode_t(S_IRWXU))
        let data = try JSONEncoder().encode(payload)
        let inventoryURL = dataDirectory.appendingPathComponent(".local_servers.json")
        try data.write(to: inventoryURL, options: .atomic)
        _ = chmod(inventoryURL.path, mode_t(S_IRUSR | S_IWUSR))
    }

    private static func withLock<T>(_ body: () throws -> T) throws -> T {
        try withFileLock(at: dataDirectory.appendingPathComponent(".local_servers.json.lock"), body)
    }

    private static func withStartLock<T>(profileID: String, _ body: () throws -> T) throws -> T {
        try withFileLock(
            at: dataDirectory.appendingPathComponent(".local_servers.json.lock.start.\(profileID)"),
            body
        )
    }

    private static func withFileLock<T>(at lockURL: URL, _ body: () throws -> T) throws -> T {
        try FileManager.default.createDirectory(at: dataDirectory, withIntermediateDirectories: true)
        let descriptor = open(lockURL.path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw LocalServerError.requestFailed("Could not open the local server inventory.") }
        _ = chmod(lockURL.path, mode_t(S_IRUSR | S_IWUSR))
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
        let profiles = profilesByID(old.profiles)
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
            let profileID = Self.profileID(cwd: draft.cwd, port: draft.port)
            let profile = profiles[profileID]
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
                stoppedAt: nil,
                profileID: profileID,
                isConfigured: !(profile?.command.isEmpty ?? true),
                isPinned: profile?.isPinned ?? false
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
                stoppedAt: now,
                profileID: server.profileID,
                isConfigured: server.isConfigured,
                isPinned: server.isPinned
            )
        }

        for (id, server) in byID {
            let profileID = Self.profileID(cwd: server.cwd, port: server.port)
            let profile = profiles[profileID]
            byID[id] = LocalServer(
                id: server.id,
                pid: server.pid,
                process: server.process,
                cwd: server.cwd,
                project: server.project,
                host: server.host,
                port: server.port,
                startedAt: server.startedAt,
                state: server.state,
                firstSeen: server.firstSeen,
                lastSeen: server.lastSeen,
                stoppedAt: server.stoppedAt,
                profileID: profileID,
                isConfigured: !(profile?.command.isEmpty ?? true),
                isPinned: profile?.isPinned ?? false
            )
        }

        let cutoff = Calendar.current.date(byAdding: .day, value: -30, to: Date()) ?? .distantPast
        let formatter = ISO8601DateFormatter()
        let kept = byID.values.filter { server in
            if server.isPinned { return true }
            guard let date = formatter.date(from: server.lastSeen) else { return false }
            return date >= cutoff
        }.sorted {
            if $0.isPinned != $1.isPinned { return $0.isPinned }
            if $0.isRunning != $1.isRunning { return $0.isRunning }
            return $0.lastSeen > $1.lastSeen
        }.prefix(100)
        let payload = LocalServerPayload(updatedAt: now, servers: Array(kept), profiles: Array(profiles.values))
        try write(payload)
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
