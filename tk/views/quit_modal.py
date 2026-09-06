from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class QuitConfirmationModal(tk.Toplevel):
    """Modal dialog to confirm quitting when background processes are active."""

    def __init__(self, parent: tk.Tk, active_count: int) -> None:
        super().__init__(parent)
        self.active_count = active_count
        self.result = False

        self.title("Confirm Quit")
        self.geometry("460x180")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Center on parent window
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width() // 2) - (460 // 2)
        py = parent.winfo_y() + (parent.winfo_height() // 2) - (180 // 2)
        self.geometry(f"+{max(0, px)}+{max(0, py)}")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        warn_label = ttk.Label(
            frame,
            text=f"⚠️ Warning: {self.active_count} active service(s) running!",
            font=("Segoe UI", 11, "bold"),
            foreground="#d9534f",
        )
        warn_label.pack(anchor=tk.W, pady=(0, 8))

        msg_label = ttk.Label(
            frame,
            text="Do you want to stop all active services and quit industrial-flow?",
            wraplength=410,
            font=("Segoe UI", 10),
        )
        msg_label.pack(anchor=tk.W, pady=(0, 20))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, anchor=tk.E)

        stop_quit_btn = ttk.Button(btn_frame, text="Stop & Quit", command=self._on_confirm)
        stop_quit_btn.pack(side=tk.RIGHT, padx=(5, 0))

        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self._on_cancel)
        cancel_btn.pack(side=tk.RIGHT)

    def _on_confirm(self) -> None:
        self.result = True
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = False
        self.destroy()
