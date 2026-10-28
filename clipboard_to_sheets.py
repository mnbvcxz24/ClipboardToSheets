import datetime
import queue
import threading
import time
import tkinter as tk
import secret
from pathlib import Path
from tkinter import messagebox

import gspread
import pyperclip
from google.oauth2.service_account import Credentials
from plyer import notification

APP_NAME = "ClipboardToSheets"
BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_KEY = secret.SPREADSHEET_KEY
SPREADSHEET_NAME = ""
WORKSHEET_NAME = "RAW"
POLL_INTERVAL_SECONDS = 1

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
        self.root.geometry("390x270")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.logging_enabled = threading.Event()
        self.sheet = None
        self.watcher_started = False
        self.connected = False

        tk.Label(root, text=APP_NAME, bg=BG, fg=TEXT,
                 font=("Segoe UI", 17, "bold")).pack(pady=(18, 4))
        self.status_label = tk.Label(
            root, text="Connecting to Google Sheets...", bg=BG,
            fg=MUTED, font=("Segoe UI", 10)
        )
        self.status_label.pack(pady=(0, 12))

        self.state_label = tk.Label(
            root, text="LOGGING OFF", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 11, "bold"), width=22, pady=9
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

        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.root.after(150, self.process_events)
        self.connect_async()

    def notify(self, title, message):
        try:
            notification.notify(
                title=title,
                message=message,
                app_name=APP_NAME,
                timeout=4
            )
        except Exception:
            pass

    def connect_async(self):
        if not CREDENTIALS_FILE.exists():
            self.set_status("credentials.json not found", RED)
            self.activity_label.config(text="Place credentials.json beside the app.")
            self.notify(APP_NAME, "credentials.json was not found.")
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
            self.events.put(("connected", sheet))
        except Exception as exc:
            self.events.put(("connect_error", str(exc)))

    def set_status(self, message, color=MUTED):
        self.status_label.config(text=message, fg=color)

    def process_events(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "connected":
                    self.sheet = payload
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
                    self.notify(APP_NAME, "Connected to Google Sheets.")
                elif event == "connect_error":
                    self.connected = False
                    self.connect_button.config(state="normal", text="Reconnect")
                    self.toggle_button.config(state="disabled")
                    self.set_status("Connection failed", RED)
                    self.activity_label.config(text=payload[:160])
                    self.notify(APP_NAME, "Could not connect to Google Sheets. Check app status.")
                elif event == "logged":
                    self.activity_label.config(text=f"Logged copied text to {payload}")
                    self.notify(APP_NAME, f"Copied text logged to {payload}.")
                elif event == "log_error":
                    self.activity_label.config(text="Could not write to Google Sheets.")
                    self.notify(APP_NAME, "Could not write to Google Sheets. Check your connection.")
        except queue.Empty:
            pass
        if not self.stop_event.is_set():
            self.root.after(150, self.process_events)

    def toggle_logging(self):
        if not self.connected:
            self.notify(APP_NAME, "Connect to Google Sheets first.")
            return
        if self.logging_enabled.is_set():
            self.logging_enabled.clear()
            self.toggle_button.config(text="Turn ON", bg=GREEN, fg="#06210f")
            self.state_label.config(text="LOGGING OFF", fg=MUTED)
            self.set_status("Connected · logging paused", MUTED)
            self.notify(APP_NAME, "Clipboard logging is OFF.")
        else:
            self.logging_enabled.set()
            self.toggle_button.config(text="Turn OFF", bg=RED, fg="white")
            self.state_label.config(text="LOGGING ON", fg=GREEN)
            self.set_status("Connected · watching clipboard", GREEN)
            self.notify(APP_NAME, "Clipboard logging is ON.")

    def get_next_position(self):
        col_a = self.sheet.col_values(1)
        col_b = self.sheet.col_values(2)
        entry_number = len(col_a) + len(col_b) + 1
        row = (entry_number + 1) // 2
        col = 1 if entry_number % 2 == 1 else 2
        return row, col

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
                try:
                    row, col = self.get_next_position()
                    self.sheet.update_cell(row, col, current_value)
                    cell_ref = f"{'A' if col == 1 else 'B'}{row}"
                    self.events.put(("logged", cell_ref))
                except Exception:
                    self.events.put(("log_error", None))
            time.sleep(POLL_INTERVAL_SECONDS)

    def close_app(self):
        if messagebox.askyesno(APP_NAME, "Exit ClipboardToSheets?"):
            self.stop_event.set()
            self.root.destroy()


def main():
    root = tk.Tk()
    ClipboardToSheetsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
