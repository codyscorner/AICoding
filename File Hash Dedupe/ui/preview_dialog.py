"""Preview/review dialog shown before any duplicate is moved or deleted"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt

from hasher import FileDeduplicator, ScanResult, KEEP_RULES


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


class PreviewDialog(QDialog):
    """
    Shows every duplicate group found by a scan, with the chosen primary (kept file)
    highlighted, before anything is moved or deleted. In single-folder mode the keep
    rule can be changed live to recompute which copy survives, without re-hashing.
    """

    def __init__(self, deduplicator: FileDeduplicator, scan_result: ScanResult,
                 compare_mode: bool = False, permanent_delete: bool = False,
                 clear_read_only: bool = False, parent=None):
        super().__init__(parent)
        self.deduplicator = deduplicator
        self.scan_result = scan_result
        self.compare_mode = compare_mode
        self.permanent_delete = permanent_delete
        self.clear_read_only = clear_read_only

        action_word = "delete" if permanent_delete else "move"
        title = "Review Matches" if compare_mode else "Review Duplicates"
        self.setWindowTitle(title)
        self.resize(900, 600)

        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()
        self.summary_label = QLabel()
        header_row.addWidget(self.summary_label, stretch=1)

        if not compare_mode:
            header_row.addWidget(QLabel("Keep:"))
            self.keep_rule_combo = QComboBox()
            self.keep_rule_combo.addItems(KEEP_RULES)
            self.keep_rule_combo.setCurrentText(scan_result.keep_rule)
            self.keep_rule_combo.currentTextChanged.connect(self._on_keep_rule_changed)
            header_row.addWidget(self.keep_rule_combo)
        layout.addLayout(header_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Role", "Size"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, stretch=1)

        note = "Reference folder (A) files are never modified." if compare_mode else \
            f"Only files marked 'duplicate' will be {action_word}d. Change the keep rule above to pick a different survivor."
        note_label = QLabel(note)
        note_label.setObjectName("subtitle")
        layout.addWidget(note_label)

        # Read-only check: only matters when deleting (moves are renames, which Windows allows)
        self.read_only_label = QLabel()
        self.read_only_label.setTextFormat(Qt.TextFormat.RichText)
        self.read_only_label.setWordWrap(True)
        self.read_only_label.setVisible(False)
        layout.addWidget(self.read_only_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.proceed_btn = QPushButton(f"{action_word.capitalize()} Duplicates")
        self.proceed_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.proceed_btn)
        layout.addLayout(btn_row)

        self._rebuild_tree()

    def _on_keep_rule_changed(self, keep_rule: str) -> None:
        self.scan_result = self.deduplicator.rescan_keep_rule(self.scan_result, keep_rule)
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        self.tree.setUpdatesEnabled(False)       # big drives can produce tens of thousands of rows
        self.tree.clear()

        remove_paths = {entry.path for _, entry in self.scan_result.to_remove}
        duplicate_count = len(remove_paths)
        reclaimable_bytes = sum(entry.size for _, entry in self.scan_result.to_remove)

        # Groups and their members arrive in SQL rank order: largest files first, kept copy first
        for file_hash, entries in self.scan_result.groups.items():
            primary = self.scan_result.primary_map[file_hash]
            rows = list(entries)
            if all(e.path != primary.path for e in rows):      # compare mode: kept file is in folder A
                rows.insert(0, primary)
            group_item = QTreeWidgetItem([f"Group ({len(rows)} copies)", "", _format_size(primary.size)])
            group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(group_item)

            for entry in rows:
                if entry.path in remove_paths:
                    role = "Duplicate"
                elif entry.path == primary.path:
                    role = "Kept (reference A)" if self.compare_mode else "Kept (primary)"
                else:
                    role = "Kept"
                group_item.addChild(QTreeWidgetItem([entry.path, role, _format_size(entry.size)]))

            group_item.setExpanded(True)
        self.tree.setUpdatesEnabled(True)

        if self.compare_mode:
            self.summary_label.setText(
                f"{duplicate_count:,} file(s) in the target folder already exist in the reference folder "
                f"— {_format_size(reclaimable_bytes)} reclaimable"
            )
        else:
            self.summary_label.setText(
                f"{len(self.scan_result.groups):,} duplicate group(s), {duplicate_count:,} duplicate file(s) "
                f"— {_format_size(reclaimable_bytes)} reclaimable"
            )

        self.proceed_btn.setEnabled(duplicate_count > 0)

        read_only = sum(1 for _, e in self.scan_result.to_remove if e.path in self.scan_result.read_only_paths)
        if self.permanent_delete and read_only:
            if self.clear_read_only:
                text = (f"<span style='color:#4caf50'>●</span> {read_only:,} of the files to delete are "
                        f"read-only - their read-only flag will be cleared first.")
            else:
                text = (f"<span style='color:#f0a030'>●</span> {read_only:,} of the files to delete are "
                        f"read-only and will fail with 'Access is denied'. Cancel and tick "
                        f"'Clear read-only flag' to delete them.")
            self.read_only_label.setText(text)
        self.read_only_label.setVisible(bool(self.permanent_delete and read_only))

    def get_scan_result(self) -> ScanResult:
        return self.scan_result
