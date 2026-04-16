from __future__ import annotations

import os
import random
import subprocess
from pathlib import Path
from threading import Event, Lock, Thread

from .config import get_settings


class MusicPlayer:
    def __init__(self) -> None:
        self.playlist: list[str] = []
        self.current_index = 0
        self.playing = False
        self.process: subprocess.Popen | None = None
        self.playlist_lock = Lock()
        self.stop_event = Event()
        self.player_thread: Thread | None = None

    def build_playlist(self, category: str | None = None, specific: str | None = None) -> int:
        settings = get_settings()
        with self.playlist_lock:
            self.playlist = []
            folder = settings.music_dir / (category or "general")
            if not folder.exists():
                return 0
            if specific:
                target = folder / specific
                if target.exists():
                    self.playlist = [str(target)]
                else:
                    matches = [str(folder / name) for name in os.listdir(folder) if specific.lower() in name.lower() and name.endswith(".mp3")]
                    self.playlist = matches
            else:
                self.playlist = [str(folder / name) for name in os.listdir(folder) if name.endswith(".mp3")]
                random.shuffle(self.playlist)
            self.current_index = 0
            return len(self.playlist)

    def start_playback(self, category: str | None = None, specific: str | None = None) -> bool:
        self.stop_playback()
        self.stop_event.clear()
        if self.build_playlist(category, specific) == 0:
            return False
        self.playing = True
        self.player_thread = Thread(target=self._playback_loop, daemon=True)
        self.player_thread.start()
        return True

    def _playback_loop(self) -> None:
        while not self.stop_event.is_set() and self.playlist:
            with self.playlist_lock:
                if self.current_index >= len(self.playlist):
                    self.current_index = 0
                current_song = self.playlist[self.current_index]
                self.current_index += 1
            self.process = subprocess.Popen(["mpg123", "-o", "pulse", current_song])
            self.process.wait()
            if self.stop_event.is_set():
                break
        self.playing = False
        self.process = None

    def stop_playback(self) -> None:
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.playing = False


music_player = MusicPlayer()


def play_music(category: str | None = None, track: str | None = None) -> bool:
    return music_player.start_playback(category, track)


def stop_music() -> None:
    music_player.stop_playback()
