import os
import datetime
from PyQt6.QtCore import QUrl, QObject, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSlot
from PyQt6.QtMultimedia import QSoundEffect

class AudioManager(QObject):
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.base_path = os.path.join(os.path.dirname(__file__), "Songs")
        self.console_players = {}
        self.active_console = None
        self.is_stopped = True
        self.current_sequence = "IDLE"
        
        self.fade_timer = None
        self.fade_anim = None
        self._fade_multiplier = 1.0
        self.global_volume = 0.5
        
        self._is_transitioning = False
        
        if config and "volume" in config:
            self.global_volume = config["volume"] / 100.0
            
        self._log("Initializing AudioManager engine")
        self._preload_boot_sound()

    def _log(self, message, level="INFO"):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [AUDIO][{level}] {message}")

    def _preload_boot_sound(self):
        if self.global_volume > 0.0:
            self._log("Preloading TriCore boot sound...")
            self._get_player("TriCore", "Startup", "Boot.wav")

    @pyqtProperty(float)
    def fade_multiplier(self):
        return self._fade_multiplier

    @fade_multiplier.setter
    def fade_multiplier(self, value):
        self._fade_multiplier = value
        actual_vol = self.global_volume * value
        for console, players in self.console_players.items():
            for sound_type, p in players.items():
                if p.isPlaying():
                    p.setVolume(actual_vol)

    def set_global_volume(self, volume_pct):
        self.global_volume = volume_pct / 100.0
        self._log(f"Global volume modified: {self.global_volume:.2f}")
        
        if self.global_volume == 0.0:
            self._stop_all_audio_only(force_all=True)
        else:
            actual_vol = self.global_volume * self.fade_multiplier
            for console, players in self.console_players.items():
                for sound_type, player in players.items():
                    player.setMuted(False)
                    if player.isPlaying():
                        player.setVolume(actual_vol)
                        
            if not self.is_stopped and self.active_console:
                if self.current_sequence == "WELCOME" and self.active_console == "TriCore":
                    loop_player = self._get_player("TriCore", "WelcomeLoop", "Welcome0_loop.wav")
                    if not loop_player.isPlaying():
                        self._force_play(loop_player)
                elif self.current_sequence == "DOWNLOADING":
                    running_player = self._get_player(self.active_console, "Running")
                    if not running_player.isPlaying():
                        self._force_play(running_player)

    def _is_valid_wav(self, file_path):
        is_valid = os.path.exists(file_path) and os.path.getsize(file_path) > 0
        if not is_valid:
            self._log(f"Invalid or missing file: {file_path}", "WARN")
        return is_valid

    def _on_player_status_changed(self, player, console, sound_type):
        status = player.status()
        if status == QSoundEffect.Status.Error:
            self._log(f"AUDIO ENGINE ERROR for {console}_{sound_type}! File may be corrupted or inaccessible.", "ERROR")
        elif status == QSoundEffect.Status.Ready:
            self._log(f"Player ready: {console}_{sound_type}")

    def _get_player(self, console, sound_type, custom_filename=None):
        if console not in self.console_players:
            self.console_players[console] = {}
            
        if sound_type not in self.console_players[console] or self.console_players[console][sound_type].status() == QSoundEffect.Status.Error:
            
            if sound_type in self.console_players[console]:
                self._log(f"Cleaning up old buggy player: {console}_{sound_type}", "WARN")
                old_p = self.console_players[console][sound_type]
                old_p.playingChanged.disconnect()
                old_p.statusChanged.disconnect()
                old_p.deleteLater()
                
            player = QSoundEffect(self)
            player.setVolume(self.global_volume * self.fade_multiplier)
            
            if sound_type in ("Running", "WelcomeLoop"):
                player.setLoopCount(QSoundEffect.Loop.Infinite.value)
            else:
                player.setLoopCount(1)
                
            filename = custom_filename if custom_filename else f"{console}_{sound_type}.wav"
            file_path = os.path.join(self.base_path, console, filename)
            fallback_filename = custom_filename if custom_filename else f"{sound_type}.wav"
            fallback_path = os.path.join(self.base_path, console, fallback_filename)
            
            loaded_path = None
            if self._is_valid_wav(file_path):
                loaded_path = file_path
            elif self._is_valid_wav(fallback_path):
                self._log(f"Using fallback file for {console}_{sound_type} -> {fallback_filename}")
                loaded_path = fallback_path
                
            if loaded_path:
                player.setSource(QUrl.fromLocalFile(loaded_path))
                self._log(f"Source loaded: {loaded_path}")
            else:
                self._log(f"No valid WAV file found for {console}_{sound_type}", "ERROR")
                
            player.statusChanged.connect(lambda p=player, c=console, t=sound_type: self._on_player_status_changed(p, c, t))
            player.playingChanged.connect(lambda p=player, c=console, t=sound_type: self._on_playback_changed(p, c, t))
            
            self.console_players[console][sound_type] = player
            
        return self.console_players[console][sound_type]

    def _force_play(self, player):
        if player.source().isEmpty() or self.global_volume == 0.0:
            self._log("Playback cancelled: empty source or volume is 0", "WARN")
            return
            
        if self.current_sequence not in ("WELCOME", "IDLE"):
            self.fade_multiplier = 1.0
            
        is_new_player_boot = any(
            p == player for c, p_dict in self.console_players.items() for t, p in p_dict.items() if t in ("Boot", "Startup")
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
            
        player.setMuted(False)
        player.setVolume(self.global_volume * self.fade_multiplier)
        
        self._log(f"Playback requested: {player.source().fileName()} (Effective Volume: {player.volume():.2f})")
        QTimer.singleShot(10, player.play)

    def _cancel_fades(self):
        if self.fade_timer:
            self.fade_timer.stop()
            self.fade_timer.deleteLater()
            self.fade_timer = None
        if self.fade_anim:
            self.fade_anim.stop()
            self.fade_anim.deleteLater() 
            self.fade_anim = None
        self._log("Ongoing fades cancelled.")

    def _schedule_running_fade(self, player):
        self._cancel_fades()
        self._log("Scheduling background fade-out (Running) in 5s...")
        self.fade_timer = QTimer(self)
        self.fade_timer.setSingleShot(True)
        
        def check_and_fade():
            if self.current_sequence == "DOWNLOADING":
                self._start_fade_anim(player)
            else:
                self._log("Fade-out cancelled: sequence is no longer DOWNLOADING.")
                
        self.fade_timer.timeout.connect(check_and_fade)
        self.fade_timer.start(5000)

    def _start_fade_anim(self, player):
        if not player.isPlaying(): 
            self._log("Fade-out ignored: Running player is already stopped.", "WARN")
            return
            
        self._cancel_fades()
        self._log("Starting fade-out animation (Running)...")
        
        self.fade_anim = QPropertyAnimation(self, b"fade_multiplier")
        self.fade_anim.setDuration(8000)
        self.fade_anim.setStartValue(self.fade_multiplier)
        self.fade_anim.setEndValue(0.2)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_anim.start()

    def _on_playback_changed(self, player, console, sound_type):
        if self._is_transitioning:
            return
            
        if player.isPlaying() or self.global_volume == 0.0:
            return

        self._log(f"Natural playback end detected: {console}_{sound_type}")

        if self.current_sequence == "DOWNLOADING" and self.active_console == console:
            if sound_type in ("Start", "Click"):
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
    def play_tricore_boot(self):
        self.current_sequence = "BOOT"
        player = self._get_player("TriCore", "Startup", "Boot.wav")
        self._force_play(player)

    @pyqtSlot()
    def play_welcome(self):
        self.stop_all()
        self.active_console = "TriCore"
        self.is_stopped = False
        self.current_sequence = "WELCOME"
        
        player_intro = self._get_player("TriCore", "WelcomeIntro", "Welcome0_intro.wav")
        self._get_player("TriCore", "WelcomeLoop", "Welcome0_loop.wav")
        
        if not player_intro.source().isEmpty():
            self._cancel_fades()
            self.fade_multiplier = 0.0
            self._force_play(player_intro)
            
            self._log("Starting WelcomeIntro fade-in...")
            self.fade_anim = QPropertyAnimation(self, b"fade_multiplier")
            self.fade_anim.setDuration(3000)
            self.fade_anim.setStartValue(0.0)
            self.fade_anim.setEndValue(1.0)
            self.fade_anim.setEasingCurve(QEasingCurve.Type.InQuad)
            self.fade_anim.start()

    @pyqtSlot(int)
    def fade_out_fast(self, duration=120):
        self._cancel_fades()
        active_player = None
        
        for console, players in self.console_players.items():
            for sound_type, player in players.items():
                if player.isPlaying() and sound_type not in ("Boot", "Startup"):
                    active_player = player
                    break
                    
        if active_player:
            self._log(f"Launching rapid fade-out of {duration}ms on {active_player.source().fileName()}")
            self.fade_anim = QPropertyAnimation(self, b"fade_multiplier")
            self.fade_anim.setDuration(duration)
            self.fade_anim.setStartValue(self.fade_multiplier)
            self.fade_anim.setEndValue(0.0)
            self.fade_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
            
            def on_fade_finished():
                self._log("Rapid fade-out completed. Stopping track.")
                self._is_transitioning = True
                try:
                    active_player.stop()
                finally:
                    self._is_transitioning = False
                    self.fade_multiplier = 1.0 
                    
            self.fade_anim.finished.connect(on_fade_finished)
            self.fade_anim.start()

    @pyqtSlot(str)
    def play_boot(self, console):
        self.current_sequence = "BOOT"
        player = self._get_player(console, "Boot")
        self._force_play(player)

    @pyqtSlot(str)
    def play_console_click(self, console):
        self.current_sequence = "CLICK"
        player = self._get_player(console, "Click")
        self._force_play(player)

    @pyqtSlot(str)
    def play_start_sequence(self, console):
        self.stop_all()
        self.active_console = console
        self.is_stopped = False
        self.current_sequence = "DOWNLOADING"
        
        self._log(f"Beginning START sequence for {console}")
        player_start = self._get_player(console, "Start")
        
        if player_start.source().isEmpty():
            self._log("Start sound missing, attempting fallback to Click...", "WARN")
            player_start = self._get_player(console, "Click")
            
        if player_start.source().isEmpty():
            self._log("Start/Click sound missing, skipping directly to Running...", "WARN")
            player_running = self._get_player(console, "Running")
            self._force_play(player_running)
            self._schedule_running_fade(player_running)
        else:
            self._force_play(player_start)

    @pyqtSlot(str, bool)
    def play_result(self, console, success):
        self.stop_all()
        self.active_console = console
        self.current_sequence = "RESULT"
        
        state = "Succes" if success else "Fail"
        self._log(f"RESULT Sequence: {state} for {console}")
        player_result = self._get_player(console, state)
        self._force_play(player_result)

    @pyqtSlot(str)
    def play_stop(self, console):
        self.stop_all()
        self.active_console = console
        self.current_sequence = "STOP"
        
        self._log(f"STOP Sequence for {console}")
        player_stop = self._get_player(console, "STOP")
        self._force_play(player_stop)

    @pyqtSlot()
    def play_test_sound(self):
        player_test = self._get_player("TriCore", "Test", "Test.wav")
        if not player_test.source().isEmpty() and self.global_volume > 0.0:
            self._is_transitioning = True
            try:
                if player_test.isPlaying():
                    player_test.stop()
            finally:
                self._is_transitioning = False
            
            player_test.setMuted(False)
            player_test.setVolume(self.global_volume * self.fade_multiplier)
            self._log("Playing test sound")
            QTimer.singleShot(10, player_test.play)

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
            
        self.fade_multiplier = 1.0

    @pyqtSlot()
    def stop_all(self):
        self._log("Global shutdown of all audio sequences.")
        self.is_stopped = True
        self.current_sequence = "IDLE"
        self._stop_all_audio_only()