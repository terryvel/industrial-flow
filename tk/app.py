from __future__ import annotations

import argparse
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

# Add repository root to sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from tk.config_store import ConfigStore
from tk.process_manager import ProcessManager
from tk.async_loop import AsyncLoopThread
from tk.views.config_view import ConfigurationView
from tk.views.quit_modal import QuitConfirmationModal
from tk.views.services_view import ServicesView


class IndustrialFlowTkApp:
    """Tkinter application for industrial-flow services and configuration management."""

    TITLE = "industrial-flow GUI"
    SUB_TITLE = "PI/PIMS Data Bridge Control Center"

    def __init__(self, config_path: str | Path = "config/config.yaml") -> None:
        self.config_path = Path(config_path)
        self.config_store = ConfigStore(self.config_path)
        self.process_manager = ProcessManager()
        self.async_loop = AsyncLoopThread()

        self.root = tk.Tk()
        self.root.title(f"{self.TITLE} - {self.SUB_TITLE}")
        self.root.geometry("980x680")
        self.root.minsize(800, 550)

        self._configure_theme()
        self._build_ui()
        self._bind_shortcuts()

        self.root.protocol("WM_DELETE_WINDOW", self.on_request_quit)

    def _configure_theme(self) -> None:
        style = ttk.Style()
        # Try to use 'clam' or 'vista' if available
        available = style.theme_names()
        if "clam" in available:
            style.theme_use("clam")
        elif "vista" in available:
            style.theme_use("vista")

        style.configure(".", font=("Segoe UI", 9))
        style.configure("TButton", padding=5)
        style.configure("TNotebook.Tab", padding=(10, 5))

    def _build_ui(self) -> None:
        # Header bar
        header_frame = ttk.Frame(self.root, padding=(16, 12, 16, 8))
        header_frame.pack(fill=tk.X)

        title_lbl = ttk.Label(
            header_frame,
            text=self.TITLE,
            font=("Segoe UI", 14, "bold"),
            foreground="#1565c0",
        )
        title_lbl.pack(anchor=tk.W)

        sub_lbl = ttk.Label(
            header_frame,
            text=self.SUB_TITLE,
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        sub_lbl.pack(anchor=tk.W)

        separator = ttk.Separator(self.root, orient=tk.HORIZONTAL)
        separator.pack(fill=tk.X)

        # Notebook tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Tab 1: Services
        self.services_view = ServicesView(
            parent=self.notebook,
            manager=self.process_manager,
            run_coro_fn=self.run_coroutine,
        )
        self.notebook.add(self.services_view, text=" Services ")

        # Tab 2: Configuration
        self.config_view = ConfigurationView(
            parent=self.notebook,
            config_store=self.config_store,
        )
        self.notebook.add(self.config_view, text=" Configuration ")

        # Footer bar
        footer_frame = ttk.Frame(self.root, padding=(12, 4))
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)

        shortcut_lbl = ttk.Label(
            footer_frame,
            text="Shortcuts: [n] New Service  |  [e] Edit  |  [l] Log  |  [s] Stop  |  [r] Restart  |  [F5] Reload",
            font=("Segoe UI", 8),
            foreground="#777777",
        )
        shortcut_lbl.pack(side=tk.LEFT)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<n>", lambda e: self.services_view.open_new_service_modal())
        self.root.bind("<e>", lambda e: self.services_view.edit_selected_service())
        self.root.bind("<l>", lambda e: self.services_view.open_selected_log())
        self.root.bind("<s>", lambda e: self.services_view.stop_selected_service())
        self.root.bind("<r>", lambda e: self.services_view.restart_selected_service())
        self.root.bind("<F5>", lambda e: self.refresh_active_view())

    def run_coroutine(self, coro, callback=None) -> None:
        self.async_loop.run_coroutine(coro, callback=callback, tk_root=self.root)

    def refresh_active_view(self) -> None:
        active_tab = self.notebook.select()
        if active_tab == self.notebook.tabs()[0]:
            self.services_view.refresh_table()
        elif active_tab == self.notebook.tabs()[1]:
            self.config_view.reload_config()

    def on_request_quit(self) -> None:
        active = self.process_manager.active_count()
        if active > 0:
            modal = QuitConfirmationModal(self.root, active_count=active)
            self.root.wait_window(modal)
            if modal.result:
                self._shutdown_and_quit()
        else:
            self._shutdown_and_quit()

    def _shutdown_and_quit(self) -> None:
        def _on_all_stopped(res):
            self.async_loop.stop()
            self.root.destroy()

        coro = self.process_manager.stop_all(force=True)
        self.run_coroutine(coro, callback=_on_all_stopped)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="industrial-flow Tk GUI")
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to YAML configuration (default: config/config.yaml)",
    )
    args = parser.parse_args()
    app = IndustrialFlowTkApp(config_path=args.config)
    app.run()


if __name__ == "__main__":
    main()
