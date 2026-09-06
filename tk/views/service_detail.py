from __future__ import annotations

import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Callable

from tk.models import LogEntry, LogSource, ProcessStatus
from datetime import timezone


def format_local_time(dt: Any) -> str:
    if not dt:
        return "-"
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%H:%M:%S")


class ServiceDetailWindow(tk.Toplevel):
    """Window inspecting live logs and details of a single managed service."""

    def __init__(
        self,
        parent: tk.Tk,
        process_id: str,
        manager: ProcessManager,
        stop_service_cb: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self.process_id = process_id
        self.manager = manager
        self.stop_service_cb = stop_service_cb
        self.process: ManagedProcess | None = manager.get_process(process_id)

        self.auto_scroll_var = tk.BooleanVar(value=True)

        self.title(f"Service Detail — ID {process_id}")
        self.geometry("850x550")
        self.minsize(650, 400)
        self.transient(parent)

        self._build_ui()

        # Wire listeners safely into Tk thread
        self.manager.add_log_listener(self._on_log_entry_bg)
        self.manager.add_status_listener(self._on_status_change_bg)

        # Populate initial historical logs
        self._populate_initial_logs()
        self._update_process_info()

        # Timer for runtime update
        self._tick_runtime()

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_lbl = ttk.Label(
            main_frame,
            text=f"Service Detail — ID {self.process_id}",
            font=("Segoe UI", 12, "bold"),
        )
        title_lbl.pack(anchor=tk.W, pady=(0, 8))

        # Info Card Box
        info_frame = ttk.LabelFrame(main_frame, text=" Process Information ", padding=8)
        info_frame.pack(fill=tk.X, pady=(0, 8))

        self.lbl_info_summary = ttk.Label(info_frame, font=("Segoe UI", 9), justify=tk.LEFT)
        self.lbl_info_summary.pack(anchor=tk.W, fill=tk.X)

        self.lbl_info_cmd = ttk.Label(info_frame, font=("Consolas", 8, "italic"), foreground="#555555", wraplength=800)
        self.lbl_info_cmd.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))

        # Action bar
        bar_frame = ttk.Frame(main_frame)
        bar_frame.pack(fill=tk.X, pady=(0, 8))

        chk_autoscroll = ttk.Checkbutton(
            bar_frame,
            text="Auto-scroll log",
            variable=self.auto_scroll_var,
        )
        chk_autoscroll.pack(side=tk.LEFT, padx=(0, 10))

        btn_clear = ttk.Button(bar_frame, text="Clear Log View", command=self.clear_logs)
        btn_clear.pack(side=tk.LEFT, padx=(0, 5))

        btn_stop = ttk.Button(bar_frame, text="Stop Process", command=self._on_stop_click)
        btn_stop.pack(side=tk.LEFT, padx=(0, 5))

        btn_back = ttk.Button(bar_frame, text="Back to Services", command=self.destroy)
        btn_back.pack(side=tk.RIGHT)

        # Log viewer (ScrolledText)
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.txt_log = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            font=("Consolas", 9),
            background="#1e1e1e",
            foreground="#d4d4d4",
            insertbackground="#ffffff",
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # Text Tags for Log colors
        self.txt_log.tag_config("STDOUT", foreground="#d4d4d4")
        self.txt_log.tag_config("STDERR", foreground="#f44336")
        self.txt_log.tag_config("SYSTEM", foreground="#00bcd4", font=("Consolas", 9, "bold"))
        self.txt_log.tag_config("TS", foreground="#888888")

    def _populate_initial_logs(self) -> None:
        if not self.process:
            return
        for entry in list(self.process.log_entries):
            self._append_log_entry(entry)

    def _update_process_info(self) -> None:
        if not self.process:
            self.lbl_info_summary.config(text="Process not found.")
            return

        summary = (
            f"Service: {self.process.spec.service_type.value}  |  "
            f"Target: {self.process.spec.target_summary()}  |  "
            f"PID: {self.process.pid or '-'}  |  "
            f"Status: {self.process.status.value}  |  "
            f"Started: {format_local_time(self.process.started_at)}  |  "
            f"Runtime: {self.process.formatted_runtime()}"
        )
        self.lbl_info_summary.config(text=summary)

        cmd_str = f"Command: {' '.join(self.process.command_args)}"
        self.lbl_info_cmd.config(text=cmd_str)

    def _tick_runtime(self) -> None:
        if not self.winfo_exists():
            return
        if self.process and self.process.status in (ProcessStatus.STARTING, ProcessStatus.RUNNING, ProcessStatus.STOPPING):
            self._update_process_info()
        self.after(1000, self._tick_runtime)

    def _on_log_entry_bg(self, proc: ManagedProcess, entry: LogEntry) -> None:
        if proc.id == self.process_id and self.winfo_exists():
            self.after(0, lambda: self._append_log_entry(entry))

    def _on_status_change_bg(self, proc: ManagedProcess) -> None:
        if proc.id == self.process_id and self.winfo_exists():
            self.after(0, self._update_process_info)

    def _append_log_entry(self, entry: LogEntry) -> None:
        if not self.winfo_exists():
            return

        ts_str = f"[{format_local_time(entry.timestamp)}] "
        src_tag = entry.source.value

        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.insert(tk.END, ts_str, "TS")
        self.txt_log.insert(tk.END, f"[{src_tag}] {entry.text}\n", src_tag)
        self.txt_log.configure(state=tk.DISABLED)

        if self.auto_scroll_var.get():
            self.txt_log.see(tk.END)

    def clear_logs(self) -> None:
        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.configure(state=tk.DISABLED)

    def _on_stop_click(self) -> None:
        if self.process:
            self.stop_service_cb(self.process_id)
