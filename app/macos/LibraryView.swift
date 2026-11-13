import AppKit
import CoreTransferable
import SwiftUI
import UniformTypeIdentifiers

private struct TranscriptReference: Codable, Transferable {
    let id: UUID

    static var transferRepresentation: some TransferRepresentation {
        CodableRepresentation(contentType: UTType(exportedAs: "fr.notevive.transcript-reference"))
    }
}

@MainActor final class TranscriptWorkspace: ObservableObject {
    @Published private(set) var selectedID: UUID?
    @Published private(set) var titleDraft = ""

    let library: TranscriptLibrary
    let dictation: Dictation
    private var changingNote = false
    private var editingBody = false

    init(library: TranscriptLibrary, dictation: Dictation) {
        self.library = library
        self.dictation = dictation
        dictation.onNoteChange = { [weak self] body in
            guard let self, !self.changingNote, let id = self.selectedID else { return }
            self.library.updateBody(id, body: body, immediate: !self.editingBody)
        }
        if let latest = library.notes.max(by: { $0.updatedAt < $1.updatedAt }) {
            open(latest.id)
        }
    }

    var canSwitch: Bool { dictation.canSwitchNote }
    var selected: TranscriptNote? { selectedID.flatMap { library.note($0) } }

    func open(_ id: UUID) {
        guard canSwitch, selectedID != id, let note = library.note(id) else { return }
        _ = library.flush()
        changingNote = true
        defer { changingNote = false }
        selectedID = id
        titleDraft = note.title
        dictation.note = note.body
    }

    func addNote(to folderID: UUID?) {
        guard canSwitch, library.canEdit, let id = library.createNote(folderID: folderID) else { return }
        open(id)
    }

    func editTitle(_ value: String) {
        guard let id = selectedID, library.canEdit else { return }
        titleDraft = value
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        library.renameNote(id, title: trimmed.isEmpty ? "Sans titre" : trimmed)
    }

    func finishTitle() {
        if let note = selected { titleDraft = note.title }
    }

    func editBody(_ value: String) {
        guard library.canEdit, selectedID != nil else { return }
        editingBody = true
        defer { editingBody = false }
        dictation.note = value
    }
}

struct LibraryView: View {
    private enum Scope: Hashable {
        case all, unfiled, folder(UUID)

        var folderID: UUID? {
            if case let .folder(id) = self { return id }
            return nil
        }
    }

    private struct DateGroup: Identifiable {
        let id: Date
        let notes: [TranscriptNote]
    }

    @ObservedObject var workspace: TranscriptWorkspace
    @ObservedObject var library: TranscriptLibrary
    @ObservedObject var dictation: Dictation
    @State private var scope: Scope = .all
    @State private var search = ""
    @State private var folderPrompt = false
    @State private var folderName = ""
    @State private var renamingFolder: UUID?
    @State private var folderNameRejected = false
    @FocusState private var titleFocused: Bool

    init(workspace: TranscriptWorkspace) {
        self.workspace = workspace
        self.library = workspace.library
        self.dictation = workspace.dictation
    }

    private var sortedFolders: [TranscriptFolder] {
        library.folders.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }

    private var recording: Bool { dictation.phase == .listening }
    private var preparing: Bool { dictation.phase == .loading }
    private var query: String { search.trimmingCharacters(in: .whitespacesAndNewlines) }

    private var groups: [DateGroup] {
        let calendar = Calendar.current
        let filtered = library.notes.filter { note in
            let inScope = switch scope {
            case .all: true
            case .unfiled: note.folderID == nil
            case let .folder(id): note.folderID == id
            }
            guard inScope else { return false }
            return query.isEmpty || note.title.localizedStandardContains(query)
                || note.body.localizedStandardContains(query)
        }
        let grouped = Dictionary(grouping: filtered) { calendar.startOfDay(for: $0.updatedAt) }
        return grouped.keys.sorted(by: >).map { date in
            DateGroup(id: date, notes: (grouped[date] ?? []).sorted {
                if $0.updatedAt != $1.updatedAt { return $0.updatedAt > $1.updatedAt }
                return $0.id.uuidString < $1.id.uuidString
            })
        }
    }

