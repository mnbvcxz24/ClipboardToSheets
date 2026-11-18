import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import gspread
import pyperclip
import pystray
from google.oauth2.service_account import Credentials
from PIL import Image, ImageDraw

APP_NAME = "ClipboardToSheets"
BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"

try:
    import secret
except ImportError:
    secret = None

SPREADSHEET_KEY = getattr(secret, "SPREADSHEET_KEY", "")
SPREADSHEET_NAME = getattr(secret, "SPREADSHEET_NAME", "Clipboard Log")
WORKSHEET_NAME = "RAW"

# Fast local polling; Google Sheets writes happen on a separate worker.
POLL_INTERVAL_SECONDS = 0.15
WRITE_BATCH_WINDOW_SECONDS = 0.12
MAX_BATCH_SIZE = 50

BG = "#111827"
PANEL = "#1f2937"
TEXT = "#f9fafb"
MUTED = "#9ca3af"
GREEN = "#22c55e"
RED = "#ef4444"
BLUE = "#3b82f6"


class ClipboardToSheetsApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("390x250")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        self.events = queue.Queue()
        self.write_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.logging_enabled = threading.Event()
        self.sheet = None
        self.next_entry_number = 1
        self.watcher_started = False
        self.writer_started = False
        self.connected = False
        self.tray_icon = None
        self.exiting = False

        tk.Label(
            root, text=APP_NAME, bg=BG, fg=TEXT,
            font=("Segoe UI", 17, "bold")
        ).pack(pady=(18, 4))

        self.status_label = tk.Label(
            root, text="Connecting to Google Sheets...", bg=BG,
            fg=MUTED, font=("Segoe UI", 10)
        )
        self.status_label.pack(pady=(0, 12))

        self.state_label = tk.Label(
            root, text="●  LOGGING OFF", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 11, "bold"), width=25, pady=9
        )
        self.state_label.pack(pady=4)

        buttons = tk.Frame(root, bg=BG)
        buttons.pack(pady=12)

        self.toggle_button = tk.Button(
            buttons, text="Turn ON", command=self.toggle_logging,
            bg=GREEN, fg="#06210f", activebackground=GREEN,
            relief="flat", width=12, pady=7, font=("Segoe UI", 10, "bold"),
            state="disabled", cursor="hand2"
        )
        self.toggle_button.pack(side="left", padx=5)

        self.connect_button = tk.Button(
            buttons, text="Reconnect", command=self.connect_async,
            bg=BLUE, fg="white", activebackground=BLUE,
            relief="flat", width=12, pady=7, font=("Segoe UI", 10),
            cursor="hand2"
        )
        self.connect_button.pack(side="left", padx=5)

        self.activity_label = tk.Label(
            root, text="Ready when connected", bg=BG, fg=MUTED,
            font=("Segoe UI", 9), wraplength=350
        )
        self.activity_label.pack(pady=(1, 0))

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.after(150, self.process_events)
        self.start_tray_icon()
        self.connect_async()

    @staticmethod
    def make_tray_image(is_on):
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        color = (34, 197, 94, 255) if is_on else (156, 163, 175, 255)
        draw.ellipse((8, 8, 56, 56), fill=color)
        draw.ellipse((17, 17, 47, 47), fill=(255, 255, 255, 45))
        return image

    def start_tray_icon(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open ClipboardToSheets", self.tray_show),
            pystray.MenuItem(
                lambda item: "Turn OFF logging" if self.logging_enabled.is_set()
                else "Turn ON logging",
                self.tray_toggle,
                enabled=lambda item: self.connected
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.tray_exit)
        )
        self.tray_icon = pystray.Icon(
            APP_NAME, self.make_tray_image(False), APP_NAME, menu
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def refresh_tray_icon(self):
        if self.tray_icon is not None:
            is_on = self.logging_enabled.is_set()
            self.tray_icon.icon = self.make_tray_image(is_on)
            self.tray_icon.title = (
                f"{APP_NAME} - Logging ON" if is_on
                else f"{APP_NAME} - Logging OFF"
            )
            self.tray_icon.update_menu()

    def tray_show(self, icon=None, item=None):
        self.root.after(0, self.show_window)

    def tray_toggle(self, icon=None, item=None):
        self.root.after(0, self.toggle_logging)

    def tray_exit(self, icon=None, item=None):
        self.root.after(0, self.exit_app)

    def show_window(self):
        if self.exiting:
            return
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        if not self.exiting:
            self.root.withdraw()

    def connect_async(self):
        if not CREDENTIALS_FILE.is_file():
            self.set_status("credentials.json not found", RED)
            self.activity_label.config(text="Place credentials.json beside the app.")
            return

        self.connect_button.config(state="disabled", text="Connecting...")
        self.status_label.config(text="Connecting to Google Sheets...", fg=MUTED)
        threading.Thread(target=self.connect_worker, daemon=True).start()

    def connect_worker(self):
        try:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(
                str(CREDENTIALS_FILE), scopes=scopes
            )
            client = gspread.authorize(creds)
            if SPREADSHEET_KEY.strip():
                spreadsheet = client.open_by_key(SPREADSHEET_KEY.strip())
            else:
                spreadsheet = client.open(SPREADSHEET_NAME)
            sheet = spreadsheet.worksheet(WORKSHEET_NAME)

            # One read on connection to determine the next zigzag cell.
            values = sheet.get_all_values()
            col_a_count = sum(1 for row in values if len(row) > 0 and row[0].strip())
            col_b_count = sum(1 for row in values if len(row) > 1 and row[1].strip())
            next_entry_number = col_a_count + col_b_count + 1
            self.events.put(("connected", (sheet, next_entry_number)))
        except Exception as exc:
            self.events.put(("connect_error", str(exc)))

    def set_status(self, message, color=MUTED):
        self.status_label.config(text=message, fg=color)

    def process_events(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "connected":
                    self.sheet, self.next_entry_number = payload
                    self.connected = True
                    self.connect_button.config(state="normal", text="Reconnect")
                    self.toggle_button.config(state="normal")
                    self.set_status("Connected to Google Sheets", GREEN)
                    self.activity_label.config(text=f"Target: {WORKSHEET_NAME}")
                    if not self.watcher_started:
                        self.watcher_started = True
                        threading.Thread(
                            target=self.clipboard_watch_loop, daemon=True
                        ).start()
                    if not self.writer_started:
                        self.writer_started = True
                        threading.Thread(
                            target=self.sheet_writer_loop, daemon=True
                        ).start()
                    self.refresh_tray_icon()
                elif event == "connect_error":
                    self.connected = False
                    self.logging_enabled.clear()
                    self.state_label.config(text="●  LOGGING OFF", fg=MUTED)
                    self.toggle_button.config(text="Turn ON", bg=GREEN, fg="#06210f")
                    self.connect_button.config(state="normal", text="Reconnect")
                    self.toggle_button.config(state="disabled")
                    self.set_status("Connection failed", RED)
                    self.activity_label.config(text=payload[:160])
                    self.refresh_tray_icon()
                elif event == "rescanned":
                    self.next_entry_number = payload
                    self.logging_enabled.set()
                    self.toggle_button.config(
                        state="normal", text="Turn OFF", bg=RED, fg="white"
                    )
                    self.state_label.config(text="●  LOGGING ON", fg=GREEN)
                    self.set_status("Sheet rescanned · watching clipboard", GREEN)
                    self.activity_label.config(
                        text=f"Next target: {'A' if payload % 2 == 1 else 'B'}{(payload + 1) // 2}"
                    )
                    self.refresh_tray_icon()
                elif event == "rescan_error":
                    self.toggle_button.config(
                        state="normal", text="Turn ON", bg=GREEN, fg="#06210f"
                    )
                    self.set_status("Rescan failed · logging remains OFF", RED)
                    self.activity_label.config(text=str(payload)[:160])
                elif event == "logged":
                    count, last_cell = payload
                    self.activity_label.config(
                        text=f"Logged {count} item(s) · latest: {last_cell}"
                    )
                elif event == "log_error":
                    self.activity_label.config(
                        text="Could not write to Google Sheets. Will keep monitoring."
                    )
        except queue.Empty:
            pass
        if not self.stop_event.is_set():
            self.root.after(150, self.process_events)

    def toggle_logging(self):
        if not self.connected:
            self.activity_label.config(text="Connect to Google Sheets first.")
            return
        if self.logging_enabled.is_set():
            self.logging_enabled.clear()
            self.toggle_button.config(text="Turn ON", bg=GREEN, fg="#06210f")
            self.state_label.config(text="●  LOGGING OFF", fg=MUTED)
            self.set_status("Connected · logging paused", MUTED)
        else:
            # Keep monitoring paused until pending writes finish and the sheet
            # has been rescanned, so the next cell is based on current contents.
            self.toggle_button.config(state="disabled", text="Rescanning...")
            self.set_status("Rescanning Google Sheets...", MUTED)
            self.activity_label.config(text="Finishing pending writes first...")
            threading.Thread(target=self.refresh_position_worker, daemon=True).start()
        self.refresh_tray_icon()

    def refresh_position_worker(self):
        try:
            # Wait for queued writes to finish before reading the sheet.
            self.write_queue.join()
            values = self.sheet.get_all_values()
            col_a_count = sum(
                1 for row in values if len(row) > 0 and row[0].strip()
            )
            col_b_count = sum(
                1 for row in values if len(row) > 1 and row[1].strip()
            )
            self.events.put(("rescanned", col_a_count + col_b_count + 1))
        except Exception as exc:
            self.events.put(("rescan_error", str(exc)))

    def clipboard_watch_loop(self):
        try:
            last_value = pyperclip.paste()
        except Exception:
            last_value = ""

        while not self.stop_event.is_set():
            if not self.logging_enabled.is_set():
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            try:
                current_value = pyperclip.paste()
            except Exception:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            if current_value != last_value and current_value.strip():
                last_value = current_value
                # Never wait for a Sheets network request in the clipboard watcher.
                if self.logging_enabled.is_set():
                    self.write_queue.put(current_value)

            time.sleep(POLL_INTERVAL_SECONDS)

    def sheet_writer_loop(self):
        while not self.stop_event.is_set():
            try:
                first_value = self.write_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            batch_values = [first_value]
            deadline = time.monotonic() + WRITE_BATCH_WINDOW_SECONDS
            while len(batch_values) < MAX_BATCH_SIZE:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    batch_values.append(self.write_queue.get(timeout=remaining))
                except queue.Empty:
                    break

            updates = []
            last_cell = ""
            for value in batch_values:
                entry = self.next_entry_number
                row = (entry + 1) // 2
                col = 1 if entry % 2 == 1 else 2
                last_cell = f"{'A' if col == 1 else 'B'}{row}"
                updates.append({"range": last_cell, "values": [[value]]})
                self.next_entry_number += 1

            # A single Sheets API request can write multiple copied values.
            try:
                self.sheet.batch_update(updates, value_input_option="RAW")
                self.events.put(("logged", (len(batch_values), last_cell)))
            except Exception:
                # Retry the same fixed cell ranges once; this is safe if the first
                # request reached Sheets but its response was interrupted.
                try:
                    time.sleep(0.25)
                    self.sheet.batch_update(updates, value_input_option="RAW")
                    self.events.put(("logged", (len(batch_values), last_cell)))
                except Exception:
                    self.events.put(("log_error", None))
                finally:
                    for _ in batch_values:
                        self.write_queue.task_done()

    def exit_app(self):
        if self.exiting:
            return
        if not messagebox.askyesno(APP_NAME, "Exit ClipboardToSheets?"):
            return
        self.exiting = True
        self.stop_event.set()
        if self.tray_icon is not None:
            self.tray_icon.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    ClipboardToSheetsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
