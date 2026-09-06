from __future__ import annotations

import copy
import tkinter as tk
from tkinter import ttk
from typing import Any

from tk.config_store import DEFAULT_SITE, ConfigStore


class ConfigurationView(ttk.Frame):
    """View component for visually editing and validating config/config.yaml."""

    def __init__(self, parent: tk.Widget, config_store: ConfigStore, **kwargs) -> None:
        super().__init__(parent, padding=12, **kwargs)
        self.store = config_store
        self.current_site_index: int = 0

        self._build_ui()
        self.populate_form()

    def _build_ui(self) -> None:
        # Title
        title_lbl = ttk.Label(self, text="Configuration Editor — config/config.yaml", font=("Segoe UI", 12, "bold"))
        title_lbl.pack(anchor=tk.W, pady=(0, 10))

        # Button Bar
        btn_bar = ttk.Frame(self)
        btn_bar.pack(fill=tk.X, pady=(0, 5))

        btn_val = ttk.Button(btn_bar, text="Validate Configuration", command=self.validate_config)
        btn_val.pack(side=tk.LEFT, padx=(0, 5))

        btn_rel = ttk.Button(btn_bar, text="Reload from Disk", command=self.reload_config)
        btn_rel.pack(side=tk.LEFT, padx=(0, 5))

        btn_save = ttk.Button(btn_bar, text="Save Configuration", command=self.save_config)
        btn_save.pack(side=tk.LEFT, padx=(0, 5))

        # Status feedback banner label
        self.lbl_status = ttk.Label(self, text="", font=("Segoe UI", 9), wraplength=750)
        self.lbl_status.pack(fill=tk.X, pady=(0, 8))

        # Configuration Sub-Notebook (Tabs for 5 sections)
        self.config_notebook = ttk.Notebook(self)
        self.config_notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Plant / Site Management (First tab as requested)
        tab_sites = self._create_scrollable_tab(self.config_notebook, "Plant / Site Management")
        self._build_sites_section(tab_sites)

        # Tab 2: Cache
        tab_cache = self._create_scrollable_tab(self.config_notebook, "Cache")
        self._build_cache_section(tab_cache)

        # Tab 3: Writer
        tab_writer = self._create_scrollable_tab(self.config_notebook, "Writer")
        self._build_writer_section(tab_writer)

        # Tab 4: Realtime
        tab_realtime = self._create_scrollable_tab(self.config_notebook, "Realtime")
        self._build_realtime_section(tab_realtime)

        # Tab 5: Historical
        tab_historical = self._create_scrollable_tab(self.config_notebook, "Historical")
        self._build_historical_section(tab_historical)

    def _create_scrollable_tab(self, notebook: ttk.Notebook, tab_title: str) -> ttk.Frame:
        tab_frame = ttk.Frame(notebook)
        canvas = tk.Canvas(tab_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab_frame, orient=tk.VERTICAL, command=canvas.yview)
        scroll_content = ttk.Frame(canvas, padding=10)

        scroll_content.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas_window = canvas.create_window((0, 0), window=scroll_content, anchor=tk.NW)

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        notebook.add(tab_frame, text=f" {tab_title} ")
        return scroll_content

    def _create_section_header(self, parent: ttk.Frame, title: str) -> None:
        lbl = ttk.Label(parent, text=title, font=("Segoe UI", 10, "bold"), foreground="#1976d2")
        lbl.pack(anchor=tk.W, pady=(4, 8))

    def _create_field_row(self, parent: ttk.Frame, label_text: str, help_text: str = "") -> tuple[ttk.Frame, ttk.Entry]:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=3)

        lbl = ttk.Label(row, text=label_text, width=32, anchor=tk.W, font=("Segoe UI", 9))
        lbl.pack(side=tk.LEFT, padx=(0, 5))

        ent = ttk.Entry(row)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)

        if help_text:
            hlp = ttk.Label(row, text=help_text, font=("Segoe UI", 8), foreground="#666666")
            hlp.pack(side=tk.LEFT, padx=(6, 0))

        return row, ent

    def _create_combo_row(self, parent: ttk.Frame, label_text: str, values: list[str], help_text: str = "") -> tuple[ttk.Frame, ttk.Combobox]:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=3)

        lbl = ttk.Label(row, text=label_text, width=32, anchor=tk.W, font=("Segoe UI", 9))
        lbl.pack(side=tk.LEFT, padx=(0, 5))

        var = tk.StringVar()
        combo = ttk.Combobox(row, textvariable=var, values=values, state="readonly")
        combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        if help_text:
            hlp = ttk.Label(row, text=help_text, font=("Segoe UI", 8), foreground="#666666")
            hlp.pack(side=tk.LEFT, padx=(6, 0))

        return row, combo

    def _create_check_row(self, parent: ttk.Frame, label_text: str, help_text: str = "") -> tuple[ttk.Frame, tk.BooleanVar]:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=3)

        var = tk.BooleanVar(value=True)
        chk = ttk.Checkbutton(row, text=label_text, variable=var)
        chk.pack(side=tk.LEFT, padx=(0, 5))

        if help_text:
            hlp = ttk.Label(row, text=help_text, font=("Segoe UI", 8), foreground="#666666")
            hlp.pack(side=tk.LEFT, padx=(6, 0))

        return row, var

    def _build_cache_section(self, parent: ttk.Frame) -> None:
        self._create_section_header(parent, "Cache Configuration")
        _, self.ent_cache_point = self._create_field_row(parent, "Point Cache File:", "Path to local JSON cache for PI point IDs.")
        _, self.ent_cache_digital = self._create_field_row(parent, "Digital State Cache File:", "Path to local JSON cache for PI digital state names.")

    def _build_writer_section(self, parent: ttk.Frame) -> None:
        self._create_section_header(parent, "Writer Configuration")
        _, self.combo_writer_type = self._create_combo_row(parent, "Writer Type:", ["console", "pubsub"], "Input source mode for PI archive writing.")

        pubsub_frame = ttk.LabelFrame(parent, text=" Pub/Sub Configuration ", padding=10)
        pubsub_frame.pack(fill=tk.X, pady=(10, 0))

        _, self.ent_writer_pubsub_proj = self._create_field_row(pubsub_frame, "Pub/Sub Project ID:")
        _, self.ent_writer_pubsub_sub = self._create_field_row(pubsub_frame, "Pub/Sub Subscription ID:")
        _, self.ent_writer_pubsub_sa = self._create_field_row(pubsub_frame, "Pub/Sub Service Account File:")

    def _build_realtime_section(self, parent: ttk.Frame) -> None:
        self._create_section_header(parent, "Realtime Stream Configuration")
        _, self.combo_rt_type = self._create_combo_row(parent, "Realtime Type:", ["console", "file", "kafka", "pubsub", "bigquery"], "Default publisher target.")

        read_lf = ttk.LabelFrame(parent, text=" Read & Ingestion Settings ", padding=10)
        read_lf.pack(fill=tk.X, pady=(10, 0))
        _, self.ent_rt_interval = self._create_field_row(read_lf, "Interval Seconds:")
        _, self.ent_rt_window = self._create_field_row(read_lf, "Window Seconds:")
        _, self.ent_rt_partition = self._create_field_row(read_lf, "Tag Partition Size:")
        _, self.ent_rt_workers = self._create_field_row(read_lf, "Max Workers:")
        _, self.ent_rt_batch = self._create_field_row(read_lf, "Batch Size:")
        _, self.ent_rt_retries = self._create_field_row(read_lf, "Max Publish Retries:")
        _, self.ent_rt_retry_sleep = self._create_field_row(read_lf, "Retry Sleep Seconds:")

        file_lf = ttk.LabelFrame(parent, text=" File Publisher ", padding=10)
        file_lf.pack(fill=tk.X, pady=(10, 0))
        _, self.ent_rt_file_path = self._create_field_row(file_lf, "File Output Path:")

        kafka_lf = ttk.LabelFrame(parent, text=" Kafka Publisher ", padding=10)
        kafka_lf.pack(fill=tk.X, pady=(10, 0))
        _, self.ent_rt_kafka_servers = self._create_field_row(kafka_lf, "Kafka Bootstrap Servers:")
        _, self.ent_rt_kafka_topic = self._create_field_row(kafka_lf, "Kafka Topic:")

        bq_lf = ttk.LabelFrame(parent, text=" BigQuery Publisher ", padding=10)
        bq_lf.pack(fill=tk.X, pady=(10, 0))
        _, self.ent_rt_bq_proj = self._create_field_row(bq_lf, "BigQuery Project ID:")
        _, self.ent_rt_bq_dataset = self._create_field_row(bq_lf, "BigQuery Dataset:")
        _, self.ent_rt_bq_table = self._create_field_row(bq_lf, "BigQuery Table:")
        _, self.ent_rt_bq_sa = self._create_field_row(bq_lf, "BigQuery SA File:")

    def _build_historical_section(self, parent: ttk.Frame) -> None:
        self._create_section_header(parent, "Historical Backfill Configuration")
        _, self.combo_hist_type = self._create_combo_row(parent, "Historical Type:", ["parquet", "parquet_gcs", "parquet_gcs_bigquery"])

        read_lf = ttk.LabelFrame(parent, text=" Read & Ingestion Settings ", padding=10)
        read_lf.pack(fill=tk.X, pady=(10, 0))
        _, self.ent_hist_interval = self._create_field_row(read_lf, "Historical Interval Seconds:")
        _, self.ent_hist_window = self._create_field_row(read_lf, "Historical Window Seconds:")
        _, self.ent_hist_partition = self._create_field_row(read_lf, "Historical Tag Partition Size:")
        _, self.ent_hist_workers = self._create_field_row(read_lf, "Historical Max Workers:")
        _, self.ent_hist_batch = self._create_field_row(read_lf, "Historical Batch Size:")

        parquet_lf = ttk.LabelFrame(parent, text=" Parquet Local Storage ", padding=10)
        parquet_lf.pack(fill=tk.X, pady=(10, 0))
        _, self.ent_hist_parquet_dir = self._create_field_row(parquet_lf, "Parquet Output Dir:")

        gcs_lf = ttk.LabelFrame(parent, text=" Google Cloud Storage (GCS) ", padding=10)
        gcs_lf.pack(fill=tk.X, pady=(10, 0))
        _, self.ent_hist_gcs_bucket = self._create_field_row(gcs_lf, "GCS Bucket:")
        _, self.var_hist_gcs_delete = self._create_check_row(gcs_lf, "GCS Delete Local File After Upload")
        _, self.ent_hist_gcs_sa = self._create_field_row(gcs_lf, "GCS SA File:")

        bq_lf = ttk.LabelFrame(parent, text=" BigQuery Load Settings ", padding=10)
        bq_lf.pack(fill=tk.X, pady=(10, 0))
        _, self.ent_hist_bq_proj = self._create_field_row(bq_lf, "Historical BigQuery Project ID:")
        _, self.ent_hist_bq_dataset = self._create_field_row(bq_lf, "Historical BigQuery Dataset:")
        _, self.ent_hist_bq_table = self._create_field_row(bq_lf, "Historical BigQuery Table:")
        _, self.ent_hist_bq_sa = self._create_field_row(bq_lf, "Historical BigQuery SA File:")

    def _build_sites_section(self, parent: ttk.Frame) -> None:
        self._create_section_header(parent, "Plant / Site Management")

        site_btn_frame = ttk.Frame(parent)
        site_btn_frame.pack(fill=tk.X, pady=(0, 6))

        btn_add = ttk.Button(site_btn_frame, text="Add Site", command=self.add_site)
        btn_add.pack(side=tk.LEFT, padx=(0, 5))

        btn_del = ttk.Button(site_btn_frame, text="Delete Selected Site", command=self.delete_site)
        btn_del.pack(side=tk.LEFT)

        # Listbox for sites
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.X, pady=(0, 8))

        self.list_sites = tk.Listbox(list_frame, height=4, exportselection=False)
        self.list_sites.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.list_sites.bind("<<ListboxSelect>>", self._on_site_selected)

        s_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.list_sites.yview)
        s_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_sites.config(yscrollcommand=s_scroll.set)

        # Site fields
        _, self.ent_site_id = self._create_field_row(parent, "Site ID:")
        _, self.var_site_enabled = self._create_check_row(parent, "Site Enabled")
        _, self.combo_site_pi_provider = self._create_combo_row(parent, "PI Provider:", ["piapi", "simulator"])
        _, self.ent_site_pi_server = self._create_field_row(parent, "PI Server Name:")
        _, self.ent_site_pi_tz = self._create_field_row(parent, "PI Timezone:")
        _, self.ent_site_pi_user = self._create_field_row(parent, "PI Username:")

        row_pass = ttk.Frame(parent)
        row_pass.pack(fill=tk.X, pady=3)
        ttk.Label(row_pass, text="PI Password:", width=32, anchor=tk.W, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 5))
        self.ent_site_pi_pass = ttk.Entry(row_pass, show="*")
        self.ent_site_pi_pass.pack(side=tk.LEFT, fill=tk.X, expand=True)

        _, self.ent_site_tags_file = self._create_field_row(parent, "Tags File Path:")

    def populate_form(self) -> None:
        store = self.store

        # Cache
        self._set_ent(self.ent_cache_point, store.get_value_by_path("cache.point_cache_file", ".cache/industrial-flow-pointids.json"))
        self._set_ent(self.ent_cache_digital, store.get_value_by_path("cache.digital_state_cache_file", ".cache/industrial-flow-digital-states.json"))

        # Writer
        self._set_combo(self.combo_writer_type, store.get_value_by_path("writer.type", "console"))
        self._set_ent(self.ent_writer_pubsub_proj, store.get_value_by_path("writer.pubsub.project_id", ""))
        self._set_ent(self.ent_writer_pubsub_sub, store.get_value_by_path("writer.pubsub.subscription_id", ""))
        self._set_ent(self.ent_writer_pubsub_sa, store.get_value_by_path("writer.pubsub.service_account_file", ""))

        # Realtime
        self._set_combo(self.combo_rt_type, store.get_value_by_path("realtime.type", "console"))
        self._set_ent(self.ent_rt_interval, str(store.get_value_by_path("realtime.read.interval_seconds", 60)))
        self._set_ent(self.ent_rt_window, str(store.get_value_by_path("realtime.read.window_seconds", 120)))
        self._set_ent(self.ent_rt_partition, str(store.get_value_by_path("realtime.read.tag_partition_size", 250)))
        self._set_ent(self.ent_rt_workers, str(store.get_value_by_path("realtime.read.max_workers", 8)))
        self._set_ent(self.ent_rt_batch, str(store.get_value_by_path("realtime.read.batch_size", 1000)))
        self._set_ent(self.ent_rt_retries, str(store.get_value_by_path("realtime.read.max_publish_retries", 3)))
        self._set_ent(self.ent_rt_retry_sleep, str(store.get_value_by_path("realtime.read.retry_sleep_seconds", 2)))

        self._set_ent(self.ent_rt_file_path, store.get_value_by_path("realtime.file.output_path", "output/events.json"))
        self._set_ent(self.ent_rt_kafka_servers, store.get_value_by_path("realtime.kafka.bootstrap_servers", "localhost:9092"))
        self._set_ent(self.ent_rt_kafka_topic, store.get_value_by_path("realtime.kafka.topic", "industrial-flow.pi-tags"))
        self._set_ent(self.ent_rt_bq_proj, store.get_value_by_path("realtime.bigquery.project_id", ""))
        self._set_ent(self.ent_rt_bq_dataset, store.get_value_by_path("realtime.bigquery.dataset", "industrial"))
        self._set_ent(self.ent_rt_bq_table, store.get_value_by_path("realtime.bigquery.table", "pi_data"))
        self._set_ent(self.ent_rt_bq_sa, store.get_value_by_path("realtime.bigquery.service_account_file", ""))

        # Historical
        self._set_combo(self.combo_hist_type, store.get_value_by_path("historical.type", "parquet"))
        self._set_ent(self.ent_hist_interval, str(store.get_value_by_path("historical.read.interval_seconds", 60)))
        self._set_ent(self.ent_hist_window, str(store.get_value_by_path("historical.read.window_seconds", 172800)))
        self._set_ent(self.ent_hist_partition, str(store.get_value_by_path("historical.read.tag_partition_size", 250)))
        self._set_ent(self.ent_hist_workers, str(store.get_value_by_path("historical.read.max_workers", 8)))
        self._set_ent(self.ent_hist_batch, str(store.get_value_by_path("historical.read.batch_size", 10000)))

        self._set_ent(self.ent_hist_parquet_dir, store.get_value_by_path("historical.parquet.output_dir", "output/parquet"))
        self._set_ent(self.ent_hist_gcs_bucket, store.get_value_by_path("historical.gcs.bucket", "raw-industrial"))
        self.var_hist_gcs_delete.set(bool(store.get_value_by_path("historical.gcs.delete_local_file_after_upload", True)))
        self._set_ent(self.ent_hist_gcs_sa, store.get_value_by_path("historical.gcs.service_account_file", ""))
        self._set_ent(self.ent_hist_bq_proj, store.get_value_by_path("historical.bigquery.project_id", ""))
        self._set_ent(self.ent_hist_bq_dataset, store.get_value_by_path("historical.bigquery.dataset", "industrial"))
        self._set_ent(self.ent_hist_bq_table, store.get_value_by_path("historical.bigquery.table", "pi_data"))
        self._set_ent(self.ent_hist_bq_sa, store.get_value_by_path("historical.bigquery.service_account_file", ""))

        # Populate sites
        self._populate_sites_list()

    def _populate_sites_list(self) -> None:
        self.list_sites.delete(0, tk.END)
        sites = self.store.get_sites()
        for idx, site in enumerate(sites):
            site_id = site.get("id", f"site-{idx}")
            enabled = " (enabled)" if site.get("enabled", True) else " (disabled)"
            self.list_sites.insert(tk.END, f"{site_id}{enabled}")

        if sites:
            idx = min(self.current_site_index, len(sites) - 1)
            self.list_sites.selection_clear(0, tk.END)
            self.list_sites.selection_set(idx)
            self.load_site_into_form(idx)

    def load_site_into_form(self, index: int) -> None:
        sites = self.store.get_sites()
        if not (0 <= index < len(sites)):
            return
        self.current_site_index = index
        site = sites[index]
        pi = site.get("pi", {})

        self._set_ent(self.ent_site_id, site.get("id", ""))
        self.var_site_enabled.set(bool(site.get("enabled", True)))
        self._set_combo(self.combo_site_pi_provider, pi.get("provider", "piapi"))
        self._set_ent(self.ent_site_pi_server, pi.get("server", ""))
        self._set_ent(self.ent_site_pi_tz, pi.get("pi_timezone", "America/Sao_Paulo"))
        self._set_ent(self.ent_site_pi_user, pi.get("username", ""))
        self._set_ent(self.ent_site_pi_pass, pi.get("password", ""))
        self._set_ent(self.ent_site_tags_file, site.get("tags_file", "config/tags.txt"))

    def collect_form_values(self) -> dict[str, Any]:
        data = copy.deepcopy(self.store.data)

        # Cache
        data["cache"] = {
            "point_cache_file": self.ent_cache_point.get().strip(),
            "digital_state_cache_file": self.ent_cache_digital.get().strip(),
        }

        # Writer
        data["writer"] = {
            "type": self.combo_writer_type.get().strip(),
            "pubsub": {
                "project_id": self.ent_writer_pubsub_proj.get().strip() or None,
                "subscription_id": self.ent_writer_pubsub_sub.get().strip() or None,
                "service_account_file": self.ent_writer_pubsub_sa.get().strip() or None,
            },
        }

        # Realtime
        data["realtime"] = {
            "type": self.combo_rt_type.get().strip(),
            "read": {
                "interval_seconds": self._get_int(self.ent_rt_interval, 60),
                "window_seconds": self._get_int(self.ent_rt_window, 120),
                "tag_partition_size": self._get_int(self.ent_rt_partition, 250),
                "max_workers": self._get_int(self.ent_rt_workers, 8),
                "batch_size": self._get_int(self.ent_rt_batch, 1000),
                "max_publish_retries": self._get_int(self.ent_rt_retries, 3),
                "retry_sleep_seconds": self._get_int(self.ent_rt_retry_sleep, 2),
            },
            "file": {"output_path": self.ent_rt_file_path.get().strip()},
            "kafka": {
                "bootstrap_servers": self.ent_rt_kafka_servers.get().strip(),
                "topic": self.ent_rt_kafka_topic.get().strip(),
            },
            "bigquery": {
                "project_id": self.ent_rt_bq_proj.get().strip() or None,
                "dataset": self.ent_rt_bq_dataset.get().strip(),
                "table": self.ent_rt_bq_table.get().strip(),
                "service_account_file": self.ent_rt_bq_sa.get().strip() or None,
            },
        }

        # Historical
        data["historical"] = {
            "type": self.combo_hist_type.get().strip(),
            "read": {
                "interval_seconds": self._get_int(self.ent_hist_interval, 60),
                "window_seconds": self._get_int(self.ent_hist_window, 172800),
                "tag_partition_size": self._get_int(self.ent_hist_partition, 250),
                "max_workers": self._get_int(self.ent_hist_workers, 8),
                "batch_size": self._get_int(self.ent_hist_batch, 10000),
            },
            "parquet": {"output_dir": self.ent_hist_parquet_dir.get().strip()},
            "gcs": {
                "bucket": self.ent_hist_gcs_bucket.get().strip() or None,
                "delete_local_file_after_upload": self.var_hist_gcs_delete.get(),
                "service_account_file": self.ent_hist_gcs_sa.get().strip() or None,
            },
            "bigquery": {
                "project_id": self.ent_hist_bq_proj.get().strip() or None,
                "dataset": self.ent_hist_bq_dataset.get().strip(),
                "table": self.ent_hist_bq_table.get().strip(),
                "service_account_file": self.ent_hist_bq_sa.get().strip() or None,
            },
        }

        # Current site update
        sites = data.get("sites", [])
        if sites and 0 <= self.current_site_index < len(sites):
            sites[self.current_site_index] = {
                "id": self.ent_site_id.get().strip(),
                "enabled": self.var_site_enabled.get(),
                "pi": {
                    "provider": self.combo_site_pi_provider.get().strip(),
                    "server": self.ent_site_pi_server.get().strip(),
                    "pi_timezone": self.ent_site_pi_tz.get().strip(),
                    "username": self.ent_site_pi_user.get().strip() or None,
                    "password": self.ent_site_pi_pass.get().strip() or None,
                },
                "tags_file": self.ent_site_tags_file.get().strip(),
            }

        return data

    def _set_ent(self, ent: ttk.Entry, val: str | None) -> None:
        ent.delete(0, tk.END)
        ent.insert(0, val or "")

    def _set_combo(self, combo: ttk.Combobox, val: str | None) -> None:
        if val:
            combo.set(val)

    def _get_int(self, ent: ttk.Entry, default: int = 0) -> int:
        val = ent.get().strip()
        try:
            return int(val)
        except ValueError:
            return default

    def _on_site_selected(self, event=None) -> None:
        selection = self.list_sites.curselection()
        if selection:
            idx = selection[0]
            # Save current editing fields back to site object before switching
            sites = self.store.get_sites()
            if 0 <= self.current_site_index < len(sites):
                sites[self.current_site_index] = {
                    "id": self.ent_site_id.get().strip(),
                    "enabled": self.var_site_enabled.get(),
                    "pi": {
                        "provider": self.combo_site_pi_provider.get().strip(),
                        "server": self.ent_site_pi_server.get().strip(),
                        "pi_timezone": self.ent_site_pi_tz.get().strip(),
                        "username": self.ent_site_pi_user.get().strip() or None,
                        "password": self.ent_site_pi_pass.get().strip() or None,
                    },
                    "tags_file": self.ent_site_tags_file.get().strip(),
                }

            self.load_site_into_form(idx)

    def add_site(self) -> None:
        new_site = copy.deepcopy(DEFAULT_SITE)
        new_site["id"] = f"site-{len(self.store.get_sites()) + 1}"
        new_site["enabled"] = False
        self.store.add_site(new_site)
        self.current_site_index = len(self.store.get_sites()) - 1
        self._populate_sites_list()
        self.lbl_status.config(text="Added new plant site (disabled by default).", foreground="#388e3c")

    def delete_site(self) -> None:
        sites = self.store.get_sites()
        if len(sites) > 1:
            self.store.delete_site(self.current_site_index)
            self.current_site_index = max(0, self.current_site_index - 1)
            self._populate_sites_list()
            self.lbl_status.config(text="Deleted site.", foreground="#f57c00")
        else:
            self.lbl_status.config(text="Cannot delete the only configured site.", foreground="#d32f2f")

    def validate_config(self) -> None:
        try:
            data = self.collect_form_values()
            self.store.validate_in_memory(data)
            self.lbl_status.config(text="Validation succeeded! Configuration schema is valid.", foreground="#2e7d32")
        except Exception as exc:
            self.lbl_status.config(text=f"Validation failed: {exc}", foreground="#d32f2f")

    def reload_config(self) -> None:
        try:
            self.store.load()
            self.populate_form()
            self.lbl_status.config(text="Configuration reloaded from disk.", foreground="#0288d1")
        except Exception as exc:
            self.lbl_status.config(text=f"Error reloading configuration: {exc}", foreground="#d32f2f")

    def save_config(self) -> None:
        try:
            data = self.collect_form_values()
            self.store.validate_in_memory(data)
            self.store.data = data
            self.store.save()
            self.lbl_status.config(text="Configuration saved successfully to config/config.yaml!", foreground="#2e7d32")
        except Exception as exc:
            self.lbl_status.config(text=f"Save rejected: Configuration is invalid! {exc}", foreground="#d32f2f")
