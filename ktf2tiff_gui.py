"""Window front end for ktf2tiff: pick folders, convert every .ktf in them to TIFF."""

import queue
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import ktf2tiff

TITLE = "Keyence KTF to TIFF"


class App:
    def __init__(self, root, initial=()):
        self.root = root
        self.msgs = queue.Queue()
        self.worker = None
        root.title(TITLE)
        root.geometry("760x560")
        root.minsize(600, 440)

        pad = dict(padx=8, pady=4)

        top = ttk.LabelFrame(root, text="Folders with .ktf images")
        top.pack(fill="both", expand=False, **pad)
        self.listbox = tk.Listbox(top, height=6, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        btns = ttk.Frame(top)
        btns.pack(side="left", fill="y", padx=6, pady=6)
        ttk.Button(btns, text="Add folder...", command=self.add_folder).pack(fill="x")
        ttk.Button(btns, text="Add files...", command=self.add_files).pack(fill="x", pady=4)
        ttk.Button(btns, text="Remove selected", command=self.remove_selected).pack(fill="x")
        ttk.Button(btns, text="Clear", command=lambda: self.listbox.delete(0, "end")).pack(fill="x", pady=4)

        opts = ttk.LabelFrame(root, text="Options")
        opts.pack(fill="x", **pad)
        self.recursive = tk.BooleanVar(value=True)
        self.gray = tk.BooleanVar(value=False)
        self.overwrite = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Include subfolders", variable=self.recursive).grid(row=0, column=0, sticky="w", padx=6)
        ttk.Checkbutton(opts, text="Also save single-channel gray TIFF (for intensity measurements)",
                        variable=self.gray).grid(row=1, column=0, columnspan=3, sticky="w", padx=6)
        ttk.Checkbutton(opts, text="Overwrite existing TIFFs", variable=self.overwrite).grid(row=2, column=0, sticky="w", padx=6)

        self.out_mode = tk.StringVar(value="beside")
        self.out_dir = tk.StringVar(value="")
        ttk.Radiobutton(opts, text="Save next to each .ktf file", value="beside",
                        variable=self.out_mode).grid(row=3, column=0, sticky="w", padx=6, pady=(6, 0))
        ttk.Radiobutton(opts, text="Save all into:", value="folder",
                        variable=self.out_mode).grid(row=4, column=0, sticky="w", padx=6)
        ttk.Entry(opts, textvariable=self.out_dir, width=55).grid(row=4, column=1, sticky="we", padx=4)
        ttk.Button(opts, text="Browse...", command=self.pick_out_dir).grid(row=4, column=2, padx=6, pady=4)
        opts.columnconfigure(1, weight=1)

        run = ttk.Frame(root)
        run.pack(fill="x", **pad)
        self.run_btn = ttk.Button(run, text="Convert", command=self.start)
        self.run_btn.pack(side="left")
        self.progress = ttk.Progressbar(run, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        self.status = ttk.Label(run, text="")
        self.status.pack(side="left")

        logf = ttk.LabelFrame(root, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, height=10, wrap="none", state="disabled")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        for p in initial:
            self.add_entry(str(Path(p)))
        if not initial:
            root.after(300, self.add_folder)
        root.after(100, self.poll)

    # ---- input selection -------------------------------------------------
    def entries(self):
        return list(self.listbox.get(0, "end"))

    def add_entry(self, path):
        if path and path not in self.entries():
            self.listbox.insert("end", path)

    def add_folder(self):
        d = filedialog.askdirectory(parent=self.root, title="Select a folder containing .ktf images")
        if d:
            self.add_entry(str(Path(d)))

    def add_files(self):
        fs = filedialog.askopenfilenames(parent=self.root, title="Select .ktf files",
                                         filetypes=[("Keyence KTF", "*.ktf"), ("All files", "*.*")])
        for f in fs:
            self.add_entry(str(Path(f)))

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)

    def pick_out_dir(self):
        d = filedialog.askdirectory(parent=self.root, title="Select output folder")
        if d:
            self.out_dir.set(str(Path(d)))
            self.out_mode.set("folder")

    # ---- running ---------------------------------------------------------
    def collect_files(self):
        files = []
        for e in self.entries():
            p = Path(e)
            if p.is_dir():
                found = p.rglob("*.ktf") if self.recursive.get() else p.glob("*.ktf")
                files += sorted(found)
            elif p.suffix.lower() == ".ktf" and p.exists():
                files.append(p)
        seen, unique = set(), []
        for f in files:
            if f.resolve() not in seen:
                seen.add(f.resolve())
                unique.append(f)
        return unique

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        if not self.entries():
            messagebox.showinfo(TITLE, "Add at least one folder first.", parent=self.root)
            return
        out = None
        if self.out_mode.get() == "folder":
            if not self.out_dir.get().strip():
                messagebox.showinfo(TITLE, "Choose an output folder, or pick 'Save next to each .ktf file'.",
                                    parent=self.root)
                return
            out = Path(self.out_dir.get().strip())
        files = self.collect_files()
        if not files:
            messagebox.showinfo(TITLE, "No .ktf files found in the selected folders.", parent=self.root)
            return
        self.run_btn.configure(state="disabled")
        self.progress.configure(maximum=len(files), value=0)
        self.write_log("Found %d .ktf file(s)." % len(files))
        args = (files, out, self.gray.get(), self.overwrite.get())
        self.worker = threading.Thread(target=self.run, args=args, daemon=True)
        self.worker.start()

    def run(self, files, out, gray, overwrite):
        failed = 0
        log = lambda m: self.msgs.put(("log", m))
        for i, f in enumerate(files, 1):
            self.msgs.put(("status", "%d / %d: %s" % (i, len(files), f.name)))
            try:
                ktf2tiff.convert(f, out or f.parent, gray, overwrite, log=log)
            except Exception as e:  # keep going with the next file
                failed += 1
                log("FAILED %s: %s" % (f, e))
                log(traceback.format_exc().strip().splitlines()[-1])
            self.msgs.put(("progress", i))
        self.msgs.put(("done", (len(files), failed)))

    def poll(self):
        try:
            while True:
                kind, val = self.msgs.get_nowait()
                if kind == "log":
                    self.write_log(val)
                elif kind == "status":
                    self.status.configure(text=val)
                elif kind == "progress":
                    self.progress.configure(value=val)
                elif kind == "done":
                    n, failed = val
                    self.run_btn.configure(state="normal")
                    self.status.configure(text="Done")
                    msg = "Finished %d file(s), %d failed." % (n, failed)
                    self.write_log(msg)
                    (messagebox.showwarning if failed else messagebox.showinfo)(TITLE, msg, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(TITLE, "A conversion is running. Quit anyway?", parent=self.root):
                return
        self.root.destroy()


def main():
    args = sys.argv[1:]
    if args and args[0] == "--cli":
        # Command-line mode, same options as ktf2tiff.py. No window.
        sys.exit(ktf2tiff.main(args[1:]))
    root = tk.Tk()
    App(root, initial=args)  # paths dropped onto the exe pre-fill the list
    root.mainloop()


if __name__ == "__main__":
    main()
