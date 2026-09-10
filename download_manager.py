"""
Optionaler Download-Hook über spotdl.
"""
import os
import queue
import re
import shutil
import subprocess
import threading

import applog
import config as cfg

# Unter Windows verhindert CREATE_NO_WINDOW, dass für jeden Aufruf kurz ein
# Konsolenfenster aufblitzt (im PyInstaller-Windowed-Build sichtbar). Das stiehlt
# sonst den Fokus und wird von NVDA mitgelesen.
NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def get_item_url(item: dict) -> str:
    """Liefert eine Spotify-URL für ein API-Objekt."""
    external_urls = item.get("external_urls") or {}
    if external_urls.get("spotify"):
        return external_urls["spotify"]

    uri = item.get("uri", "")
    if uri.startswith("spotify:"):
        parts = uri.split(":")
        if len(parts) >= 3:
            return f"https://open.spotify.com/{parts[1]}/{parts[2]}"
    return ""


def _spotdl_output_template(output_dir: str) -> str:
    """Übersetzt SpotiFlix-Platzhalter in das spotdl-Ausgabeformat."""
    template = cfg.get_download_template()
    replacements = {
        "%artist%": "{artist}",
        "%artists%": "{artists}",
        "%album%": "{album}",
        "%title%": "{title}",
        "%num%": "{track-number}",
        "%num,2%": "{track-number}",
        "%disc%": "{disc-number}",
        "%year%": "{year}",
    }
    for source, target in replacements.items():
        template = template.replace(source, target)

    template = template.replace("\\", "/").strip("/")
    template = re.sub(r"/+", "/", template)
    if not template:
        template = cfg.DEFAULT_DOWNLOAD_TEMPLATE
        for source, target in replacements.items():
            template = template.replace(source, target)
    return os.path.join(output_dir, template)


class DownloadCancelled(Exception):
    """Wird ausgelöst, wenn der Nutzer einen laufenden Download abbricht."""


# Zustände eines Auftrags in der Warteschlange.
STATUS_WAITING = "wartet"
STATUS_RUNNING = "läuft"
STATUS_DONE = "fertig"
STATUS_FAILED = "fehlgeschlagen"
STATUS_CANCELLED = "abgebrochen"
#: Zustände, aus denen heraus ein erneuter Versuch sinnvoll ist.
RETRYABLE = (STATUS_FAILED, STATUS_CANCELLED)


class DownloadJob:
    """Ein Auftrag in der Download-Warteschlange."""

    def __init__(self, job_id: int, item: dict, name: str):
        self.id = job_id
        self.item = item
        self.name = name
        self.status = STATUS_WAITING
        self.done = 0
        self.total = 0
        self.error: Exception | None = None
        self.cancel_event = threading.Event()

    @property
    def finished(self) -> bool:
        return self.status in (STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED)

    def label(self) -> str:
        """Kurzbeschreibung für Statusleiste und Dialog."""
        if self.status == STATUS_RUNNING and self.total:
            return f"{self.name} ({self.done}/{self.total})"
        if self.status == STATUS_RUNNING:
            return f"{self.name} (läuft …)"
        if self.status == STATUS_FAILED:
            return f"{self.name} (fehlgeschlagen: {applog.short_error(self.error, 60, hint=False)})"
        return f"{self.name} ({self.status})"


