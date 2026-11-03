#!/usr/bin/env python3
"""Visual read-only inspector for N3 gameplay tables."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import queue
import sys
import threading

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.n3_gameplay_data import (
    AbilityRecord,
    GameData,
    GameplayDataError,
    ItemRecord,
    SoxRow,
    TableSource,
    UnitRecord,
    display_value,
    load_game_data,
    validate_corpus,
    write_structural_report,
)


DEFAULT_GAME_ROOT = PROJECT_ROOT / "private" / "game"


def _number(table: TableSource, row: SoxRow, name: str, occurrence: int = 0) -> str:
    indices = table.table.column_indices(name)
    if occurrence >= len(indices):
        return ""
    return display_value(row.values[indices[occurrence]], table.encoding)


def _unique_headings(source: TableSource) -> tuple[str, ...]:
    counts = Counter(column.name.casefold() for column in source.table.columns)
    seen: defaultdict[str, int] = defaultdict(int)
    labels = []
    for column in source.table.columns:
        key = column.name.casefold()
        seen[key] += 1
        suffix = f" [{seen[key]}]" if counts[key] > 1 else ""
        labels.append(f"{column.name}{suffix}")
    return tuple(labels)


def _short(value: str, limit: int = 180) -> str:
    normalized = value.replace("\r", " ").replace("\n", " ")
    return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"


class GameplayInspectorApp:
    def __init__(self, root, initial_game: Path | None = None):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title("N3 Gameplay Inspector")
        self.root.geometry("1440x900")
        self.root.minsize(1050, 700)

        self.data: GameData | None = None
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._table_sources: dict[str, TableSource] = {}
        self._unit_records: dict[str, UnitRecord] = {}
        self._item_records: dict[str, ItemRecord] = {}
        self._ability_records: dict[str, AbilityRecord] = {}
        self._generic_rows: dict[str, SoxRow] = {}
        self._current_table: TableSource | None = None
        self._loading = False

        self.game_path = tk.StringVar(
            value=str(initial_game) if initial_game is not None else ""
        )
        self.status_text = tk.StringVar(value="Choose an owned N3 extraction.")
        self.unit_filter = tk.StringVar()
        self.item_filter = tk.StringVar()
        self.ability_filter = tk.StringVar()
        self.table_filter = tk.StringVar()
        self.ability_language = tk.StringVar(value="ENG")

        self._configure_style()
        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()

        self.unit_filter.trace_add("write", lambda *_args: self._populate_units())
        self.item_filter.trace_add("write", lambda *_args: self._populate_items())
        self.ability_filter.trace_add(
            "write", lambda *_args: self._populate_abilities()
        )
        self.table_filter.trace_add(
            "write", lambda *_args: self._populate_generic_rows()
        )

        if initial_game is not None and initial_game.is_dir():
            self.root.after(150, self.load_selected_game)

    def _configure_style(self) -> None:
        style = self.ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Muted.TLabel", foreground="#5d6470")
        style.configure(
            "ReadOnly.TLabel",
            background="#1f5f8b",
            foreground="white",
            padding=(9, 4),
            font=("Segoe UI", 9, "bold"),
        )
        style.configure("Good.TLabel", foreground="#186a3b")
        style.configure("Warn.TLabel", foreground="#9a4f00")
        style.configure("Error.TLabel", foreground="#a61b1b")
        style.configure("Treeview", rowheight=24)

    def _build_menu(self) -> None:
        menu = self.tk.Menu(self.root)
        file_menu = self.tk.Menu(menu, tearoff=False)
        file_menu.add_command(
            label="Open Game Folder…", accelerator="Ctrl+O", command=self.choose_game
        )
        file_menu.add_command(
            label="Reload", accelerator="F5", command=self.load_selected_game
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Export Structural Report…",
            accelerator="Ctrl+E",
            command=self.export_report,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        help_menu = self.tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu)

    def _build_layout(self) -> None:
        ttk = self.ttk

        header = ttk.Frame(self.root, padding=(12, 10, 12, 8))
        header.pack(fill="x")
        ttk.Label(header, text="N3 Gameplay Inspector", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, text="READ ONLY", style="ReadOnly.TLabel").grid(
            row=0, column=1, padx=(12, 0), sticky="w"
        )
        ttk.Label(
            header,
            text="Character, enemy, item, ability, and raw SOX data",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(1, 8))
        ttk.Label(header, text="Game folder:").grid(row=2, column=0, sticky="w")
        self.path_entry = ttk.Entry(header, textvariable=self.game_path)
        self.path_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 8))
        ttk.Button(header, text="Browse…", command=self.choose_game).grid(
            row=2, column=3, padx=(0, 6)
        )
        self.load_button = ttk.Button(
            header, text="Load", command=self.load_selected_game
        )
        self.load_button.grid(row=2, column=4)
        header.columnconfigure(2, weight=1)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.overview_tab = ttk.Frame(self.notebook, padding=16)
        self.units_tab = ttk.Frame(self.notebook, padding=8)
        self.items_tab = ttk.Frame(self.notebook, padding=8)
        self.abilities_tab = ttk.Frame(self.notebook, padding=8)
        self.tables_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.overview_tab, text="Overview")
        self.notebook.add(self.units_tab, text="Units & Stats")
        self.notebook.add(self.items_tab, text="Items")
        self.notebook.add(self.abilities_tab, text="Abilities")
        self.notebook.add(self.tables_tab, text="All Tables")

        self._build_overview_tab()
        self._build_units_tab()
        self._build_items_tab()
        self._build_abilities_tab()
        self._build_tables_tab()

        status = ttk.Frame(self.root, padding=(12, 2, 12, 8))
        status.pack(fill="x")
        ttk.Separator(status).pack(fill="x", pady=(0, 5))
        ttk.Label(status, textvariable=self.status_text).pack(side="left")

    def _build_overview_tab(self) -> None:
        ttk = self.ttk
        ttk.Label(
            self.overview_tab, text="Extraction summary", style="Title.TLabel"
        ).pack(anchor="w")
        ttk.Label(
            self.overview_tab,
            text=(
                "Only data structure and values are displayed. "
                "This application never writes to the game extraction."
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        self.overview_text = self.tk.Text(
            self.overview_tab,
            wrap="word",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=10,
            font=("Segoe UI", 10),
        )
        self.overview_text.pack(fill="both", expand=True)
        self.overview_text.tag_configure(
            "heading", font=("Segoe UI", 12, "bold"), spacing1=8, spacing3=4
        )
        self.overview_text.tag_configure(
            "good", foreground="#186a3b", font=("Segoe UI", 10, "bold")
        )
        self.overview_text.tag_configure(
            "warn", foreground="#9a4f00", font=("Segoe UI", 10, "bold")
        )
        self.overview_text.tag_configure(
            "error", foreground="#a61b1b", font=("Segoe UI", 10, "bold")
        )
        self._set_text(
            self.overview_text,
            "No extraction is loaded.\n\nChoose private\\game or another owned extraction.",
        )

    def _build_units_tab(self) -> None:
        ttk = self.ttk
        pane = ttk.Panedwindow(self.units_tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane, padding=(0, 0, 8, 0))
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=3)

        ttk.Label(left, text="Units", style="Heading.TLabel").pack(anchor="w")
        ttk.Entry(left, textvariable=self.unit_filter).pack(fill="x", pady=(5, 7))
        self.unit_tree = self._scrolled_tree(
            left, ("name", "id", "type", "max"), selectmode="browse"
        )
        for column, label, width in (
            ("name", "Display name", 150),
            ("id", "Internal ID", 115),
            ("type", "Unit type", 75),
            ("max", "Max level", 70),
        ):
            self.unit_tree.heading(column, text=label)
            self.unit_tree.column(column, width=width, minwidth=55, stretch=True)
        self.unit_tree.bind("<<TreeviewSelect>>", self._show_selected_unit)

        self.unit_title = ttk.Label(
            right, text="Select a unit", style="Title.TLabel"
        )
        self.unit_title.pack(anchor="w", padx=6)
        self.unit_subtitle = ttk.Label(right, text="", style="Muted.TLabel")
        self.unit_subtitle.pack(anchor="w", padx=6, pady=(0, 5))
        unit_tabs = ttk.Notebook(right)
        unit_tabs.pack(fill="both", expand=True)

        identity = ttk.Frame(unit_tabs, padding=6)
        curves = ttk.Frame(unit_tabs, padding=6)
        hero = ttk.Frame(unit_tabs, padding=6)
        related = ttk.Frame(unit_tabs, padding=6)
        unit_tabs.add(identity, text="Identity")
        unit_tabs.add(curves, text="Level curves")
        unit_tabs.add(hero, text="Hero progression")
        unit_tabs.add(related, text="All related fields")

        self.unit_identity_tree = self._field_tree(identity)
        self.unit_curve_tree = self._scrolled_tree(
            curves,
            (
                "level",
                "atk_e",
                "atk_f",
                "def_e",
                "def_f",
                "hp_e",
                "hp_f",
                "crit_e",
                "crit_f",
                "orb",
                "exp",
                "guard_e",
                "guard_f",
                "guard_h",
                "true_orb",
                "match",
            ),
        )
        curve_labels = (
            ("level", "Level"),
            ("atk_e", "Attack enemy"),
            ("atk_f", "Attack friend"),
            ("def_e", "Defense enemy"),
            ("def_f", "Defense friend"),
            ("hp_e", "HP enemy"),
            ("hp_f", "HP friend"),
            ("crit_e", "Critical enemy"),
            ("crit_f", "Critical friend"),
            ("orb", "Orb Spark"),
            ("exp", "EXP"),
            ("guard_e", "Guard prob enemy"),
            ("guard_f", "Guard prob friend"),
            ("guard_h", "Guard prob hero"),
            ("true_orb", "True Orb atten."),
            ("match", "Level match"),
        )
        for column, label in curve_labels:
            self.unit_curve_tree.heading(column, text=label)
            self.unit_curve_tree.column(
                column,
                width=70 if column == "level" else 105,
                minwidth=65,
                stretch=False,
                anchor="e" if column != "level" else "center",
            )
        self.hero_tree = self._scrolled_tree(
            hero,
            (
                "level",
                "speed",
                "slots",
                "orb",
                "guard_def",
                "guard_hp",
                "troops",
                "units",
                "range",
            ),
        )
        for column, label in (
            ("level", "Hero level"),
            ("speed", "Move speed"),
            ("slots", "Slots"),
            ("orb", "Orb use"),
            ("guard_def", "Guard defense"),
            ("guard_hp", "Guard HP"),
            ("troops", "Troop count"),
            ("units", "Units/troop"),
            ("range", "Attack range"),
        ):
            self.hero_tree.heading(column, text=label)
            self.hero_tree.column(column, width=110, minwidth=70, anchor="e")
        self.unit_related_tree = self._scrolled_tree(
            related, ("table", "field", "value")
        )
        for column, label, width in (
            ("table", "Table", 170),
            ("field", "Field", 220),
            ("value", "Value", 280),
        ):
            self.unit_related_tree.heading(column, text=label)
            self.unit_related_tree.column(column, width=width, minwidth=100)

    def _build_items_tab(self) -> None:
        ttk = self.ttk
        ttk.Label(self.items_tab, text="Items", style="Heading.TLabel").pack(
            anchor="w"
        )
        ttk.Entry(self.items_tab, textvariable=self.item_filter).pack(
            fill="x", pady=(5, 7)
        )
        pane = ttk.Panedwindow(self.items_tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        top = ttk.Frame(pane)
        bottom = ttk.Frame(pane)
        pane.add(top, weight=3)
        pane.add(bottom, weight=2)

        self.item_tree = self._scrolled_tree(
            top, ("id", "name", "type", "level", "hero", "effects")
        )
        for column, label, width in (
            ("id", "ID", 55),
            ("name", "English name", 220),
            ("type", "Type", 75),
            ("level", "Minimum level", 95),
            ("hero", "Hero", 70),
            ("effects", "Effect IDs and values", 420),
        ):
            self.item_tree.heading(column, text=label)
            self.item_tree.column(column, width=width, minwidth=50)
        self.item_tree.bind("<<TreeviewSelect>>", self._show_selected_item)

        details = ttk.Panedwindow(bottom, orient="horizontal")
        details.pack(fill="both", expand=True, pady=(7, 0))
        description_frame = ttk.LabelFrame(details, text="Description", padding=6)
        effect_frame = ttk.LabelFrame(details, text="Effect slots", padding=6)
        raw_frame = ttk.LabelFrame(details, text="Raw fields", padding=6)
        details.add(description_frame, weight=2)
        details.add(effect_frame, weight=2)
        details.add(raw_frame, weight=3)
        self.item_description = self.tk.Text(
            description_frame, wrap="word", height=8, font=("Segoe UI", 10)
        )
        self.item_description.pack(fill="both", expand=True)
        self.item_effect_tree = self._scrolled_tree(
            effect_frame, ("slot", "type", "value")
        )
        for column, label, width in (
            ("slot", "Slot", 45),
            ("type", "Effect ID", 80),
            ("value", "Value", 80),
        ):
            self.item_effect_tree.heading(column, text=label)
            self.item_effect_tree.column(column, width=width, minwidth=45)
        self.item_raw_tree = self._field_tree(raw_frame)

    def _build_abilities_tab(self) -> None:
        ttk = self.ttk
        controls = ttk.Frame(self.abilities_tab)
        controls.pack(fill="x", pady=(0, 7))
        ttk.Label(controls, text="Abilities and moves", style="Heading.TLabel").pack(
            side="left"
        )
        ttk.Label(controls, text="Language:").pack(side="left", padx=(20, 5))
        self.language_combo = ttk.Combobox(
            controls,
            textvariable=self.ability_language,
            values=("ENG", "FRA", "GER", "ITA", "SPA"),
            width=6,
            state="readonly",
        )
        self.language_combo.pack(side="left")
        self.language_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._populate_abilities()
        )
        ttk.Entry(controls, textvariable=self.ability_filter).pack(
            side="right", fill="x", expand=True, padx=(20, 0)
        )

        pane = ttk.Panedwindow(self.abilities_tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        top = ttk.Frame(pane)
        bottom = ttk.LabelFrame(pane, text="Selected move", padding=7)
        pane.add(top, weight=4)
        pane.add(bottom, weight=1)
        self.ability_tree = self._scrolled_tree(
            top, ("character", "level", "name", "command")
        )
        for column, label, width in (
            ("character", "Character", 120),
            ("level", "Level", 55),
            ("name", "Move", 230),
            ("command", "Command", 460),
        ):
            self.ability_tree.heading(column, text=label)
            self.ability_tree.column(column, width=width, minwidth=50)
        self.ability_tree.bind(
            "<<TreeviewSelect>>", self._show_selected_ability
        )
        self.ability_details = self.tk.Text(
            bottom, wrap="word", height=6, font=("Segoe UI", 10)
        )
        self.ability_details.pack(fill="both", expand=True)

    def _build_tables_tab(self) -> None:
        ttk = self.ttk
        pane = ttk.Panedwindow(self.tables_tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane, padding=(0, 0, 8, 0))
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=4)

        ttk.Label(left, text="SOX tables", style="Heading.TLabel").pack(anchor="w")
        self.table_tree = self._scrolled_tree(
            left, (), selectmode="browse", show="tree"
        )
        self.table_tree.heading("#0", text="Table")
        self.table_tree.column("#0", width=300, minwidth=170)
        self.table_tree.bind("<<TreeviewSelect>>", self._select_table)

        self.table_title = ttk.Label(
            right, text="Select a table", style="Title.TLabel"
        )
        self.table_title.pack(anchor="w")
        self.table_metadata = ttk.Label(right, text="", style="Muted.TLabel")
        self.table_metadata.pack(anchor="w", pady=(0, 5))
        ttk.Entry(right, textvariable=self.table_filter).pack(
            fill="x", pady=(0, 7)
        )

        vertical = ttk.Panedwindow(right, orient="vertical")
        vertical.pack(fill="both", expand=True)
        grid_frame = ttk.Frame(vertical)
        detail_frame = ttk.LabelFrame(vertical, text="Selected row", padding=5)
        vertical.add(grid_frame, weight=4)
        vertical.add(detail_frame, weight=2)
        self.generic_tree = self._scrolled_tree(grid_frame, ())
        self.generic_tree.bind(
            "<<TreeviewSelect>>", self._show_selected_generic_row
        )
        self.generic_detail_tree = self._field_tree(detail_frame)

    def _scrolled_tree(
        self, parent, columns, selectmode="extended", show="headings"
    ):
        frame = self.ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = self.ttk.Treeview(
            frame, columns=columns, show=show, selectmode=selectmode
        )
        vertical = self.ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = self.ttk.Scrollbar(
            frame, orient="horizontal", command=tree.xview
        )
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def _field_tree(self, parent):
        tree = self._scrolled_tree(parent, ("field", "value"), selectmode="browse")
        tree.heading("field", text="Field")
        tree.heading("value", text="Value")
        tree.column("field", width=240, minwidth=120)
        tree.column("value", width=500, minwidth=180)
        return tree

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self.choose_game())
        self.root.bind("<Control-e>", lambda _event: self.export_report())
        self.root.bind("<F5>", lambda _event: self.load_selected_game())

    def choose_game(self) -> None:
        from tkinter import filedialog

        initial = self.game_path.get().strip()
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Choose the extracted N3 game folder",
            initialdir=initial if initial and Path(initial).is_dir() else PROJECT_ROOT,
            mustexist=True,
        )
        if selected:
            self.game_path.set(selected)
            self.load_selected_game()

    def load_selected_game(self) -> None:
        from tkinter import messagebox

        if self._loading:
            return
        raw_path = self.game_path.get().strip()
        if not raw_path:
            messagebox.showerror(
                "Game folder required",
                "Choose the folder containing default.xex and data\\PackedResources.",
                parent=self.root,
            )
            return
        path = Path(raw_path)
        self._loading = True
        self.load_button.configure(state="disabled")
        self.status_text.set("Loading gameplay data…")

        def worker() -> None:
            try:
                loaded = load_game_data(
                    path, lambda message: self._events.put(("progress", message))
                )
            except GameplayDataError as error:
                self._events.put(("error", str(error)))
                return
            self._events.put(("loaded", loaded))

        threading.Thread(target=worker, name="n3-inspector-loader", daemon=True).start()
        self.root.after(50, self._poll_load_events)

    def _poll_load_events(self) -> None:
        from tkinter import messagebox

        completed = False
        while True:
            try:
                event, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if event == "progress":
                self.status_text.set(str(payload))
            elif event == "error":
                completed = True
                self._loading = False
                self.load_button.configure(state="normal")
                self.status_text.set("Load failed.")
                messagebox.showerror(
                    "Cannot load gameplay data", str(payload), parent=self.root
                )
            elif event == "loaded":
                completed = True
                self._loading = False
                self.load_button.configure(state="normal")
                self._apply_data(payload)
        if self._loading and not completed:
            self.root.after(50, self._poll_load_events)

    def _apply_data(self, data: object) -> None:
        if not isinstance(data, GameData):
            raise TypeError("Loader returned an unexpected data model")
        self.data = data
        self.game_path.set(str(data.game_root))
        self._populate_overview()
        self._populate_units()
        self._populate_items()
        self._populate_abilities()
        self._populate_table_tree()
        warning_suffix = f" — {len(data.warnings)} warning(s)" if data.warnings else ""
        self.status_text.set(
            f"Loaded {len(data.tables)} tables from {data.game_root}{warning_suffix}"
        )

    def _populate_overview(self) -> None:
        if self.data is None:
            return
        data = self.data
        text = self.overview_text
        text.configure(state="normal")
        text.delete("1.0", "end")

        text.insert("end", "Supported build\n", "heading")
        tag = {
            "verified": "good",
            "mismatch": "error",
            "missing": "warn",
        }.get(data.build.status, "warn")
        text.insert("end", f"{data.build.status.upper()}: ", tag)
        text.insert("end", data.build.message + "\n")
        if data.build.actual_sha256:
            text.insert("end", f"SHA-256: {data.build.actual_sha256}\n")

        text.insert("end", "\nCore archive\n", "heading")
        archive_format = "zlib-wrapped" if data.archive_wrapped else "raw"
        text.insert(
            "end",
            f"{data.archive_name}: {archive_format}, "
            f"{data.archive_member_count} members, "
            f"{data.archive_duplicate_extra_count} extra duplicate records.\n",
        )

        categories = Counter(source.category for source in data.tables)
        text.insert("end", "\nLoaded tables\n", "heading")
        text.insert(
            "end",
            f"{len(data.tables)} SOX tables are available in this view.\n",
        )
        for category, count in sorted(categories.items()):
            text.insert("end", f"  • {category}: {count}\n")

        text.insert("end", "\nLanguage-specific mechanics archives\n", "heading")
        for variant in data.variants:
            variant_tag = "good" if variant.status == "identical" else "warn"
            text.insert("end", f"{variant.archive}: {variant.status}", variant_tag)
            text.insert(
                "end",
                f" ({variant.matched_tables}/{variant.expected_tables} core tables)\n",
            )

        text.insert("end", "\nValidation boundary\n", "heading")
        text.insert(
            "end",
            "Values are parsed from owned files and are not edited. Structural "
            "validity does not establish runtime loading, gameplay correctness, "
            "or save compatibility.\n",
        )
        if data.warnings:
            text.insert("end", "\nWarnings\n", "heading")
            for warning in data.warnings:
                text.insert("end", f"  • {warning}\n", "warn")
        text.configure(state="disabled")

    def _populate_units(self) -> None:
        self._clear_tree(self.unit_tree)
        self._unit_records.clear()
        if self.data is None:
            return
        source = self.data.table_source("CHARDATA.SOX")
        if source is None:
            return
        unit_type = source.table.column_index("unit type")
        max_level = source.table.column_index("MaxLevel")
        needle = self.unit_filter.get().strip().casefold()
        for record in self.data.units():
            haystack = f"{record.display_name} {record.unit_id}".casefold()
            if needle and needle not in haystack:
                continue
            iid = f"unit:{record.row.row_id}"
            self._unit_records[iid] = record
            self.unit_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    record.display_name,
                    record.unit_id,
                    display_value(record.row.values[unit_type], source.encoding),
                    display_value(record.row.values[max_level], source.encoding),
                ),
            )

    def _show_selected_unit(self, _event=None) -> None:
        selection = self.unit_tree.selection()
        if not selection or self.data is None:
            return
        record = self._unit_records.get(selection[0])
        source = self.data.table_source("CHARDATA.SOX")
        if record is None or source is None:
            return
        self.unit_title.configure(text=record.display_name)
        subtitle = record.unit_id
        if record.display_name != record.unit_id:
            subtitle += " — playable hero"
        self.unit_subtitle.configure(text=subtitle)

        self._fill_field_tree(
            self.unit_identity_tree,
            source,
            record.row,
        )
        self._populate_unit_curves(record)
        self._populate_hero_progression(record)

        self._clear_tree(self.unit_related_tree)
        for related_source, row in record.tables:
            headings = _unique_headings(related_source)
            for index, value in enumerate(row.values):
                self.unit_related_tree.insert(
                    "",
                    "end",
                    values=(
                        related_source.name,
                        headings[index],
                        display_value(value, related_source.encoding),
                    ),
                )

    def _populate_unit_curves(self, record: UnitRecord) -> None:
        self._clear_tree(self.unit_curve_tree)
        linked = {source.name.upper(): (source, row) for source, row in record.tables}

        def value(table_name: str, prefix: str, level: int) -> str:
            pair = linked.get(table_name)
            return _number(pair[0], pair[1], f"{prefix}{level}") if pair else ""

        for level in range(1, 13):
            self.unit_curve_tree.insert(
                "",
                "end",
                values=(
                    level,
                    value("ATTACKTABLE.SOX", "Attack_enemy", level),
                    value("ATTACKTABLE.SOX", "Attack_friend", level),
                    value("DEFENSETABLE.SOX", "Defense_enemy", level),
                    value("DEFENSETABLE.SOX", "Defense_friend", level),
                    value("HPTABLE.SOX", "HP_enemy", level),
                    value("HPTABLE.SOX", "HP_friend", level),
                    value("CRITICALTABLE.SOX", "Critical_enemy", level),
                    value("CRITICALTABLE.SOX", "Critical_friend", level),
                    value("ORBTABLE.SOX", "OrbSpark", level),
                    value("ORBTABLE.SOX", "Exp", level),
                    value(
                        "DEFENSEPROBTABLE.SOX", "DefenseProb_enemy", level
                    ),
                    value(
                        "DEFENSEPROBTABLE.SOX", "DefenseProb_friend", level
                    ),
                    value("DEFENSEPROBTABLE.SOX", "DefenseProb_Hero", level),
                    value("DEFENSETABLE.SOX", "TrueOrb_attenuation", level),
                    value("LEVELMATCHINGTABLE.SOX", "Level", level),
                ),
            )

    def _populate_hero_progression(self, record: UnitRecord) -> None:
        self._clear_tree(self.hero_tree)
        pair = next(
            (
                (source, row)
                for source, row in record.tables
                if source.name.casefold() == "herotable.sox"
            ),
            None,
        )
        if pair is None:
            return
        source, row = pair
        for level in range(1, 10):
            self.hero_tree.insert(
                "",
                "end",
                values=(
                    level,
                    _number(source, row, f"MoveSpeed{level}"),
                    _number(source, row, f"SlotCount{level}"),
                    _number(source, row, f"OrbDecrease{level}"),
                    _number(source, row, f"GuardianDefense{level}"),
                    _number(source, row, f"GuardianHP{level}"),
                    _number(source, row, f"GuardianControlTroopCount{level}"),
                    _number(
                        source, row, f"GuardianControlTroopUnitCount{level}"
                    ),
                    _number(source, row, f"AttackRange{level}"),
                ),
            )

    def _populate_items(self) -> None:
        self._clear_tree(self.item_tree)
        self._item_records.clear()
        if self.data is None:
            return
        source = self.data.table_source("ITEMTABLE.SOX")
        if source is None:
            return
        table = source.table
        type_index = table.column_index("ItemType")
        level_index = table.column_index("LevelMinimum")
        hero_index = table.column_index("Hero")
        needle = self.item_filter.get().strip().casefold()
        for record in self.data.items():
            effects = []
            for slot in range(1, 8):
                effect = _number(source, record.row, f"ParamType{slot}")
                value = _number(source, record.row, f"ParamVal{slot}")
                if effect and effect != "-1":
                    effects.append(f"{effect}={value}")
            searchable = (
                f"{record.row.row_id} {record.name} {record.description} "
                f"{' '.join(effects)}"
            ).casefold()
            if needle and needle not in searchable:
                continue
            iid = f"item:{record.row.row_id}"
            self._item_records[iid] = record
            self.item_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    record.row.row_id,
                    record.name,
                    display_value(record.row.values[type_index], source.encoding),
                    display_value(record.row.values[level_index], source.encoding),
                    display_value(record.row.values[hero_index], source.encoding),
                    ", ".join(effects),
                ),
            )

    def _show_selected_item(self, _event=None) -> None:
        selection = self.item_tree.selection()
        if not selection or self.data is None:
            return
        record = self._item_records.get(selection[0])
        source = self.data.table_source("ITEMTABLE.SOX")
        if record is None or source is None:
            return
        self._set_text(
            self.item_description,
            f"{record.name}\n\n{record.description or 'No English description.'}",
        )
        self._clear_tree(self.item_effect_tree)
        for slot in range(1, 8):
            effect = _number(source, record.row, f"ParamType{slot}")
            value = _number(source, record.row, f"ParamVal{slot}")
            self.item_effect_tree.insert("", "end", values=(slot, effect, value))
        self._fill_field_tree(self.item_raw_tree, source, record.row)

    def _populate_abilities(self) -> None:
        self._clear_tree(self.ability_tree)
        self._ability_records.clear()
        if self.data is None:
            return
        language = self.ability_language.get()
        needle = self.ability_filter.get().strip().casefold()
        for index, record in enumerate(self.data.abilities(language)):
            searchable = (
                f"{record.character} {record.level} {record.name} "
                f"{record.command} {record.caption}"
            ).casefold()
            if needle and needle not in searchable:
                continue
            iid = f"ability:{index}"
            self._ability_records[iid] = record
            self.ability_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    record.character,
                    record.level,
                    record.name,
                    record.command,
                ),
            )

    def _show_selected_ability(self, _event=None) -> None:
        selection = self.ability_tree.selection()
        if not selection:
            return
        record = self._ability_records.get(selection[0])
        if record is None:
            return
        self._set_text(
            self.ability_details,
            (
                f"{record.character} — level {record.level}\n"
                f"{record.name}\n\n"
                f"Command: {record.command or '(none)'}\n"
                f"Caption: {record.caption or '(none)'}\n"
                f"Source: {record.source}"
            ),
        )

    def _populate_table_tree(self) -> None:
        self._clear_tree(self.table_tree)
        self._table_sources.clear()
        self._current_table = None
        if self.data is None:
            return
        categories: defaultdict[str, list[TableSource]] = defaultdict(list)
        for source in self.data.tables:
            categories[source.category].append(source)
        for category in sorted(categories, key=str.casefold):
            category_id = f"category:{category}"
            self.table_tree.insert(
                "", "end", iid=category_id, text=category, open=True
            )
            for source in categories[category]:
                iid = f"table:{source.id}"
                self._table_sources[iid] = source
                label = source.name
                same_names = sum(
                    item.name.casefold() == source.name.casefold()
                    for item in categories[category]
                )
                if same_names > 1:
                    label += f" — {source.origin}"
                self.table_tree.insert(
                    category_id, "end", iid=iid, text=label
                )

    def _select_table(self, _event=None) -> None:
        selection = self.table_tree.selection()
        if not selection:
            return
        source = self._table_sources.get(selection[0])
        if source is None:
            return
        self._current_table = source
        self.table_title.configure(text=source.name)
        self.table_metadata.configure(
            text=(
                f"{source.description}  •  {len(source.table.rows)} rows  •  "
                f"{len(source.table.columns)} columns  •  key "
                f"0x{source.table.key:08X}  •  {source.origin}"
            )
        )
        self._configure_generic_columns(source)
        self._populate_generic_rows()

    def _configure_generic_columns(self, source: TableSource) -> None:
        column_ids = ("row_id",) + tuple(
            f"column_{index}" for index in range(len(source.table.columns))
        )
        self.generic_tree.configure(columns=column_ids)
        self.generic_tree.heading("row_id", text="Row ID")
        self.generic_tree.column(
            "row_id", width=65, minwidth=55, stretch=False, anchor="e"
        )
        for identifier, label, column in zip(
            column_ids[1:],
            _unique_headings(source),
            source.table.columns,
            strict=True,
        ):
            width = max(95, min(230, len(label) * 8 + 28))
            self.generic_tree.heading(identifier, text=label)
            self.generic_tree.column(
                identifier,
                width=width,
                minwidth=70,
                stretch=False,
                anchor="e" if column.type_code != 1 else "w",
            )

    def _populate_generic_rows(self) -> None:
        self._clear_tree(self.generic_tree)
        self._clear_tree(self.generic_detail_tree)
        self._generic_rows.clear()
        source = self._current_table
        if source is None:
            return
        needle = self.table_filter.get().strip().casefold()
        for row in source.table.rows:
            rendered = tuple(
                display_value(value, source.encoding) for value in row.values
            )
            if needle and needle not in (
                f"{row.row_id} {' '.join(rendered)}".casefold()
            ):
                continue
            iid = f"row:{row.row_id}"
            self._generic_rows[iid] = row
            self.generic_tree.insert(
                "", "end", iid=iid, values=(row.row_id,) + tuple(map(_short, rendered))
            )

    def _show_selected_generic_row(self, _event=None) -> None:
        selection = self.generic_tree.selection()
        source = self._current_table
        if not selection or source is None:
            return
        row = self._generic_rows.get(selection[0])
        if row is not None:
            self._fill_field_tree(self.generic_detail_tree, source, row)

    def _fill_field_tree(
        self, tree, source: TableSource, row: SoxRow
    ) -> None:
        self._clear_tree(tree)
        tree.insert("", "end", values=("Row ID", row.row_id))
        for label, value in zip(
            _unique_headings(source), row.values, strict=True
        ):
            tree.insert(
                "",
                "end",
                values=(label, display_value(value, source.encoding)),
            )

    @staticmethod
    def _clear_tree(tree) -> None:
        children = tree.get_children()
        if children:
            tree.delete(*children)

    @staticmethod
    def _set_text(widget, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def export_report(self) -> None:
        from tkinter import filedialog, messagebox

        if self.data is None:
            messagebox.showinfo(
                "Nothing to export",
                "Load an owned extraction first.",
                parent=self.root,
            )
            return
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export structural report",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            initialfile="n3-gameplay-structure.json",
        )
        if not selected:
            return
        try:
            write_structural_report(self.data, Path(selected))
        except GameplayDataError as error:
            messagebox.showerror("Export failed", str(error), parent=self.root)
            return
        self.status_text.set(f"Structural report written to {selected}")

    def show_about(self) -> None:
        from tkinter import messagebox

        messagebox.showinfo(
            "About N3 Gameplay Inspector",
            (
                "Dependency-free, read-only inspector for user-owned "
                "N3: Ninety-Nine Nights data.\n\n"
                "It decodes the known PAK and SOX structures but does not "
                "write archives or claim runtime gameplay compatibility."
            ),
            parent=self.root,
        )


def _require_game_path(path: Path | None) -> Path:
    if path is not None:
        return path
    if DEFAULT_GAME_ROOT.is_dir():
        return DEFAULT_GAME_ROOT
    raise GameplayDataError(
        "A game folder is required. Pass --game with the folder containing "
        "default.xex and data\\PackedResources."
    )


def _run_headless(args: argparse.Namespace) -> int | None:
    if not args.report and not args.validate_corpus:
        return None
    game_root = _require_game_path(args.game)
    progress = lambda message: print(message, file=sys.stderr)
    if args.validate_corpus:
        result = validate_corpus(game_root, progress)
        print(json.dumps(result, indent=2))
        return 0
    data = load_game_data(game_root, progress)
    write_structural_report(data, args.report)
    print(f"Wrote structural report: {args.report}")
    return 0


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect N3 PAK and SOX gameplay data without modifying it."
    )
    parser.add_argument(
        "--game",
        type=Path,
        help="extracted game folder containing default.xex and data",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--report",
        type=Path,
        help="write a structural JSON report and exit without opening the UI",
    )
    action.add_argument(
        "--validate-corpus",
        action="store_true",
        help="validate all PackedResources PAKs and all loose/packed SOX tables",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        headless_result = _run_headless(args)
    except GameplayDataError as error:
        parser.exit(1, f"error: {error}\n")
    if headless_result is not None:
        return headless_result

    try:
        import tkinter as tk
    except ImportError as error:
        parser.exit(
            1,
            "error: Tkinter is unavailable in this Python installation. "
            f"Install Python with Tcl/Tk support ({error}).\n",
        )
    initial_game = args.game
    if initial_game is None and DEFAULT_GAME_ROOT.is_dir():
        initial_game = DEFAULT_GAME_ROOT
    root = tk.Tk()
    GameplayInspectorApp(root, initial_game)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
