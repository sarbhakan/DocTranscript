import Combine
import Darwin
import Foundation

struct TranscriptNote: Identifiable, Codable, Equatable, Sendable {
    let id: UUID
    var title: String
    var body: String
    var folderID: UUID?
    let createdAt: Date
    var updatedAt: Date
}

struct TranscriptFolder: Identifiable, Codable, Equatable, Sendable {
    let id: UUID
    var name: String
    let createdAt: Date
}

enum LibrarySaveStatus: Equatable {
    case saved
    case pending
    case unsaved
    case recovered
    case unavailable
}

private enum LibraryStorageError: Error {
    case invalidDirectory, invalidFile, invalidData, locked, tooLarge
}

private struct LibrarySnapshot: Codable {
    static let currentVersion = 1
    static let maxBytes = 16 * 1024 * 1024
    static let maxNotes = 5_000
    static let maxFolders = 500

    let version: Int
    let notes: [TranscriptNote]
    let folders: [TranscriptFolder]

    init(notes: [TranscriptNote] = [], folders: [TranscriptFolder] = []) {
        version = Self.currentVersion
        self.notes = notes
        self.folders = folders
    }

    func validate() throws {
        let folderIDs = Set(folders.map(\.id))
        guard version == Self.currentVersion, notes.count <= Self.maxNotes, folders.count <= Self.maxFolders,
              Set(notes.map(\.id)).count == notes.count, folderIDs.count == folders.count,
              folders.allSatisfy({
                  Self.validLabel($0.name) && $0.createdAt.timeIntervalSinceReferenceDate.isFinite
              }),
              notes.allSatisfy({
                  Self.validLabel($0.title) && $0.createdAt.timeIntervalSinceReferenceDate.isFinite
                      && $0.updatedAt.timeIntervalSinceReferenceDate.isFinite && $0.updatedAt >= $0.createdAt
                      && ($0.folderID.map(folderIDs.contains) ?? true)
              }) else { throw LibraryStorageError.invalidData }
    }

    static func validLabel(_ name: String) -> Bool {
        !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && name.utf8.count <= 1_024
    }
}

// The caller serializes access on the main actor. The lock also protects against
// a second copy of the app overwriting the first one's library.
private final class LibraryDisk {
    enum FileState {
        case absent
        case invalid
        case unsupportedVersion
        case valid(LibrarySnapshot, Data)
    }

    private let primary: URL
    private let backup: URL
    private let directory: URL
    private let lock: Int32
    private var primaryValidated = false

    init(directory: URL) throws {
        guard directory.isFileURL else { throw LibraryStorageError.invalidDirectory }
        let fm = FileManager.default
        try fm.createDirectory(at: directory, withIntermediateDirectories: true,
                               attributes: [.posixPermissions: 0o700])
        var metadata = stat()
        guard lstat(directory.path, &metadata) == 0, (metadata.st_mode & S_IFMT) == S_IFDIR,
              metadata.st_uid == getuid(), chmod(directory.path, 0o700) == 0 else {
            throw LibraryStorageError.invalidDirectory
        }

        let descriptor = open(directory.appendingPathComponent(".transcriptions.lock").path,
                              O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK, 0o600)
        guard descriptor >= 0 else { throw LibraryStorageError.locked }
        guard fstat(descriptor, &metadata) == 0, (metadata.st_mode & S_IFMT) == S_IFREG,
              metadata.st_uid == getuid(), flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            close(descriptor)
            throw LibraryStorageError.locked
        }

        self.directory = directory
        primary = directory.appendingPathComponent("transcriptions.json")
        backup = directory.appendingPathComponent("transcriptions.backup.json")
        lock = descriptor
    }

    deinit { close(lock) }

    func load() throws -> (snapshot: LibrarySnapshot, recovered: Bool, repairPending: Bool) {
        let main = read(primary)
        if case let .valid(snapshot, _) = main {
            primaryValidated = true
            return (snapshot, false, false)
        }
        if case .unsupportedVersion = main { throw LibraryStorageError.invalidData }

        let previous = read(backup)
        if case let .valid(snapshot, bytes) = previous {
            // Restore from the valid backup without linking the damaged primary over it.
            do {
                try bytes.write(to: primary, options: .atomic)
                primaryValidated = true
                return (snapshot, true, false)
            } catch {
                return (snapshot, true, true)
            }
        }
        if case .absent = main, case .absent = previous {
            return (LibrarySnapshot(), false, false)
        }
        // Never turn unreadable or unsupported data into a fresh empty library.
        throw LibraryStorageError.invalidData
    }

    private func read(_ url: URL) -> FileState {
        let descriptor = open(url.path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK)
        if descriptor < 0 { return errno == ENOENT ? .absent : .invalid }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0, (metadata.st_mode & S_IFMT) == S_IFREG,
              metadata.st_uid == getuid(),
              metadata.st_size >= 0, metadata.st_size <= LibrarySnapshot.maxBytes else { return .invalid }
        do {
            guard let data = try handle.read(upToCount: LibrarySnapshot.maxBytes + 1),
                  data.count <= LibrarySnapshot.maxBytes else { return .invalid }
            struct Version: Decodable { let version: Int }
            let decoder = JSONDecoder()
            let version = try decoder.decode(Version.self, from: data).version
            guard version == LibrarySnapshot.currentVersion else { return .unsupportedVersion }
            let snapshot = try decoder.decode(LibrarySnapshot.self, from: data)
            try snapshot.validate()
            return .valid(snapshot, data)
        } catch {
            return .invalid
        }
    }

    func save(_ snapshot: LibrarySnapshot) throws {
        try snapshot.validate()
        let data = try JSONEncoder().encode(snapshot)
        guard data.count <= LibrarySnapshot.maxBytes else { throw LibraryStorageError.tooLarge }

        if primaryValidated {
            // A hard link retains the last committed bytes without rewriting them.
            // Rename it atomically so a crash cannot leave a half-written backup.
            let next = directory.appendingPathComponent(".backup-\(UUID().uuidString)")
            defer { try? FileManager.default.removeItem(at: next) }
            if link(primary.path, next.path) != 0, errno != ENOENT {
                throw LibraryStorageError.invalidFile
            }
            if FileManager.default.fileExists(atPath: next.path),
               rename(next.path, backup.path) != 0 {
                throw LibraryStorageError.invalidFile
            }
        }
        // The directory is owner-only, including the atomic writer's temporary file.
        try data.write(to: primary, options: .atomic)
        primaryValidated = true
    }
}

