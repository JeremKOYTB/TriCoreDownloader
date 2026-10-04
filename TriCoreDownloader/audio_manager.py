import os
import sys
import datetime
from PyQt6.QtCore import (
    QUrl,
    QObject,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    QAbstractAnimation,
    pyqtProperty,
    pyqtSlot,
)
from PyQt6.QtMultimedia import QSoundEffect


class AudioManager(QObject):
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.base_path = self._resolve_songs_path()
        self.console_players = {}
        self.active_console = None
        self.is_stopped = True
        self.current_sequence = "IDLE"

        self._path_cache = {}
        self._fade_multiplier = 1.0
        self.global_volume = 0.5
        self.running_player_to_fade = None
        self._is_transitioning = False

        if config and "volume" in config:
            try:
                self.global_volume = max(0.0, min(1.0, float(config["volume"]) / 100.0))
            except (ValueError, TypeError):
                self.global_volume = 0.5

        self.fade_timer = QTimer(self)
        self.fade_timer.setSingleShot(True)
        self.fade_timer.timeout.connect(self._on_fade_timer_timeout)

        self.start_fallback_timer = QTimer(self)
        self.start_fallback_timer.setSingleShot(True)
        self.start_fallback_timer.timeout.connect(self._on_start_sound_timeout)

        self.fade_anim = QPropertyAnimation(self, b"fade_multiplier", self)
        self._fade_finished_callback = None
        self.fade_anim.finished.connect(self._on_fade_anim_finished)

        self._log("Initializing AudioManager engine")
        self._preload_boot_sound()

    def _normalize_console(self, console):
        if not console:
            return "TriCore"
        c = str(console).strip().upper().replace(" ", "").replace("_", "")
        if c in ("CAFE", "WIIU"):
            return "CAFE"
        if c in ("CTR", "3DS"):
            return "CTR"
        if c in ("HAC", "SWITCH", "NX"):
            return "HAC"
        if c in ("TRICORE", "SYSTEM"):
            return "TriCore"
        return str(console).strip()

    def _resolve_songs_path(self):
        filename = "Songs"
        paths_to_check = []

        if hasattr(sys, "_MEIPASS"):
            paths_to_check.append(os.path.join(sys._MEIPASS, filename))

        if getattr(sys, "frozen", False):
            paths_to_check.append(os.path.join(os.path.dirname(sys.executable), filename))

        paths_to_check.append(os.path.join(os.path.dirname(__file__), filename))
        paths_to_check.append(os.path.join(os.getcwd(), filename))

        for p in paths_to_check:
            if os.path.isdir(p):
                return os.path.abspath(p)

        return os.path.abspath(os.path.join(os.path.dirname(__file__), filename))

    def _get_console_candidates(self, console):
        console_clean = self._normalize_console(console)
        mapping = {
            "CAFE": ["CAFE", "WiiU", "Wii U"],
            "CTR": ["CTR", "3DS"],
            "HAC": ["HAC", "Switch", "NX"],
            "TriCore": ["TriCore"],
        }
        return mapping.get(console_clean, [console_clean])

    def _log(self, message, level="INFO"):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [AUDIO][{level}] {message}")

    def _preload_boot_sound(self):
        if self.global_volume > 0.0:
            self._log("Preloading TriCore boot sound...")
            self._get_player("TriCore", "Startup", "Boot.wav")

    def get_fade_multiplier(self) -> float:
        return self._fade_multiplier

    def set_fade_multiplier(self, value: float):
        self._fade_multiplier = max(0.0, min(1.0, value))
        actual_vol = self.global_volume * self._fade_multiplier
        for p_dict in self.console_players.values():
            for p in p_dict.values():
                if p.isPlaying():
                    p.setVolume(actual_vol)

    fade_multiplier = pyqtProperty(
        float, fget=get_fade_multiplier, fset=set_fade_multiplier
    )

    def set_global_volume(self, volume_pct):
        try:
            self.global_volume = max(0.0, min(1.0, float(volume_pct) / 100.0))
        except (ValueError, TypeError):
            return

        self._log(f"Global volume modified: {self.global_volume:.2f}")

        if self.global_volume == 0.0:
            self._stop_all_audio_only(force_all=True)
        else:
            actual_vol = self.global_volume * self._fade_multiplier
            for p_dict in self.console_players.values():
                for player in p_dict.values():
                    player.setMuted(False)
                    if player.isPlaying():
                        player.setVolume(actual_vol)

            if not self.is_stopped and self.active_console:
                if (
                    self.current_sequence == "WELCOME"
                    and self.active_console == "TriCore"
                ):
                    loop_player = self._get_player(
                        "TriCore", "WelcomeLoop", "Welcome0_loop.wav"
                    )
                    if not loop_player.isPlaying():
                        self._force_play(loop_player)
                elif self.current_sequence == "DOWNLOADING":
                    running_player = self._get_player(
                        self.active_console, "Running"
                    )
                    if not running_player.isPlaying():
                        self._force_play(running_player)

    def _is_valid_wav(self, file_path):
        abs_path = os.path.abspath(file_path)
        if abs_path in self._path_cache:
            return self._path_cache[abs_path]
        is_valid = bool(os.path.isfile(abs_path) and os.path.getsize(abs_path) > 0)
        self._path_cache[abs_path] = is_valid
        if not is_valid:
            self._log(f"Invalid or missing file: {abs_path}", "WARN")
        return is_valid

    def _on_player_status_changed(self, player, console, sound_type):
        status = player.status()
        if status == QSoundEffect.Status.Error:
            self._log(
                f"AUDIO ENGINE ERROR for {console}_{sound_type}! File may be corrupted or inaccessible.",
                "ERROR",
            )
        elif status == QSoundEffect.Status.Ready:
            self._log(f"Player ready: {console}_{sound_type}")
            if getattr(player, "_play_on_ready", False):
                player._play_on_ready = False
                self._log(f"Executing deferred playback for {console}_{sound_type}")
                actual_vol = getattr(player, "_requested_volume", self.global_volume * self._fade_multiplier)
                player.setMuted(False)
                player.setVolume(actual_vol)
                player.stop()
                player.play()

    def _cleanup_player(self, player):
        if player:
            try:
                player.statusChanged.disconnect()
            except Exception:
                pass
            try:
                player.playingChanged.disconnect()
            except Exception:
                pass
            player.stop()
            player.deleteLater()

    def switch_console(self, console):
        target_console = self._normalize_console(console)
        self._log(f"Switching active console context to: {target_console}")
        self._cancel_fades()
        self._stop_all_audio_only(force_all=True)

        for cons, players in list(self.console_players.items()):
            if cons != target_console and cons != "TriCore":
                for sound_type, p in list(players.items()):
                    self._cleanup_player(p)
                self.console_players[cons].clear()

        self.active_console = target_console
        self.preload_console_sounds(target_console)

    def preload_console_sounds(self, console):
        console = self._normalize_console(console)
        if console == "TriCore":
            self._get_player("TriCore", "Startup", "Boot.wav")
            self._get_player("TriCore", "Reset", "Reset.wav")
            self._get_player("TriCore", "Test", "Test.wav")
            self._get_player("TriCore", "WelcomeIntro", "Welcome0_intro.wav")
            self._get_player("TriCore", "WelcomeLoop", "Welcome0_loop.wav")
            return

        sound_types = ["Boot", "Click", "Start", "Running", "Succes", "Fail", "Stop"]
        for s_type in sound_types:
            self._get_player(console, s_type)

    def _get_player(self, console, sound_type, custom_filename=None):
        console = self._normalize_console(console)
        if console not in self.console_players:
            self.console_players[console] = {}

        players_dict = self.console_players[console]
        existing_player = players_dict.get(sound_type)

        if existing_player is None or existing_player.status() == QSoundEffect.Status.Error or existing_player.source().isEmpty():
            if existing_player is not None:
                self._log(f"Cleaning up old buggy player: {console}_{sound_type}", "WARN")
                self._cleanup_player(existing_player)

            player = QSoundEffect(self)
            player.setVolume(self.global_volume * self._fade_multiplier)
            player._play_on_ready = False

            if sound_type in ("Running", "WelcomeLoop"):
                player.setLoopCount(QSoundEffect.Loop.Infinite.value)
            else:
                player.setLoopCount(1)

            loaded_path = None
            console_candidates = self._get_console_candidates(console)

            for c_cand in console_candidates:
                if console == "TriCore":
                    filename = custom_filename if custom_filename else f"{sound_type}.wav"
                    file_path = os.path.abspath(os.path.join(self.base_path, c_cand, filename))
                    if self._is_valid_wav(file_path):
                        loaded_path = file_path
                        break
                else:
                    filename = custom_filename if custom_filename else f"{c_cand}_{sound_type}.wav"
                    file_path = os.path.abspath(os.path.join(self.base_path, c_cand, filename))
                    fallback_filename = custom_filename if custom_filename else f"{sound_type}.wav"
                    fallback_path = os.path.abspath(os.path.join(self.base_path, c_cand, fallback_filename))

                    if self._is_valid_wav(file_path):
                        loaded_path = file_path
                        break
                    elif self._is_valid_wav(fallback_path):
                        self._log(f"Using fallback file for {console}_{sound_type} -> {fallback_filename}")
                        loaded_path = fallback_path
                        break

            if not loaded_path and custom_filename:
                direct_path = os.path.abspath(os.path.join(self.base_path, console, custom_filename))
                if self._is_valid_wav(direct_path):
                    loaded_path = direct_path

            if loaded_path:
                player.setSource(QUrl.fromLocalFile(loaded_path))
                self._log(f"Source loaded for {console}_{sound_type}: {loaded_path}")
            else:
                self._log(f"No valid WAV file found for {console}_{sound_type}", "ERROR")

            player.statusChanged.connect(
                lambda p=player, c=console, t=sound_type: self._on_player_status_changed(p, c, t)
            )
            player.playingChanged.connect(
                lambda p=player, c=console, t=sound_type: self._on_playback_changed(p, c, t)
            )

            players_dict[sound_type] = player

        return players_dict[sound_type]

    def _force_play(self, player, custom_volume=None):
        if player.source().isEmpty() or self.global_volume == 0.0:
            self._log("Playback cancelled: empty source or volume is 0", "WARN")
            return

        if self.current_sequence != "WELCOME":
            self._cancel_fades()

        is_new_player_boot = any(
            p == player
            for p_dict in self.console_players.values()
            for t, p in p_dict.items()
            if t in ("Boot", "Startup")
        )

        self._is_transitioning = True
        try:
            for console, players in self.console_players.items():
                for sound_type, p in players.items():
                    if p != player and p.isPlaying():
                        if sound_type in ("Boot", "Startup") and not is_new_player_boot:
                            continue
                        self._log(f"Stopping old track: {console}_{sound_type}")
                        p.stop()

            if player.isPlaying():
                player.stop()
        finally:
            self._is_transitioning = False

        actual_vol = custom_volume if custom_volume is not None else (self.global_volume * self._fade_multiplier)
        player._requested_volume = actual_vol

        if player.status() == QSoundEffect.Status.Ready:
            player._play_on_ready = False
            player.setMuted(False)
            player.setVolume(actual_vol)
            player.play()
            self._log(f"Playback started: {player.source().fileName()} (Vol: {player.volume():.2f})")
        else:
            player._play_on_ready = True
            self._log(f"Playback deferred until Ready: {player.source().fileName()}")

    def _cancel_fades(self):
        if self.fade_timer.isActive():
            self.fade_timer.stop()
        if self.start_fallback_timer.isActive():
            self.start_fallback_timer.stop()
        if self.fade_anim.state() == QAbstractAnimation.State.Running:
            self.fade_anim.stop()
        self._fade_finished_callback = None
        self.set_fade_multiplier(1.0)
        self._log("Ongoing fades cancelled.")

    def _on_fade_anim_finished(self):
        callback = self._fade_finished_callback
        self._fade_finished_callback = None
        if callback:
            callback()

    def _schedule_running_fade(self, player):
        self._cancel_fades()
        self.running_player_to_fade = player
        self._log("Scheduling background fade-out (Running) in 5s...")
        self.fade_timer.start(5000)

    def _on_fade_timer_timeout(self):
        if self.current_sequence == "DOWNLOADING" and self.running_player_to_fade:
            self._start_fade_anim(self.running_player_to_fade)
        else:
            self._log("Fade-out cancelled: sequence is no longer DOWNLOADING.")

    def _start_fade_anim(self, player):
        if not player.isPlaying():
            self._log("Fade-out ignored: Running player is already stopped.", "WARN")
            return

        self._cancel_fades()
        self._log("Starting fade-out animation (Running)...")

        self.fade_anim.setDuration(8000)
        self.fade_anim.setStartValue(self._fade_multiplier)
        self.fade_anim.setEndValue(0.2)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_anim.start()

    def _on_start_sound_timeout(self):
        if self.current_sequence == "DOWNLOADING" and self.active_console:
            running_player = self._get_player(self.active_console, "Running")
            if not running_player.isPlaying():
                self._log("Fallback timer triggered: forcing Running track.")
                self._force_play(running_player)
                self._schedule_running_fade(running_player)

    def _on_playback_changed(self, player, console, sound_type):
        if self._is_transitioning or player.isPlaying() or self.global_volume == 0.0:
            return

        self._log(f"Natural playback end detected: {console}_{sound_type}")

        if self.current_sequence == "DOWNLOADING" and self.active_console == console:
            if sound_type in ("Start", "Click"):
                if self.start_fallback_timer.isActive():
                    self.start_fallback_timer.stop()
                self._log(f"Auto-chaining: {sound_type} -> Running")
                player_running = self._get_player(console, "Running")
                self._force_play(player_running)
                self._schedule_running_fade(player_running)

        elif self.current_sequence == "WELCOME" and self.active_console == console:
            if sound_type == "WelcomeIntro":
                self._log("Auto-chaining: WelcomeIntro -> WelcomeLoop")
                player_welcome_loop = self._get_player("TriCore", "WelcomeLoop", "Welcome0_loop.wav")
                self._force_play(player_welcome_loop)

    @pyqtSlot()
    def play_reset_sound(self):
        self.current_sequence = "RESET"
        player = self._get_player("TriCore", "Reset", "Reset.wav")
        if not player.source().isEmpty():
            effective_vol = max(0.5, self.global_volume * self._fade_multiplier)
            self._log(f"Playing config reset sound (Effective Vol: {effective_vol:.2f})")
            self._force_play(player, custom_volume=effective_vol)
        else:
            self._log("Reset sound file missing or invalid (TriCore/Reset.wav)", "WARN")

    @pyqtSlot()
    def play_tricore_boot(self):
        self.switch_console("TriCore")
        self.current_sequence = "BOOT"
        player = self._get_player("TriCore", "Startup", "Boot.wav")
        self._force_play(player)

    @pyqtSlot()
    def play_welcome(self):
        self.stop_all()
        self.switch_console("TriCore")
        self.is_stopped = False
        self.current_sequence = "WELCOME"

        player_intro = self._get_player("TriCore", "WelcomeIntro", "Welcome0_intro.wav")
        self._get_player("TriCore", "WelcomeLoop", "Welcome0_loop.wav")

        if not player_intro.source().isEmpty():
            self._cancel_fades()
            self.set_fade_multiplier(0.0)
            self._force_play(player_intro)

            self._log("Starting WelcomeIntro fade-in...")
            self.fade_anim.setDuration(3000)
            self.fade_anim.setStartValue(0.0)
            self.fade_anim.setEndValue(1.0)
            self.fade_anim.setEasingCurve(QEasingCurve.Type.InQuad)
            self.fade_anim.start()

    @pyqtSlot(int)
    def fade_out_fast(self, duration=120):
        self._cancel_fades()
        active_player = None

        for players in self.console_players.values():
            for sound_type, player in players.items():
                if player.isPlaying() and sound_type not in ("Boot", "Startup"):
                    active_player = player
                    break
            if active_player:
                break

        if active_player:
            self._log(f"Launching rapid fade-out of {duration}ms on {active_player.source().fileName()}")
            
            def on_fade_finished():
                self._log("Rapid fade-out completed. Stopping track.")
                self._is_transitioning = True
                try:
                    active_player.stop()
                finally:
                    self._is_transitioning = False
                    self.set_fade_multiplier(1.0)

            self._fade_finished_callback = on_fade_finished
            self.fade_anim.setDuration(duration)
            self.fade_anim.setStartValue(self._fade_multiplier)
            self.fade_anim.setEndValue(0.0)
            self.fade_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
            self.fade_anim.start()
        else:
            self.set_fade_multiplier(1.0)

    @pyqtSlot(str)
    def play_boot(self, console):
        self.switch_console(console)
        self.current_sequence = "BOOT"
        player = self._get_player(self.active_console, "Startup" if self.active_console == "TriCore" else "Boot")
        self._force_play(player)

    @pyqtSlot(str)
    def play_console_click(self, console):
        self.switch_console(console)
        self.current_sequence = "CLICK"
        player = self._get_player(self.active_console, "Click")
        self._force_play(player)

    @pyqtSlot(str)
    def play_start_sequence(self, console):
        self.switch_console(console)
        self.stop_all()
        self.is_stopped = False
        self.current_sequence = "DOWNLOADING"

        self._log(f"Beginning START sequence for {self.active_console}")
        player_start = self._get_player(self.active_console, "Start")

        if player_start.source().isEmpty():
            self._log("Start sound missing, attempting fallback to Click...", "WARN")
            player_start = self._get_player(self.active_console, "Click")

        if player_start.source().isEmpty():
            self._log("Start/Click sound missing, skipping directly to Running...", "WARN")
            player_running = self._get_player(self.active_console, "Running")
            self._force_play(player_running)
            self._schedule_running_fade(player_running)
        else:
            self._force_play(player_start)
            self.start_fallback_timer.start(2500)

    @pyqtSlot(str, bool)
    def play_result(self, console, success):
        self.switch_console(console)
        self.stop_all()
        self.current_sequence = "RESULT"

        state = "Succes" if success else "Fail"
        self._log(f"RESULT Sequence: {state} for {self.active_console}")
        player_result = self._get_player(self.active_console, state)
        if player_result.source().isEmpty():
            player_result = self._get_player(self.active_console, "Error" if not success else "Success")
        self._force_play(player_result)

    @pyqtSlot(str)
    def play_stop(self, console):
        self.switch_console(console)
        self.stop_all()
        self.current_sequence = "STOP"

        self._log(f"STOP Sequence for {self.active_console}")
        player_stop = self._get_player(self.active_console, "STOP")
        if player_stop.source().isEmpty():
            player_stop = self._get_player(self.active_console, "Stop")
        self._force_play(player_stop)

    @pyqtSlot()
    def play_test_sound(self):
        player_test = self._get_player("TriCore", "Test", "Test.wav")
        if not player_test.source().isEmpty() and self.global_volume > 0.0:
            self._force_play(player_test)

    def _stop_all_audio_only(self, force_all=False):
        self._cancel_fades()

        self._is_transitioning = True
        try:
            for console, players in self.console_players.items():
                for sound_type, player in players.items():
                    if player.isPlaying():
                        if not force_all and sound_type in ("Boot", "Startup"):
                            continue
                        self._log(f"Forced stop: {console}_{sound_type}")
                        player.stop()
        finally:
            self._is_transitioning = False

        self.set_fade_multiplier(1.0)

    @pyqtSlot()
    def stop_all(self):
        self._log("Global shutdown of all audio sequences.")
        self.is_stopped = True
        self.current_sequence = "IDLE"
        self._stop_all_audio_only()

    def cleanup(self):
        self._cancel_fades()
        self._stop_all_audio_only(force_all=True)
        for players in self.console_players.values():
            for player in players.values():
                self._cleanup_player(player)
        self.console_players.clear()