#include "notes_model.h"

#include <iostream>
#include <stdexcept>

namespace {

using namespace notes;
using namespace notes::model;

void Check(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}

std::wstring Id(unsigned id) {
    std::wstring result = L"01234567-1234-4567-89ab-1234567890ab";
    result.replace(30, 6, 6, L'0');
    for (std::size_t i = 36; i > 30 && id; id /= 16)
        result[--i] = L"0123456789abcdef"[id % 16];
    return result;
}

const std::wstring kCreated = L"2024-02-29T12:34:56.123Z";
const std::wstring kModified = L"2025-01-15T09:00:00.130Z";

void Format() {
    const std::wstring id = Id(1);
    // Construct a frozen NVN1 payload independently of the new encoder:
    // historical Windows wrote five uint32-prefixed UTF-16LE fields.
    std::vector<Byte> old{'N', 'V', 'N', '1'};
    const std::u16string legacyId(id.begin(), id.end());
    const std::u16string legacyCreated(kCreated.begin(), kCreated.end());
    const std::u16string legacyModified(kModified.begin(), kModified.end());
    for (const auto& field : {legacyId, legacyCreated, legacyModified,
                              std::u16string(u"Œdème"), std::u16string(u"Texte fictif\r\n\U0001F4DD")}) {
        Check(field.size() < 256, "fixture field size");
        old.insert(old.end(), {static_cast<Byte>(field.size()), 0, 0, 0});
        for (auto ch : field) old.insert(old.end(), {static_cast<Byte>(ch & 255), static_cast<Byte>(ch >> 8)});
    }
    Note loaded;
    Check(DecodeNote(old.data(), old.size(), id, loaded) && loaded.created == kCreated &&
          loaded.modified == kModified && loaded.title == L"Œdème" && loaded.text == L"Texte fictif\r\n\U0001F4DD" &&
          loaded.folder_id.empty(), "legacy decode preserves dates and UTF16");
    std::vector<Byte> bytes;
    EncodeNote(bytes, loaded);
    Check(bytes == old, "unfiled note retains exact NVN1 payload format");
    loaded.folder_id = Id(2);
    bytes.clear();
    EncodeNote(bytes, loaded);
    Check(bytes[3] == '2', "filing selects NVN2");
    Note reopened;
    Check(DecodeNote(bytes.data(), bytes.size(), id, reopened) && reopened.text == loaded.text &&
          reopened.folder_id == Id(2) && reopened.created == loaded.created && reopened.modified == loaded.modified,
          "filed note survives reopen");
    Note metadata;
    Check(DecodeNote(bytes.data(), bytes.size(), id, metadata, false) &&
          metadata.text.empty() && metadata.folder_id == Id(2), "metadata read validates body without retaining it");

    const auto unchanged = reopened;
    Check(!DecodeNote(bytes.data(), bytes.size(), Id(3), reopened), "mismatched filename ID rejected");
    Check(!DecodeNote(bytes.data(), bytes.size() - 1, id, reopened), "truncated note (folder field) rejected");
    auto invalid = bytes;
    invalid[3] = '3';
    Check(!DecodeNote(invalid.data(), invalid.size(), id, reopened), "invalid format version rejected");
    invalid = bytes;
    invalid[4] = 255;
    Check(!DecodeNote(invalid.data(), invalid.size(), id, reopened), "overlong identifier rejected");
    invalid = bytes;
    // The last Unicode codepoint of the body is an emoji. Invalidate its
    // low surrogate before the 4 + 72 bytes for the folder ID field.
    invalid[invalid.size() - 4 - 72 - 1] = 0;
    Check(!DecodeNote(invalid.data(), invalid.size(), id, reopened, false), "invalid surrogate rejected in metadata path");
    Check(reopened.text == unchanged.text && reopened.folder_id == unchanged.folder_id, "failed read does not modify output");
    Check(IsDate(kCreated) && !IsDate(L"2025-02-29T12:34:56.123Z") && !IsDate(L"2024-02-29T24:34:56.123Z") &&
          !IsDate(L"2024-02-29T12:34:56x123Z"), "UTC dates validate the calendar");
    loaded.modified = L"2023-01-01T00:00:00.000Z";
    bytes.clear();
    EncodeNote(bytes, loaded);
    Check(!DecodeNote(bytes.data(), bytes.size(), id, reopened), "modification predates creation");
}

void Tree() {
    const Folder parent{Id(1), L"Cardiologie", {}, kCreated, kModified};
    const Folder child{Id(2), L"Consultations", parent.id, kCreated, kModified};
    const Folder leaf{Id(3), L"Suivi", child.id, kCreated, kModified};
    const Folder sibling{Id(4), L"Archives", {}, kCreated, kModified};
    std::vector<Folder> folders{parent, child, leaf, sibling};
    Check(ViewPath(folders, leaf.id) == L"Cardiologie / Consultations / Suivi", "nested path");
    auto moved = parent;
    moved.parent_id = parent.id;
    Check(CheckFolderMove(moved, folders) == MoveResult::Cycle, "self cycle");
    moved.parent_id = leaf.id;
    Check(CheckFolderMove(moved, folders) == MoveResult::Cycle, "descendant cycle");
    moved.parent_id = Id(99);
    Check(CheckFolderMove(moved, folders) == MoveResult::MissingParent, "destination must exist");
    moved.parent_id = sibling.id;
    Check(CheckFolderMove(moved, folders) == MoveResult::Ok, "whole subtree can move");
    std::vector<Byte> bytes;
    EncodeFolder(bytes, moved);
    Folder reloaded;
    Check(DecodeFolder(bytes.data(), bytes.size(), moved.id, reloaded) && reloaded.created == kCreated &&
          reloaded.modified == kModified, "folder survives serialization");
    Check(!DecodeFolder(bytes.data(), bytes.size(), leaf.id, reloaded) &&
          !DecodeFolder(bytes.data(), bytes.size() - 1, reloaded.id, reloaded), "folder corruption rejected");
    folders.front() = reloaded;
    Check(ViewPath(folders, leaf.id) == L"Archives / Cardiologie / Consultations / Suivi", "move preserves descendants");
    std::vector<Folder> nested;
    for (unsigned i = 1; i <= kMaxFolderDepth; ++i)
        nested.push_back({Id(i), L"Niveau", i == 1 ? L"" : Id(i - 1), kCreated, kModified});
    Check(RepairFolderView(nested), "exact depth limit valid");
    Check(CheckFolderMove({Id(99), L"trop loin", nested.back().id, kCreated, kModified}, nested) == MoveResult::TooDeep,
          "depth limit for new folder");
    nested.push_back({Id(99), L"Nouveau parent", {}, kCreated, kModified});
    auto deep = nested.front();
    deep.parent_id = nested.back().id;
    Check(CheckFolderMove(deep, nested) == MoveResult::TooDeep, "moving a subtree checks deepest descendant");

    folders.front().parent_id = leaf.id;
    Check(!RepairFolderView(folders) && folders[0].parent_id.empty() && folders[1].parent_id.empty() &&
          folders[2].parent_id.empty(), "cycle recovered to root in readable view");
    Check(!FolderTitle(L" \u00a0 ") && FolderTitle(L"Consultations"), "blank folder title rejected");
}

void QueryAndOrder() {
    const Folder parent{Id(12), L"Pôle", {}, kCreated, kModified};
    const Folder child{Id(13), L"Suivi", parent.id, kCreated, kModified};
    const std::vector<Folder> folders{parent, child};
    const FolderIndex index(folders);
    Note item{Id(1), L"Électrolytes", L"Œdème à l’œil\r\n    gauche.", kCreated, kModified, child.id};
    Query q{L"", parent.id, true, false, Sort::ModifiedNewest};
    Check(!MatchFolder(q, item, index), "folder only excludes child");
    q.include_descendants = true;
    Check(MatchFolder(q, item, index), "subtree includes child");
    Check(MatchText(Fold(L"OEDEME"), item) && MatchText(Fold(L"E\u0301lectrolytes"), item) &&
          MatchText(Fold(L"L'OEIL GAUCHE"), item), "case, accents, ligatures, typography and spacing match");
    Check(!MatchText(Fold(L"droite"), item), "search does not invent matches");
    q.folder_id.clear();
    q.include_descendants = false;
    Check(!MatchFolder(q, item, index), "unfiled only excludes known folder");
    item.folder_id = Id(99);
    Check(MatchFolder(q, item, index), "orphan note remains visible under unfiled");

    Note other{Id(2), L"abord", L"", L"2024-05-01T00:00:00.000Z", L"2024-06-01T00:00:00.000Z", L""};
    std::vector<Note> notes{item, other};
    OrderNotes(notes, Sort::CreatedNewest);
    Check(notes.front().id == other.id, "created descending");
    OrderNotes(notes, Sort::ModifiedNewest);
    Check(notes.front().id == item.id, "modified descending");
    OrderNotes(notes, Sort::TitleAscending);
    Check(notes.front().id == other.id, "title ascending");
    other.title = L"ELECTROLYTES";
    notes = {other, item};
    OrderNotes(notes, Sort::TitleAscending);
    Check(notes.front().id == item.id, "stable normalized title tie");
}

} // namespace

int main() {
    try {
        Format();
        Tree();
        QueryAndOrder();
        std::cout << "Notes model regression passed.\n";
    } catch (const std::exception& error) {
        std::cerr << "Notes model regression: " << error.what() << '\n';
        return 1;
    }
}
