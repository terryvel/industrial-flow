from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from tk.models import ServiceType
from tk.process_manager import ServiceSpec


class ServiceFormModal(tk.Toplevel):
    """Modal dialog to configure, launch, or edit a service."""

    def __init__(
        self,
        parent: tk.Tk,
        on_submit: Callable[[ServiceSpec], None],
        initial_spec: ServiceSpec | None = None,
        title_text: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_submit = on_submit
        self.initial_spec = initial_spec
        self.title_string = title_text or ("Edit Service" if initial_spec else "Start New Service")

        self.title(self.title_string)
        self.geometry("520x540")
        self.minsize(460, 480)
        self.transient(parent)
        self.grab_set()

        # Center on parent window
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width() // 2) - (520 // 2)
        py = parent.winfo_y() + (parent.winfo_height() // 2) - (540 // 2)
        self.geometry(f"+{max(0, px)}+{max(0, py)}")

        self._build_ui()
        if self.initial_spec:
            self._populate_initial_spec(self.initial_spec)

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self, padding=16)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_lbl = ttk.Label(main_frame, text=self.title_string, font=("Segoe UI", 12, "bold"))
        title_lbl.pack(anchor=tk.W, pady=(0, 10))

        # Service type selector
        type_frame = ttk.Frame(main_frame)
        type_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(type_frame, text="Service Type:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))

        self.service_type_var = tk.StringVar(value="Realtime Stream")
        self.combo_type = ttk.Combobox(
            type_frame,
            textvariable=self.service_type_var,
            values=[
                "Realtime Stream",
                "Historical Backfill/Reconciliation",
                "PI Archive Writer",
            ],
            state="readonly",
        )
        self.combo_type.pack(fill=tk.X, pady=(0, 2))
        self.combo_type.bind("<<ComboboxSelected>>", self._on_service_type_changed)
        ttk.Label(type_frame, text="Select the runtime operational mode.", font=("Segoe UI", 8), foreground="#666").pack(anchor=tk.W)

        # Config path (common)
        cfg_frame = ttk.Frame(main_frame)
        cfg_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(cfg_frame, text="Config File Path:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        self.ent_config_path = ttk.Entry(cfg_frame)
        self.ent_config_path.insert(0, "config/config.yaml")
        self.ent_config_path.pack(fill=tk.X, pady=(0, 2))

        # Direct container frame for dynamic fields (without scrollbar canvas)
        self.fields_container = ttk.Frame(main_frame)
        self.fields_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Build Realtime frame
        self.frame_realtime = ttk.Frame(self.fields_container)
        self._build_realtime_fields(self.frame_realtime)

        # Build Historical frame
        self.frame_historical = ttk.Frame(self.fields_container)
        self._build_historical_fields(self.frame_historical)

        # Build Writer frame
        self.frame_writer = ttk.Frame(self.fields_container)
        self._build_writer_fields(self.frame_writer)

        # Show initial
        self._show_fields_for("Realtime Stream")

        # Error label
        self.lbl_error = ttk.Label(main_frame, text="", font=("Segoe UI", 9), foreground="#d9534f", wraplength=480)
        self.lbl_error.pack(fill=tk.X, pady=(0, 8))

        # Button Bar
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        btn_text = "Save Changes" if self.initial_spec else "Start Service"
        btn_start = ttk.Button(btn_frame, text=btn_text, command=self._on_start_click)
        btn_start.pack(side=tk.RIGHT, padx=(5, 0))

        btn_cancel = ttk.Button(btn_frame, text="Cancel", command=self.destroy)
        btn_cancel.pack(side=tk.RIGHT)

    def _build_realtime_fields(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Realtime Output Type (--type):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(4, 2))
        self.rt_type_var = tk.StringVar(value="Use Config Default")
        self.combo_rt_type = ttk.Combobox(
            parent,
            textvariable=self.rt_type_var,
            values=["Use Config Default", "console", "file", "kafka", "pubsub", "bigquery"],
            state="readonly",
        )
        self.combo_rt_type.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(parent, text="Target Site (--site):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))
        self.ent_rt_site = ttk.Entry(parent)
        self.ent_rt_site.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(parent, text="e.g. casa or site1,site2 (blank = all enabled)", font=("Segoe UI", 8), foreground="#666").pack(anchor=tk.W)

    def _build_historical_fields(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Start Datetime (--start):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(4, 2))
        self.ent_hist_start = ttk.Entry(parent)
        self.ent_hist_start.insert(0, "2026-09-01T00:00:00Z")
        self.ent_hist_start.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(parent, text="End Datetime (--end):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))
        self.ent_hist_end = ttk.Entry(parent)
        self.ent_hist_end.insert(0, "2026-09-02T00:00:00Z")
        self.ent_hist_end.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(parent, text="Historical Output Type (--type):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))
        self.hist_type_var = tk.StringVar(value="Use Config Default")
        self.combo_hist_type = ttk.Combobox(
            parent,
            textvariable=self.hist_type_var,
            values=["Use Config Default", "parquet", "parquet_gcs", "parquet_gcs_bigquery"],
            state="readonly",
        )
        self.combo_hist_type.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(parent, text="Tags List (--tags):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))
        self.ent_hist_tags = ttk.Entry(parent)
        self.ent_hist_tags.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(parent, text="Target Site (--site):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))
        self.ent_hist_site = ttk.Entry(parent)
        self.ent_hist_site.pack(fill=tk.X, pady=(0, 2))

    def _build_writer_fields(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Target Site (--site):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(4, 2))
        self.ent_w_site = ttk.Entry(parent)
        self.ent_w_site.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(parent, text="PI Tag (--tag):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))
        self.ent_w_tag = ttk.Entry(parent)
        self.ent_w_tag.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(parent, text="Timestamp (--timestamp):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))
        self.ent_w_ts = ttk.Entry(parent)
        self.ent_w_ts.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(parent, text="Numeric Value (--value):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))
        self.ent_w_val = ttk.Entry(parent)
        self.ent_w_val.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(parent, text="PI Status Code (--istat):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(6, 2))
        self.ent_w_istat = ttk.Entry(parent)
        self.ent_w_istat.insert(0, "0")
        self.ent_w_istat.pack(fill=tk.X, pady=(0, 2))

        self.w_wait_var = tk.BooleanVar(value=True)
        self.chk_w_wait = ttk.Checkbutton(parent, text="Wait Confirmation (--wait)", variable=self.w_wait_var)
        self.chk_w_wait.pack(anchor=tk.W, pady=(6, 2))

    def _populate_initial_spec(self, spec: ServiceSpec) -> None:
        # Config path
        self.ent_config_path.delete(0, tk.END)
        self.ent_config_path.insert(0, spec.config_path or "config/config.yaml")

        # Service type
        if spec.service_type == ServiceType.REALTIME:
            st_val = "Realtime Stream"
            self.service_type_var.set(st_val)
            self._show_fields_for(st_val)
            self.rt_type_var.set(spec.output_type or "Use Config Default")
            self.ent_rt_site.delete(0, tk.END)
            self.ent_rt_site.insert(0, spec.site or "")

        elif spec.service_type == ServiceType.HISTORICAL:
            st_val = "Historical Backfill/Reconciliation"
            self.service_type_var.set(st_val)
            self._show_fields_for(st_val)
            self.ent_hist_start.delete(0, tk.END)
            self.ent_hist_start.insert(0, spec.start or "")
            self.ent_hist_end.delete(0, tk.END)
            self.ent_hist_end.insert(0, spec.end or "")
            self.hist_type_var.set(spec.output_type or "Use Config Default")
            self.ent_hist_tags.delete(0, tk.END)
            self.ent_hist_tags.insert(0, spec.tags or "")
            self.ent_hist_site.delete(0, tk.END)
            self.ent_hist_site.insert(0, spec.site or "")

        elif spec.service_type == ServiceType.WRITER:
            st_val = "PI Archive Writer"
            self.service_type_var.set(st_val)
            self._show_fields_for(st_val)
            self.ent_w_site.delete(0, tk.END)
            self.ent_w_site.insert(0, spec.site or "")
            self.ent_w_tag.delete(0, tk.END)
            self.ent_w_tag.insert(0, spec.tag or "")
            self.ent_w_ts.delete(0, tk.END)
            self.ent_w_ts.insert(0, spec.timestamp or "")
            self.ent_w_val.delete(0, tk.END)
            self.ent_w_val.insert(0, str(spec.value) if spec.value is not None else "")
            self.ent_w_istat.delete(0, tk.END)
            self.ent_w_istat.insert(0, str(spec.istat))
            self.w_wait_var.set(spec.wait)

    def _on_service_type_changed(self, event=None) -> None:
        st_val = self.service_type_var.get()
        self._show_fields_for(st_val)

    def _show_fields_for(self, st_val: str) -> None:
        self.frame_realtime.pack_forget()
        self.frame_historical.pack_forget()
        self.frame_writer.pack_forget()

        if st_val == "Realtime Stream":
            self.frame_realtime.pack(fill=tk.X, expand=True)
        elif st_val == "Historical Backfill/Reconciliation":
            self.frame_historical.pack(fill=tk.X, expand=True)
        elif st_val == "PI Archive Writer":
            self.frame_writer.pack(fill=tk.X, expand=True)

    def _on_start_click(self) -> None:
        self.lbl_error.config(text="")
        cfg_path = self.ent_config_path.get().strip() or "config/config.yaml"
        st_val = self.service_type_var.get()

        if st_val == "Realtime Stream":
            out_raw = self.rt_type_var.get()
            out_type = None if out_raw == "Use Config Default" else out_raw
            site = self.ent_rt_site.get().strip() or None
            spec = ServiceSpec(
                service_type=ServiceType.REALTIME,
                config_path=cfg_path,
                output_type=out_type,
                site=site,
            )
            self.on_submit(spec)
            self.destroy()

        elif st_val == "Historical Backfill/Reconciliation":
            start_val = self.ent_hist_start.get().strip()
            end_val = self.ent_hist_end.get().strip()
            if not start_val or not end_val:
                self.lbl_error.config(text="Historical mode requires both --start and --end timestamps.")
                return

            out_raw = self.hist_type_var.get()
            out_type = None if out_raw == "Use Config Default" else out_raw
            site = self.ent_hist_site.get().strip() or None
            tags = self.ent_hist_tags.get().strip() or None

            spec = ServiceSpec(
                service_type=ServiceType.HISTORICAL,
                config_path=cfg_path,
                start=start_val,
                end=end_val,
                output_type=out_type,
                site=site,
                tags=tags,
            )
            self.on_submit(spec)
            self.destroy()

        elif st_val == "PI Archive Writer":
            site = self.ent_w_site.get().strip() or None
            tag = self.ent_w_tag.get().strip() or None
            ts = self.ent_w_ts.get().strip() or None
            val_str = self.ent_w_val.get().strip()
            istat_str = self.ent_w_istat.get().strip()
            wait_val = self.w_wait_var.get()

            val_float = None
            if val_str:
                try:
                    val_float = float(val_str)
                except ValueError:
                    self.lbl_error.config(text="Writer value must be a valid numeric float.")
                    return

            istat_int = 0
            if istat_str:
                try:
                    istat_int = int(istat_str)
                except ValueError:
                    self.lbl_error.config(text="Writer istat must be an integer.")
                    return

            spec = ServiceSpec(
                service_type=ServiceType.WRITER,
                config_path=cfg_path,
                site=site,
                tag=tag,
                timestamp=ts,
                value=val_float,
                istat=istat_int,
                wait=wait_val,
            )
            self.on_submit(spec)
            self.destroy()