class DownloadQueue:
    """Arbeitet Downloads mit begrenzter Parallelität ab.

    Ohne Warteschlange startet jeder Menübefehl sofort einen eigenen Thread –
    fünf Alben bedeuten dann fünf gleichzeitige Streams. Hier laufen nur so
    viele Aufträge gleichzeitig, wie in den Einstellungen erlaubt sind; der
    Rest wartet. Fehlgeschlagene Aufträge bleiben in der Liste und lassen sich
    erneut anstoßen.
    """

    def __init__(self):
        self._jobs: dict[int, DownloadJob] = {}
        self._order: list[int] = []
        self._seq = 0
        self._pending: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._workers: list[threading.Thread] = []
        self._listener = None

    def set_listener(self, callback):
        """Setzt den Rückruf, der bei jeder Zustandsänderung feuert."""
        self._listener = callback

    def _notify(self, job: DownloadJob):
        if self._listener:
            try:
                self._listener(job)
            except Exception:
                pass

    def submit(self, item: dict, name: str | None = None) -> DownloadJob:
        """Reiht ein Element zum Herunterladen ein."""
        with self._lock:
            # Fortlaufend und nie rückwärts: Nach clear_finished() dürfen alte
            # IDs nicht erneut vergeben werden, sonst überschreibt ein neuer
            # Auftrag einen noch laufenden.
            self._seq += 1
            job_id = self._seq
            job = DownloadJob(job_id, item, name or item.get("name") or "Auswahl")
            self._jobs[job_id] = job
            self._order.append(job_id)
        self._pending.put(job_id)
        self._ensure_workers()
        self._notify(job)
        return job

    def _ensure_workers(self):
        """Startet bei Bedarf weitere Arbeiter (bis zum eingestellten Maximum)."""
        wanted = cfg.get_download_parallel()
        with self._lock:
            alive = [worker for worker in self._workers if worker.is_alive()]
            self._workers = alive
            missing = wanted - len(alive)
            for _ in range(max(0, missing)):
                worker = threading.Thread(target=self._worker_loop, daemon=True)
                self._workers.append(worker)
                worker.start()

    def _worker_loop(self):
        while True:
            job_id = self._pending.get()
            job = self._jobs.get(job_id)
            if job is None or job.cancel_event.is_set():
                if job is not None:
                    job.status = STATUS_CANCELLED
                    self._notify(job)
                continue
            self._run_job(job)

    def _run_job(self, job: DownloadJob):
        job.status = STATUS_RUNNING
        job.error = None
        self._notify(job)

        def progress(done: int, total: int):
            job.done, job.total = done, total
            self._notify(job)

        try:
            download_item(
                job.item,
                cfg.get_download_dir(),
                progress_callback=progress,
                cancel_event=job.cancel_event,
            )
            job.status = STATUS_DONE
            applog.info("Download", f"{job.name} abgeschlossen")
        except DownloadCancelled as e:
            job.status = STATUS_CANCELLED
            job.error = e
            applog.info("Download", f"{job.name} abgebrochen: {e}")
        except Exception as e:
            job.status = STATUS_FAILED
            job.error = e
            applog.error("Download", f"{job.name}: {e}")
        self._notify(job)

    # -- Abfragen und Steuern ------------------------------------------------

    def jobs(self) -> list[DownloadJob]:
        """Alle Aufträge in Einreihungsreihenfolge."""
        with self._lock:
            return [self._jobs[job_id] for job_id in self._order if job_id in self._jobs]

    def active_jobs(self) -> list[DownloadJob]:
        """Aufträge, die laufen oder noch warten."""
        return [job for job in self.jobs() if not job.finished]

    def cancel(self, job_id: int) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.finished:
            return False
        job.cancel_event.set()
        if job.status == STATUS_WAITING:
            # Wartende Aufträge sofort als abgebrochen melden.
            job.status = STATUS_CANCELLED
            self._notify(job)
        return True

    def cancel_all(self) -> int:
        return sum(1 for job in self.active_jobs() if self.cancel(job.id))

    def retry_failed(self) -> int:
        """Reiht fehlgeschlagene und abgebrochene Aufträge erneut ein."""
        retried = 0
        for job in self.jobs():
            if job.status not in RETRYABLE:
                continue
            job.cancel_event = threading.Event()
            job.status = STATUS_WAITING
            job.done = job.total = 0
            job.error = None
            self._pending.put(job.id)
            retried += 1
            self._notify(job)
        if retried:
            self._ensure_workers()
        return retried

    def clear_finished(self) -> int:
        """Entfernt abgeschlossene Aufträge aus der Liste."""
        with self._lock:
            finished = [job_id for job_id in self._order if self._jobs[job_id].finished]
            for job_id in finished:
                del self._jobs[job_id]
            self._order = [job_id for job_id in self._order if job_id in self._jobs]
        return len(finished)


#: Modul-weite Warteschlange – alle Downloads laufen hierüber.
downloads = DownloadQueue()


def download_item(item: dict, output_dir: str | None = None, progress_callback=None, cancel_event=None) -> str:
    """Lädt ein Spotify-Objekt mit der konfigurierten Methode herunter.

    ``progress_callback`` wird – soweit ermittelbar – mit (verarbeitet, gesamt)
    aufgerufen, damit die UI den Fortschritt ohne Blockieren anzeigen kann.
    ``cancel_event`` ist ein ``threading.Event``: Ist es gesetzt, bricht der
    Download an der nächsten Zwischenstation mit ``DownloadCancelled`` ab.
    """
    if cfg.get_download_method() == "librespot":
        from librespot_download import download_via_librespot
        return download_via_librespot(item, output_dir, progress_callback, cancel_event)
    return download_via_spotdl(item, output_dir, progress_callback, cancel_event)


def download_via_spotdl(item: dict, output_dir: str | None = None, progress_callback=None, cancel_event=None) -> str:
    """Startet spotdl für ein Spotify-Objekt und gibt die Konsolenausgabe zurück."""
    url = get_item_url(item)
    if not url:
        raise RuntimeError("Für dieses Element ist kein Spotify-Link verfügbar.")

    spotdl = shutil.which("spotdl")
    if not spotdl:
        raise RuntimeError(
            "spotdl ist nicht installiert. Installieren Sie es mit: pip install spotdl"
        )

    target_dir = os.path.expanduser(output_dir or cfg.get_download_dir())
    os.makedirs(target_dir, exist_ok=True)

    if progress_callback:
        progress_callback(0, 0)

    process = subprocess.Popen(
        [
            spotdl,
            "download",
            url,
            "--output",
            _spotdl_output_template(target_dir),
            "--bitrate",
            cfg.get_download_quality(),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # Ohne explizites Encoding dekodiert Python unter Windows mit der
        # ANSI-Codepage (cp1252) – ein Umlaut oder CJK-Zeichen im Songtitel
        # würde den Download mitten im Lesen mit UnicodeDecodeError abbrechen.
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=NO_WINDOW_FLAGS,
    )

    lines: list[str] = []
    total = 0
    done = 0
    # spotdl meldet die Anzahl gefundener Titel und je Titel eine "Downloaded"-Zeile.
    for line in process.stdout:
        if cancel_event is not None and cancel_event.is_set():
            process.terminate()
            process.wait(timeout=10)
            raise DownloadCancelled("Download abgebrochen.")
        lines.append(line)
        match = re.search(r"Found (\d+) song", line)
        if match:
            total = int(match.group(1))
            if progress_callback:
                progress_callback(done, total)
        if "Downloaded" in line:
            done += 1
            if progress_callback:
                progress_callback(done, total)
    process.wait()

    output = "".join(lines).strip()
    if process.returncode != 0:
        raise RuntimeError(output or "Download fehlgeschlagen.")
    return output