    var body: some View {
        HSplitView {
            sidebar
                .frame(minWidth: 240, idealWidth: 280, maxWidth: 430, maxHeight: .infinity)
            detail
                .frame(minWidth: 475, maxWidth: .infinity, maxHeight: .infinity)
        }
        .environment(\.locale, Locale(identifier: "fr_FR"))
        .alert(renamingFolder == nil ? "Nouveau dossier" : "Renommer le dossier", isPresented: $folderPrompt) {
            TextField("Nom du dossier", text: $folderName)
            Button("Annuler", role: .cancel) {}
            Button(renamingFolder == nil ? "Créer" : "Renommer") { saveFolder() }
                .disabled(folderName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .alert("Le dossier n’a pas été modifié", isPresented: $folderNameRejected) {
            Button("Réessayer") { folderPrompt = true }
            Button("Fermer", role: .cancel) {}
        } message: {
            Text("Choisissez un nom court qui n’est pas déjà utilisé dans la bibliothèque.")
        }
        .onChange(of: titleFocused) { _, focused in
            if !focused { workspace.finishTitle() }
        }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Bibliothèque").font(.title2.weight(.semibold))
                .accessibilityAddTraits(.isHeader)
            Button(action: createNote) {
                Label("Nouvelle transcription", systemImage: "plus")
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .controlSize(.large)
            .buttonStyle(.borderedProminent)
            .keyboardShortcut("n", modifiers: [.command])
            .disabled(!workspace.canSwitch || !library.canEdit)
            .help(workspace.canSwitch ? "Créer une transcription (⌘N)" : "Arrêtez la dictée avant de changer de note")
            TextField("Rechercher", text: $search, prompt: Text("Rechercher dans les notes"))
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("recherche-transcriptions")
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 4) {
                    scopeButton("Toutes les transcriptions", icon: "tray", target: .all)
                    dropRow("Sans dossier", icon: "doc.on.doc", target: .unfiled)
                    HStack {
                        Text("Dossiers").font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary).accessibilityAddTraits(.isHeader)
                        Spacer()
                        Button { promptFolder() } label: { Image(systemName: "folder.badge.plus") }
                            .buttonStyle(.borderless)
                            .accessibilityLabel("Nouveau dossier")
                            .help("Nouveau dossier")
                            .disabled(!library.canEdit)
                    }
                    .padding(.horizontal, 7).padding(.top, 10)
                    ForEach(sortedFolders) { folder in
                        dropRow(folder.name, icon: "folder", target: .folder(folder.id))
                            .contextMenu {
                                Button("Renommer le dossier…") { promptFolder(folder) }
                                    .disabled(!library.canEdit)
                            }
                    }
                    Divider().padding(.vertical, 8)
                    let displayedGroups = groups
                    if displayedGroups.isEmpty {
                        Text(query.isEmpty ? "Aucune transcription ici" : "Aucun résultat")
                            .font(.callout).foregroundStyle(.secondary).padding(7)
                    }
                    ForEach(displayedGroups) { group in
                        Text(dateLabel(group.id))
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .accessibilityAddTraits(.isHeader)
                            .padding(.horizontal, 7).padding(.top, 7)
                        ForEach(group.notes) { note in noteRow(note) }
                    }
                }
            }
            .defaultScrollAnchor(.top)
        }
        .padding(15)
        .background(Color(nsColor: .controlBackgroundColor))
    }

    private func scopeButton(_ name: String, icon: String, target: Scope) -> some View {
        Button {
            scope = target
        } label: {
            Label(name, systemImage: icon)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 8).padding(.vertical, 6)
                .contentShape(Rectangle())
                .background(scope == target ? Color.accentColor.opacity(0.17) : .clear,
                            in: RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(scope == target ? [.isSelected] : [])
    }

    private func dropRow(_ name: String, icon: String, target: Scope) -> some View {
        FolderDropRow(allowDrop: library.canEdit && workspace.canSwitch, performDrop: { refs in
            guard workspace.canSwitch, library.canEdit else { return false }
            var moved = false
            for id in Set(refs.map(\.id)) {
                guard let note = library.note(id), note.folderID != target.folderID else { continue }
                moved = library.moveNote(id, to: target.folderID) || moved
            }
            return moved
        }) {
            scopeButton(name, icon: icon, target: target)
        }
    }

    private func noteRow(_ note: TranscriptNote) -> some View {
        let current = workspace.selectedID == note.id
        let label = Button {
            workspace.open(note.id)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "doc.text").foregroundStyle(.secondary).accessibilityHidden(true)
                Text(note.title).lineLimit(1)
                Spacer(minLength: 2)
                Text(note.updatedAt, format: .dateTime.hour().minute())
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding(.horizontal, 8).padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .background(current ? Color.accentColor.opacity(0.18) : .clear,
                        in: RoundedRectangle(cornerRadius: 6))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(current ? [.isSelected] : [])
        .disabled(!workspace.canSwitch && !current)
        .contextMenu {
            Menu("Déplacer vers") {
                folderDestinations(for: note)
            }
            .disabled(!workspace.canSwitch || !library.canEdit)
        }
        return Group {
            if workspace.canSwitch && library.canEdit { label.draggable(TranscriptReference(id: note.id)) }
            else { label }
        }
    }

    private var detail: some View {
        VStack(alignment: .leading, spacing: 14) {
            storageNotice
            if let note = workspace.selected {
                editor(note)
            } else {
                Spacer()
                ContentUnavailableView {
                    Label("Vos transcriptions, au même endroit", systemImage: "waveform.and.mic")
                } description: {
                    Text("Créez une transcription pour dicter ou rédiger un brouillon. Les notes sont enregistrées sur ce Mac.")
                } actions: {
                    Button("Nouvelle transcription", action: createNote)
                        .buttonStyle(.borderedProminent).disabled(!library.canEdit)
                }
                Spacer()
            }
        }
        .padding(22)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    @ViewBuilder private var storageNotice: some View {
        switch library.status {
        case .saved, .pending: EmptyView()
        case .recovered:
            notice("Bibliothèque restaurée depuis la copie de secours. Vérifiez les dernières modifications.", icon: "arrow.counterclockwise")
        case .unsaved:
            HStack {
                notice("Modifications non enregistrées. Gardez NoteVive ouvert et réessayez, ou exportez le texte.", icon: "exclamationmark.triangle")
                Button("Réessayer") { _ = library.flush() }
            }
        case .unavailable:
            notice("Bibliothèque indisponible. Les fichiers existants sont conservés. Fermez les autres fenêtres NoteVive et relancez.", icon: "exclamationmark.triangle")
        }
    }

    private func notice(_ message: String, icon: String) -> some View {
        Label(message, systemImage: icon)
            .font(.callout).padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 7))
    }

    private func editor(_ note: TranscriptNote) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 12) {
                TextField("Titre de la transcription", text: Binding(
                    get: { workspace.titleDraft }, set: workspace.editTitle
                ))
                .font(.title2.weight(.semibold))
                .textFieldStyle(.roundedBorder)
                .focused($titleFocused)
                .accessibilityIdentifier("titre-transcription")
                .onSubmit { titleFocused = false }
                .disabled(!library.canEdit)
                Button {
                    titleFocused = false
                    dictation.toggle()
                } label: {
                    Label(recording ? "Arrêter" : preparing ? "Annuler" : "Dicter",
                          systemImage: recording ? "stop.fill" : preparing ? "xmark" : "mic")
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .keyboardShortcut("d", modifiers: [.command])
                .disabled(!library.canEdit || dictation.phase == .authorizing
                          || dictation.phase == .stopping || dictation.isExporting)
            }
            HStack {
                Menu {
                    folderDestinations(for: note)
                } label: {
                    Label(folderLabel(note), systemImage: "folder")
                        .lineLimit(1)
                }
                .fixedSize()
                .disabled(!workspace.canSwitch || !library.canEdit)
                .accessibilityLabel("Déplacer vers un dossier")
                .help("Classer cette transcription")
                Spacer()
                Text(note.createdAt, format: .dateTime.day().month(.wide).year())
            }
            .foregroundStyle(.secondary).font(.callout)
            Label(dictation.status, systemImage: recording ? "mic.fill" : "mic.slash")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(recording ? Color.red : Color.secondary)
                .accessibilityIdentifier("etat-micro")
            VStack(alignment: .leading, spacing: 6) {
                Text("Texte provisoire").font(.headline)
                ScrollView {
                    Text(dictation.draft.isEmpty ? "Le texte apparaît ici pendant la dictée." : dictation.draft)
                        .foregroundStyle(dictation.draft.isEmpty ? .secondary : .primary)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(height: 42)
                .padding(9)
                .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 7))
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("Brouillon à relire").font(.headline)
                TextEditor(text: Binding(get: { dictation.note }, set: workspace.editBody))
                    .font(.system(size: 15)).padding(5).frame(minHeight: 140)
                    .overlay { RoundedRectangle(cornerRadius: 7).strokeBorder(.quaternary) }
                    .accessibilityLabel("Brouillon à relire").accessibilityIdentifier("brouillon")
                    .disabled(!library.canEdit)
            }
            HStack {
                if library.status == .saved {
                    Label("Enregistré sur ce Mac", systemImage: "checkmark.circle")
                        .font(.footnote).foregroundStyle(.secondary)
                } else if library.status == .pending {
                    Label("Sauvegarde en cours…", systemImage: "clock")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Enregistrer") { _ = library.flush() }
                    .keyboardShortcut("s", modifiers: [.command])
                    .disabled(!library.canEdit)
                Button("Exporter le texte…") { dictation.exportNote(title: note.title) }
                    .keyboardShortcut("s", modifiers: [.command, .shift])
                    .disabled(dictation.note.isEmpty || !workspace.canSwitch)
            }
            Text("Essai sur des données fictives. L’audio n’est pas enregistré.")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }

    private func dateLabel(_ date: Date) -> String {
        if Calendar.current.isDateInToday(date) { return "Aujourd’hui" }
        if Calendar.current.isDateInYesterday(date) { return "Hier" }
        return date.formatted(.dateTime.day().month(.wide).year().locale(Locale(identifier: "fr_FR")))
    }

    private func folderLabel(_ note: TranscriptNote) -> String {
        library.folders.first { $0.id == note.folderID }?.name ?? "Sans dossier"
    }

    @ViewBuilder private func folderDestinations(for note: TranscriptNote) -> some View {
        Button("Sans dossier") { move(note, to: nil) }.disabled(note.folderID == nil)
        ForEach(sortedFolders) { folder in
            Button(folder.name) { move(note, to: folder.id) }.disabled(note.folderID == folder.id)
        }
    }

    private func createNote() {
        guard workspace.canSwitch && library.canEdit else { return }
        search = ""
        workspace.addNote(to: scope.folderID)
        titleFocused = true
    }

    private func promptFolder(_ folder: TranscriptFolder? = nil) {
        renamingFolder = folder?.id
        folderName = folder?.name ?? ""
        folderPrompt = true
    }

    private func saveFolder() {
        if let id = renamingFolder {
            if !library.renameFolder(id, name: folderName) {
                Task { @MainActor in folderNameRejected = true }
            }
        }
        else if let id = library.createFolder(name: folderName) {
            scope = .folder(id)
            search = ""
        } else {
            Task { @MainActor in folderNameRejected = true }
        }
    }

    private func move(_ note: TranscriptNote, to folderID: UUID?) {
        guard workspace.canSwitch, library.canEdit else { return }
        library.moveNote(note.id, to: folderID)
    }
}

private struct FolderDropRow<Content: View>: View {
    let allowDrop: Bool
    let performDrop: ([TranscriptReference]) -> Bool
    @ViewBuilder var content: () -> Content
    @State private var targeted = false

    var body: some View {
        content()
            .overlay {
                RoundedRectangle(cornerRadius: 6)
                    .strokeBorder(targeted && allowDrop ? Color.accentColor : .clear, lineWidth: 2)
                    .allowsHitTesting(false)
            }
            .dropDestination(for: TranscriptReference.self) { references, _ in
                allowDrop && performDrop(references)
            } isTargeted: { targeted = $0 }
    }
}
