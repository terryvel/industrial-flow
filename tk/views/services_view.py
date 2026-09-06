from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Any

from tk.models import ProcessStatus
from tk.process_manager import ManagedProcess, ProcessManager, ServiceSpec
from tk.services_cache import SavedService, ServicesCacheStore
from tk.views.service_detail import ServiceDetailWindow
from tk.views.service_form import ServiceFormModal


def format_local_time(dt: Any) -> str:
    if not dt:
        return "-"
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%H:%M:%S")


class ServicesView(ttk.Frame):
    """View component displaying persistent saved services table and process control actions."""

    def __init__(
        self,
        parent: tk.Widget,
        manager: ProcessManager,
        run_coro_fn: Callable[[Any, Callable[[Any], None] | None], None],
        **kwargs,
    ) -> None:
        super().__init__(parent, padding=12, **kwargs)
        self.manager = manager
        self.run_coro = run_coro_fn
        self.cache_store = ServicesCacheStore()

        # Load saved services from JSON cache
        self.saved_services: dict[str, SavedService] = {}
        self._load_saved_services()

        self._build_ui()

        # Listen to process status updates from process manager
        self.manager.add_status_listener(self._on_status_change_bg)

        # Initial refresh and start runtime clock timer
        self.refresh_table()
        self._tick_runtimes()

    def _load_saved_services(self) -> None:
        loaded = self.cache_store.load()
        self.saved_services = {srv.id: srv for srv in loaded}

    def _save_services_to_cache(self) -> None:
        self.cache_store.save(list(self.saved_services.values()))

    def _get_next_id(self) -> str:
        existing_ids = []
        for srv_id in self.saved_services.keys():
            try:
                existing_ids.append(int(srv_id))
            except ValueError:
                pass
        next_num = (max(existing_ids) + 1) if existing_ids else 1
        return f"{next_num:02d}"

    def _build_ui(self) -> None:
        # Title
        title_lbl = ttk.Label(self, text="Services Manager", font=("Segoe UI", 12, "bold"))
        title_lbl.pack(anchor=tk.W, pady=(0, 10))

        # Button Bar
        btn_bar = ttk.Frame(self)
        btn_bar.pack(fill=tk.X, pady=(0, 10))

        btn_new = ttk.Button(btn_bar, text="New Service (n)", command=self.open_new_service_modal)
        btn_new.pack(side=tk.LEFT, padx=(0, 5))

        btn_start = ttk.Button(btn_bar, text="Start Service", command=self.start_selected_service)
        btn_start.pack(side=tk.LEFT, padx=(0, 5))

        btn_stop = ttk.Button(btn_bar, text="Stop Service (s)", command=self.stop_selected_service)
        btn_stop.pack(side=tk.LEFT, padx=(0, 5))

        btn_restart = ttk.Button(btn_bar, text="Restart (r)", command=self.restart_selected_service)
        btn_restart.pack(side=tk.LEFT, padx=(0, 5))

        btn_log = ttk.Button(btn_bar, text="View Log (l)", command=self.open_selected_log)
        btn_log.pack(side=tk.LEFT, padx=(0, 5))

        btn_edit = ttk.Button(btn_bar, text="Edit Service (e)", command=self.edit_selected_service)
        btn_edit.pack(side=tk.LEFT, padx=(0, 5))

        btn_delete = ttk.Button(btn_bar, text="Delete Service", command=self.delete_selected_service)
        btn_delete.pack(side=tk.LEFT, padx=(0, 5))

        # Treeview (Process Table)
        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("id", "service", "target", "status", "started", "runtime")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.tree.heading("id", text="ID")
        self.tree.heading("service", text="Service")
        self.tree.heading("target", text="Target")
        self.tree.heading("status", text="Status")
        self.tree.heading("started", text="Started")
        self.tree.heading("runtime", text="Runtime")

        self.tree.column("id", width=60, anchor=tk.CENTER)
        self.tree.column("service", width=120, anchor=tk.W)
        self.tree.column("target", width=180, anchor=tk.W)
        self.tree.column("status", width=110, anchor=tk.CENTER)
        self.tree.column("started", width=100, anchor=tk.CENTER)
        self.tree.column("runtime", width=100, anchor=tk.CENTER)

        # Status Tag styles
        self.tree.tag_configure("RUNNING", foreground="#2e7d32", font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("COMPLETED", foreground="#388e3c")
        self.tree.tag_configure("FAILED", foreground="#d32f2f", font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("STOPPED", foreground="#f57c00")
        self.tree.tag_configure("STARTING", foreground="#0288d1")
        self.tree.tag_configure("STOPPING", foreground="#0288d1")

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda e: self.open_selected_log())

    def refresh_table(self) -> None:
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Gather all IDs (both saved and running processes)
        all_ids = set(self.saved_services.keys()) | set(self.manager.processes.keys())
        sorted_ids = sorted(all_ids, key=lambda x: int(x) if x.isdigit() else x)

        for srv_id in sorted_ids:
            proc = self.manager.get_process(srv_id)
            saved = self.saved_services.get(srv_id)

            if proc:
                service_name = proc.spec.service_type.value
                target = proc.spec.target_summary()
                status = proc.status.value
                started = format_local_time(proc.started_at)
                runtime = proc.formatted_runtime()
            elif saved:
                service_name = saved.spec.service_type.value
                target = saved.spec.target_summary()
                status = ProcessStatus.STOPPED.value
                started = "-"
                runtime = "00:00"
            else:
                continue

            self.tree.insert(
                "",
                tk.END,
                iid=srv_id,
                values=(
                    srv_id,
                    service_name,
                    target,
                    status,
                    started,
                    runtime,
                ),
                tags=(status,),
            )

    def _tick_runtimes(self) -> None:
        if not self.winfo_exists():
            return

        for proc in self.manager.list_processes():
            if proc.status in (ProcessStatus.STARTING, ProcessStatus.RUNNING, ProcessStatus.STOPPING):
                if self.tree.exists(proc.id):
                    self.tree.set(proc.id, "runtime", proc.formatted_runtime())

        self.after(1000, self._tick_runtimes)

    def _on_status_change_bg(self, proc: ManagedProcess) -> None:
        if self.winfo_exists():
            self.after(0, lambda: self._update_process_status(proc))

    def _update_process_status(self, proc: ManagedProcess) -> None:
        if self.tree.exists(proc.id):
            self.tree.set(proc.id, "status", proc.status.value)
            self.tree.set(proc.id, "runtime", proc.formatted_runtime())
            self.tree.item(proc.id, tags=(proc.status.value,))
        else:
            self.refresh_table()

    def get_selected_process_id(self) -> str | None:
        selected = self.tree.selection()
        if selected:
            return selected[0]
        return None

    def open_new_service_modal(self) -> None:
        def _on_start_spec(spec: ServiceSpec) -> None:
            new_id = self._get_next_id()
            saved = SavedService(id_str=new_id, spec=spec)
            self.saved_services[new_id] = saved
            self._save_services_to_cache()

            # Start service process
            proc = ManagedProcess(
                id_str=new_id,
                spec=spec,
                log_callback=self.manager._on_log,
                status_callback=self.manager._on_status,
                max_log_lines=self.manager.max_log_lines,
            )
            self.manager.processes[new_id] = proc
            coro = proc.start()
            self.run_coro(coro, lambda res: self.refresh_table())

        ServiceFormModal(self.winfo_toplevel(), on_submit=_on_start_spec)

    def edit_selected_service(self) -> None:
        srv_id = self.get_selected_process_id()
        if not srv_id:
            return

        proc = self.manager.get_process(srv_id)
        if proc and proc.status in (ProcessStatus.STARTING, ProcessStatus.RUNNING, ProcessStatus.STOPPING):
            messagebox.showwarning(
                "Service Running",
                f"Service ID {srv_id} is currently active ({proc.status.value}).\n\nThe service must be stopped before it can be edited."
            )
            return

        saved = self.saved_services.get(srv_id)
        spec = proc.spec if proc else (saved.spec if saved else None)
        if not spec:
            return

        def _on_save_spec(new_spec: ServiceSpec) -> None:
            if saved:
                saved.spec = new_spec
            else:
                self.saved_services[srv_id] = SavedService(id_str=srv_id, spec=new_spec)

            if proc:
                proc.spec = new_spec

            self._save_services_to_cache()
            self.refresh_table()

        ServiceFormModal(
            self.winfo_toplevel(),
            on_submit=_on_save_spec,
            initial_spec=spec,
            title_text=f"Edit Service — ID {srv_id}",
        )

    def start_selected_service(self) -> None:
        srv_id = self.get_selected_process_id()
        if not srv_id:
            return

        saved = self.saved_services.get(srv_id)
        proc = self.manager.get_process(srv_id)

        # If process is currently running, do nothing
        if proc and proc.status in (ProcessStatus.STARTING, ProcessStatus.RUNNING):
            return

        spec = proc.spec if proc else (saved.spec if saved else None)
        if not spec:
            return

        new_proc = ManagedProcess(
            id_str=srv_id,
            spec=spec,
            log_callback=self.manager._on_log,
            status_callback=self.manager._on_status,
            max_log_lines=self.manager.max_log_lines,
        )
        self.manager.processes[srv_id] = new_proc
        coro = new_proc.start()
        self.run_coro(coro, lambda res: self.refresh_table())

    def open_selected_log(self) -> None:
        proc_id = self.get_selected_process_id()
        if proc_id and self.manager.get_process(proc_id):
            def _stop_cb(pid: str) -> None:
                coro = self.manager.stop_service(pid)
                self.run_coro(coro, lambda res: self.refresh_table())

            ServiceDetailWindow(
                parent=self.winfo_toplevel(),
                process_id=proc_id,
                manager=self.manager,
                stop_service_cb=_stop_cb,
            )
        elif proc_id:
            messagebox.showinfo("Service Stopped", f"Service ID {proc_id} is currently stopped. Start it to view live logs.")

    def stop_selected_service(self) -> None:
        proc_id = self.get_selected_process_id()
        if proc_id:
            coro = self.manager.stop_service(proc_id)
            self.run_coro(coro, lambda res: self.refresh_table())

    def restart_selected_service(self) -> None:
        proc_id = self.get_selected_process_id()
        if proc_id:
            saved = self.saved_services.get(proc_id)
            proc = self.manager.get_process(proc_id)
            spec = proc.spec if proc else (saved.spec if saved else None)

            async def _do_restart():
                if proc:
                    await proc.stop(force=True)
                if spec:
                    new_proc = ManagedProcess(
                        id_str=proc_id,
                        spec=spec,
                        log_callback=self.manager._on_log,
                        status_callback=self.manager._on_status,
                        max_log_lines=self.manager.max_log_lines,
                    )
                    self.manager.processes[proc_id] = new_proc
                    await new_proc.start()

            self.run_coro(_do_restart(), lambda res: self.refresh_table())

    def delete_selected_service(self) -> None:
        proc_id = self.get_selected_process_id()
        if not proc_id:
            return

        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete saved service ID {proc_id}?"):
            return

        async def _do_delete():
            if self.manager.get_process(proc_id):
                await self.manager.stop_service(proc_id, force=True)
                self.manager.processes.pop(proc_id, None)

        def _on_stopped(res):
            self.saved_services.pop(proc_id, None)
            self._save_services_to_cache()
            self.refresh_table()

        self.run_coro(_do_delete(), callback=_on_stopped)