@MainActor final class TranscriptLibrary: ObservableObject {
    @Published private(set) var notes: [TranscriptNote] = []
    @Published private(set) var folders: [TranscriptFolder] = []
    @Published private(set) var status: LibrarySaveStatus = .unavailable

    private let disk: LibraryDisk?
    private let clock: () -> Date
    private let saveDelay: Duration
    private var dirty = false
    private var scheduledSave: Task<Void, Never>?

    var canEdit: Bool { disk != nil }

    init(directory: URL? = nil, clock: @escaping () -> Date = { Date() }, saveDelay: Duration = .milliseconds(350)) {
        self.clock = clock
        self.saveDelay = saveDelay
        do {
            let path = try directory ?? FileManager.default
                .url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
                .appendingPathComponent("NoteVive", isDirectory: true)
            let storage = try LibraryDisk(directory: path)
            let loaded = try storage.load()
            disk = storage
            notes = loaded.snapshot.notes
            folders = loaded.snapshot.folders
            dirty = loaded.repairPending
            status = loaded.recovered ? .recovered : .saved
        } catch {
            disk = nil
        }
    }

    func note(_ id: UUID) -> TranscriptNote? { notes.first(where: { $0.id == id }) }

    @discardableResult
    func createNote(folderID: UUID? = nil) -> UUID? {
        guard canEdit, notes.count < LibrarySnapshot.maxNotes, validFolder(folderID) else { return nil }
        let date = clock()
        let note = TranscriptNote(id: UUID(), title: "Nouvelle transcription", body: "",
                                  folderID: folderID, createdAt: date, updatedAt: date)
        notes.append(note)
        changed()
        return note.id
    }

    @discardableResult
    func createFolder(name: String) -> UUID? {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard canEdit, folders.count < LibrarySnapshot.maxFolders,
              LibrarySnapshot.validLabel(name), !hasFolder(named: name) else { return nil }
        let folder = TranscriptFolder(id: UUID(), name: name, createdAt: clock())
        folders.append(folder)
        changed()
        return folder.id
    }

    @discardableResult
    func renameNote(_ id: UUID, title: String) -> Bool {
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard LibrarySnapshot.validLabel(title) else { return false }
        return update(id, \.title, title)
    }

    @discardableResult
    func updateBody(_ id: UUID, body: String, immediate: Bool = true) -> Bool {
        update(id, \.body, body, immediate: immediate)
    }

    @discardableResult
    func moveNote(_ id: UUID, to folderID: UUID?) -> Bool {
        guard validFolder(folderID) else { return false }
        return update(id, \.folderID, folderID)
    }

    @discardableResult
    func renameFolder(_ id: UUID, name: String) -> Bool {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard canEdit, let index = folders.firstIndex(where: { $0.id == id }),
              LibrarySnapshot.validLabel(name), !hasFolder(named: name, excluding: id) else { return false }
        guard folders[index].name != name else { return true }
        folders[index].name = name
        changed()
        return true
    }

    private func update<Value: Equatable>(_ id: UUID, _ key: WritableKeyPath<TranscriptNote, Value>,
                                          _ value: Value, immediate: Bool = true) -> Bool {
        guard canEdit, let index = notes.firstIndex(where: { $0.id == id }) else { return false }
        guard notes[index][keyPath: key] != value else {
            if immediate { flush() }
            return true
        }
        var note = notes[index]
        note[keyPath: key] = value
        note.updatedAt = max(note.updatedAt, clock())
        notes[index] = note
        changed(immediate: immediate)
        return true
    }

    private func validFolder(_ id: UUID?) -> Bool {
        id.map { wanted in folders.contains { $0.id == wanted } } ?? true
    }

    private func hasFolder(named name: String, excluding id: UUID? = nil) -> Bool {
        folders.contains { $0.id != id && $0.name.caseInsensitiveCompare(name) == .orderedSame }
    }

    private func changed(immediate: Bool = true) {
        dirty = true
        if immediate {
            flush()
        } else {
            scheduledSave?.cancel()
            if status != .pending && status != .unsaved { status = .pending }
            scheduledSave = Task { [weak self, delay = saveDelay] in
                do { try await Task.sleep(for: delay) } catch { return }
                guard !Task.isCancelled else { return }
                self?.flush()
            }
        }
    }

    /// Retries a failed save; an unsuccessful save keeps the newer notes in memory.
    @discardableResult
    func flush() -> Bool {
        scheduledSave?.cancel()
        scheduledSave = nil
        guard let disk else { return false }
        guard dirty else { return true }
        do {
            try disk.save(LibrarySnapshot(notes: notes, folders: folders))
            dirty = false
            if status != .saved { status = .saved }
            return true
        } catch {
            if status != .unsaved { status = .unsaved }
            return false
        }
    }
}
