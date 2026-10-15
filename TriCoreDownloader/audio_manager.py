import os
import sys
import time
import struct
import hashlib
import tempfile
import logging
from array import array
from PyQt6.QtCore import (
    QUrl,
    QObject,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    QAbstractAnimation,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtMultimedia import (
    QSoundEffect,
    QMediaPlayer,
    QAudioOutput,
    QMediaDevices,
)

logger = logging.getLogger("TriCoreBoot")

BGM_TYPES = ("Running", "WelcomeLoop", "WelcomeIntro")
INFINITE_LOOP_TYPES = ("Running", "WelcomeLoop")


class _FallbackMediaPlayer(QObject):
    statusChanged = pyqtSignal()
    playingChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        try:
            default_dev = QMediaDevices.defaultAudioOutput()
            if not default_dev.isNull():
                self._audio_output.setDevice(default_dev)
        except Exception:
            pass
        self._player.setAudioOutput(self._audio_output)

        self._status = QSoundEffect.Status.Null
        self._cancelled = False
        self._manual_stop = False
        self._play_on_ready = False
        self._was_interrupted = False
        self._is_bgm = False
        self._infinite_loop = False
        self._restarting_loop = False
        self._custom_volume = None
        self._fade_factor = 1.0
        self._fading_out = False
        self._fade_step = 0.05
        self._last_play_ts = 0.0
        self._console_name = ""
        self._sound_type = ""
        self._custom_filename = None
        self._file_path = ""
        self._raw_file_path = ""
        self._source_url = QUrl()

        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.errorOccurred.connect(self._on_error)

    def _on_media_status(self, media_status):
        if media_status == QMediaPlayer.MediaStatus.EndOfMedia:
            if (
                self._infinite_loop
                and not self._manual_stop
                and not self._cancelled
                and not self._fading_out
            ):
                self._restarting_loop = True
                try:
                    self._player.setPosition(0)
                    self._player.play()
                finally:
                    self._restarting_loop = False
                return

        if media_status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.EndOfMedia,
        ):
            if self._status != QSoundEffect.Status.Ready:
                self._status = QSoundEffect.Status.Ready
                self.statusChanged.emit()
        elif media_status == QMediaPlayer.MediaStatus.LoadingMedia:
            self._status = QSoundEffect.Status.Loading
        elif media_status in (
            QMediaPlayer.MediaStatus.InvalidMedia,
            QMediaPlayer.MediaStatus.NoMedia,
        ):
            if media_status == QMediaPlayer.MediaStatus.InvalidMedia:
                self._status = QSoundEffect.Status.Error
                self.statusChanged.emit()

    def _on_state_changed(self, state):
        if self._restarting_loop:
            return
        if (
            state == QMediaPlayer.PlaybackState.StoppedState
            and self._infinite_loop
            and not self._manual_stop
            and not self._cancelled
            and not self._fading_out
            and self._status == QSoundEffect.Status.Ready
        ):
            self._restarting_loop = True
            try:
                self._player.setPosition(0)
                self._player.play()
            finally:
                self._restarting_loop = False
            return
        self.playingChanged.emit()

    def _on_error(self, *args):
        self._status = QSoundEffect.Status.Error
        self.statusChanged.emit()

    def status(self):
        return self._status

    def isPlaying(self):
        return (
            self._restarting_loop
            or self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )

    def setVolume(self, vol: float):
        self._audio_output.setVolume(max(0.0, min(1.0, float(vol))))

    def setMuted(self, muted: bool):
        self._audio_output.setMuted(bool(muted))

    def setLoopCount(self, count):
        is_inf = False
        if count == QSoundEffect.Loop.Infinite or count == QMediaPlayer.Loops.Infinite:
            is_inf = True
        else:
            try:
                if int(count) < 0:
                    is_inf = True
            except Exception:
                is_inf = False

        self._infinite_loop = is_inf
        try:
            if is_inf:
                self._player.setLoops(QMediaPlayer.Loops.Infinite)
            else:
                self._player.setLoops(max(1, int(count)))
        except Exception:
            pass

    def setAudioDevice(self, device):
        try:
            if device and not device.isNull():
                self._audio_output.setDevice(device)
        except Exception:
            pass

    def setSource(self, url: QUrl):
        self._source_url = url
        self._status = QSoundEffect.Status.Loading
        self._player.setSource(url)
        if self._infinite_loop:
            try:
                self._player.setLoops(QMediaPlayer.Loops.Infinite)
            except Exception:
                pass

    def play(self):
        self._restarting_loop = True
        try:
            self._manual_stop = False
            self._was_interrupted = False
            self._audio_output.setMuted(False)

            if (
                self._player.mediaStatus() == QMediaPlayer.MediaStatus.NoMedia
                or self._player.mediaStatus() == QMediaPlayer.MediaStatus.InvalidMedia
                or self._player.error() != QMediaPlayer.Error.NoError
            ) and not self._source_url.isEmpty():
                self._player.setSource(QUrl())
                self._player.setSource(self._source_url)

            if self._infinite_loop:
                try:
                    self._player.setLoops(QMediaPlayer.Loops.Infinite)
                except Exception:
                    pass

            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.setPosition(0)
            else:
                self._player.setPosition(0)
                self._player.play()
        finally:
            self._restarting_loop = False

    def stop(self):
        self._manual_stop = True
        self._restarting_loop = False
        if self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._player.stop()


class AudioManager(QObject):
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.base_path = self._resolve_songs_path()
        self.console_players = {}
        self.active_console = None
        self.is_stopped = True
        self.current_sequence = "IDLE"

        self._files_index = {}
        self._wav_cache_dir = os.path.join(tempfile.gettempdir(), "TriCoreDownloader_AudioCache")
        self._normalized_wav_cache = {}
        self._master_fade = 1.0
        self._bgm_fade = 1.0
        self.global_volume = 0.5
        self.running_player_to_fade = None
        self._is_transitioning = False
        self._start_wait_retries = 0

        self._fading_players = set()
        self._fade_tick_ms = 35
        self._player_fade_timer = QTimer(self)
        self._player_fade_timer.setInterval(self._fade_tick_ms)
        self._player_fade_timer.timeout.connect(self._on_player_fade_tick)

        self._bgm_watchdog_timer = QTimer(self)
        self._bgm_watchdog_timer.setInterval(600)
        self._bgm_watchdog_timer.timeout.connect(self._on_bgm_watchdog_tick)

        if config and "volume" in config:
            try:
                self.global_volume = max(0.0, min(1.0, float(config["volume"]) / 100.0))
            except (ValueError, TypeError):
                self.global_volume = 0.5

        self._media_devices = None
        try:
            self._media_devices = QMediaDevices(self)
            self._media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)
        except Exception:
            pass

        self._index_sound_directory()

        self.fade_timer = QTimer(self)
        self.fade_timer.setSingleShot(True)
        self.fade_timer.timeout.connect(self._on_fade_timer_timeout)

        self.start_fallback_timer = QTimer(self)
        self.start_fallback_timer.setSingleShot(True)
        self.start_fallback_timer.timeout.connect(self._on_start_sound_timeout)

        self.fade_anim = QPropertyAnimation(self, b"master_fade", self)
        self._fade_finished_callback = None
        self.fade_anim.finished.connect(self._on_fade_anim_finished)

        self.bgm_anim = QPropertyAnimation(self, b"bgm_fade", self)

        self._preload_boot_sound()

    def _on_bgm_watchdog_tick(self):
        if self.is_stopped or self.global_volume <= 0.0 or self._is_transitioning:
            return

        if self.current_sequence == "DOWNLOADING" and self.active_console:
            cons_dict = self.console_players.get(self.active_console, {})
            start_p = cons_dict.get("Start") or cons_dict.get("Click")
            if start_p and (start_p.isPlaying() or getattr(start_p, "_play_on_ready", False)):
                if (time.monotonic() - getattr(start_p, "_last_play_ts", 0.0)) < 3.5:
                    return

            running_p = cons_dict.get("Running")
            if running_p is None or getattr(running_p, "_cancelled", False) or running_p.status() == QSoundEffect.Status.Error:
                running_p = self._get_player(self.active_console, "Running", force_new=True)

            if running_p and not getattr(running_p, "_fading_out", False):
                if not running_p.isPlaying() and not getattr(running_p, "_play_on_ready", False):
                    self._force_play(running_p, is_bgm=True, stop_others=False)
        elif self.current_sequence == "WELCOME" and self.active_console == "TriCore":
            cons_dict = self.console_players.get("TriCore", {})
            intro_p = cons_dict.get("WelcomeIntro")
            if intro_p and (intro_p.isPlaying() or getattr(intro_p, "_play_on_ready", False)):
                return

            loop_p = cons_dict.get("WelcomeLoop")
            if loop_p is None or getattr(loop_p, "_cancelled", False) or loop_p.status() == QSoundEffect.Status.Error:
                loop_p = self._get_player("TriCore", "WelcomeLoop", "Welcome0_loop.wav", force_new=True)

            if loop_p and not getattr(loop_p, "_fading_out", False):
                if not loop_p.isPlaying() and not getattr(loop_p, "_play_on_ready", False):
                    self._force_play(loop_p, is_bgm=True, stop_others=False)

    def _on_audio_outputs_changed(self):
        try:
            default_dev = QMediaDevices.defaultAudioOutput()
            if default_dev.isNull():
                return
            for p_dict in list(self.console_players.values()):
                for _, player in list(p_dict.items()):
                    if not player or getattr(player, "_cancelled", False):
                        continue
                    if isinstance(player, _FallbackMediaPlayer):
                        was_playing = player.isPlaying()
                        player.setAudioDevice(default_dev)
                        if was_playing and not player.isPlaying() and not getattr(player, "_fading_out", False):
                            player.play()
                    else:
                        try:
                            player.setAudioDevice(default_dev)
                        except Exception:
                            if not player.isPlaying():
                                player._was_interrupted = True
        except Exception:
            pass

    def _ensure_standard_pcm16_wav(self, file_path: str) -> str:
        if not file_path or not file_path.lower().endswith(".wav"):
            return file_path

        if file_path in self._normalized_wav_cache:
            cached = self._normalized_wav_cache[file_path]
            if os.path.isfile(cached) and os.path.getsize(cached) > 44:
                return cached

        try:
            with open(file_path, "rb") as f:
                raw = f.read()

            if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
                return file_path

            if (
                raw[12:16] == b"fmt "
                and struct.unpack_from("<I", raw, 16)[0] == 16
                and struct.unpack_from("<H", raw, 20)[0] == 1
                and struct.unpack_from("<H", raw, 34)[0] == 16
                and raw[36:40] == b"data"
            ):
                ch_cnt = struct.unpack_from("<H", raw, 22)[0]
                blk_align = max(2, ch_cnt * 2)
                d_sz = struct.unpack_from("<I", raw, 40)[0]
                if 44 + d_sz == len(raw) and (d_sz % blk_align) == 0:
                    self._normalized_wav_cache[file_path] = file_path
                    return file_path

            pos = 12
            fmt_data = None
            pcm_data = None
            total_len = len(raw)

            while pos + 8 <= total_len:
                chunk_id = raw[pos : pos + 4]
                chunk_size = struct.unpack_from("<I", raw, pos + 4)[0]
                chunk_start = pos + 8
                chunk_end = min(total_len, chunk_start + chunk_size)

                if chunk_id == b"fmt " and chunk_size >= 16:
                    fmt_data = raw[chunk_start:chunk_end]
                elif chunk_id == b"data":
                    pcm_data = raw[chunk_start:chunk_end]
                    break

                pos = chunk_start + chunk_size + (chunk_size & 1)

            if not fmt_data or pcm_data is None:
                return file_path

            audio_format, num_channels, sample_rate, _, _, bits_per_sample = struct.unpack_from(
                "<HHIIHH", fmt_data, 0
            )
            if num_channels <= 0 or sample_rate <= 0:
                return file_path

            if audio_format == 0xFFFE and len(fmt_data) >= 40:
                audio_format = struct.unpack_from("<H", fmt_data, 24)[0]

            out_pcm = None
            if audio_format == 1:
                if bits_per_sample == 16:
                    out_pcm = pcm_data
                elif bits_per_sample == 8:
                    samples = array("h", (((b - 128) << 8) for b in pcm_data))
                    if sys.byteorder != "little":
                        samples.byteswap()
                    out_pcm = samples.tobytes()
                elif bits_per_sample == 24:
                    n_samples = len(pcm_data) // 3
                    buf = bytearray(n_samples * 2)
                    buf[0::2] = pcm_data[1 : n_samples * 3 : 3]
                    buf[1::2] = pcm_data[2 : n_samples * 3 : 3]
                    out_pcm = bytes(buf)
                elif bits_per_sample == 32:
                    n_samples = len(pcm_data) // 4
                    buf = bytearray(n_samples * 2)
                    buf[0::2] = pcm_data[2 : n_samples * 4 : 4]
                    buf[1::2] = pcm_data[3 : n_samples * 4 : 4]
                    out_pcm = bytes(buf)
            elif audio_format == 3 and bits_per_sample == 32:
                floats = array("f")
                floats.frombytes(pcm_data[: (len(pcm_data) // 4) * 4])
                if sys.byteorder != "little":
                    floats.byteswap()
                pcm16 = array("h", (int(max(-1.0, min(1.0, x)) * 32767.0) for x in floats))
                if sys.byteorder != "little":
                    pcm16.byteswap()
                out_pcm = pcm16.tobytes()

            if out_pcm is None:
                return file_path

            block_align = num_channels * 2
            aligned_len = (len(out_pcm) // block_align) * block_align
            out_pcm = out_pcm[:aligned_len]
            if not out_pcm:
                return file_path

            os.makedirs(self._wav_cache_dir, exist_ok=True)
            stat_info = os.stat(file_path)
            digest = hashlib.md5(
                f"{file_path}:{stat_info.st_mtime_ns}:{stat_info.st_size}:v2".encode("utf-8")
            ).hexdigest()[:16]
            cached_path = os.path.join(self._wav_cache_dir, f"{digest}_{os.path.basename(file_path)}")

            if not os.path.isfile(cached_path) or os.path.getsize(cached_path) <= 44:
                byte_rate = sample_rate * block_align
                data_size = len(out_pcm)
                header = struct.pack(
                    "<4sI4s4sIHHIIHH4sI",
                    b"RIFF",
                    36 + data_size,
                    b"WAVE",
                    b"fmt ",
                    16,
                    1,
                    num_channels,
                    sample_rate,
                    byte_rate,
                    block_align,
                    16,
                    b"data",
                    data_size,
                )
                with open(cached_path, "wb") as out_f:
                    out_f.write(header)
                    out_f.write(out_pcm)

            self._normalized_wav_cache[file_path] = cached_path
            return cached_path
        except Exception:
            return file_path

    def _to_linear_amplitude(self, perceived_vol: float) -> float:
        vol = max(0.0, min(1.0, float(perceived_vol)))
        return vol * vol

    def _get_effective_volume(self, is_bgm: bool = False) -> float:
        if self.global_volume <= 0.0:
            return 0.0
        amp = self._to_linear_amplitude(self.global_volume) * self._master_fade
        if is_bgm:
            amp *= self._bgm_fade
        return max(0.0, min(1.0, amp))

    def _apply_player_volume(self, player):
        if not player or getattr(player, "_cancelled", False):
            return
        if self.global_volume <= 0.0:
            player.setVolume(0.0)
            return

        custom_vol = getattr(player, "_custom_volume", None)
        s_type = getattr(player, "_sound_type", "")
        is_bgm = getattr(player, "_is_bgm", s_type in BGM_TYPES)

        if custom_vol is not None:
            base_vol = max(0.0, min(1.0, custom_vol * self._master_fade))
        else:
            base_vol = self._get_effective_volume(is_bgm=is_bgm)

        fade_factor = max(0.0, min(1.0, getattr(player, "_fade_factor", 1.0)))
        player.setVolume(max(0.0, min(1.0, base_vol * fade_factor)))

    def _cancel_player_fade(self, player):
        if not player:
            return
        self._fading_players.discard(player)
        player._fading_out = False
        player._fade_factor = 1.0
        if not self._fading_players and self._player_fade_timer.isActive():
            self._player_fade_timer.stop()

    def _fade_out_player(self, player, duration_ms=240):
        if not player or getattr(player, "_cancelled", False):
            return

        s_type = getattr(player, "_sound_type", "")
        is_bgm = getattr(player, "_is_bgm", s_type in BGM_TYPES)

        if not is_bgm or not isinstance(player, _FallbackMediaPlayer):
            self._cancel_player_fade(player)
            self._stop_player(player)
            return

        if getattr(player, "_play_on_ready", False) and not player.isPlaying():
            player._play_on_ready = False
            player._fading_out = False
            player._fade_factor = 1.0
            self._fading_players.discard(player)
            return

        if not player.isPlaying() or self.global_volume <= 0.0 or duration_ms <= 0:
            self._cancel_player_fade(player)
            self._stop_player(player)
            return

        steps = max(1.0, float(duration_ms) / float(self._fade_tick_ms))
        cur_factor = getattr(player, "_fade_factor", 1.0)
        if cur_factor <= 0.04:
            self._cancel_player_fade(player)
            self._stop_player(player)
            return

        if player in self._fading_players:
            player._fade_step = max(getattr(player, "_fade_step", 0.08), cur_factor / steps)
            return

        player._play_on_ready = False
        player._fading_out = True
        player._fade_factor = cur_factor
        player._fade_step = cur_factor / steps
        self._fading_players.add(player)

        if not self._player_fade_timer.isActive():
            self._player_fade_timer.start(self._fade_tick_ms)

    def _on_player_fade_tick(self):
        if not self._fading_players:
            self._player_fade_timer.stop()
            return

        for p in list(self._fading_players):
            if getattr(p, "_cancelled", False) or not p.isPlaying():
                p._fading_out = False
                p._fade_factor = 1.0
                self._fading_players.discard(p)
                self._apply_player_volume(p)
                continue

            new_factor = getattr(p, "_fade_factor", 1.0) - getattr(p, "_fade_step", 0.1)
            if new_factor <= 0.04:
                p._fading_out = False
                p._fade_factor = 1.0
                self._fading_players.discard(p)
                self._stop_player(p)
                self._apply_player_volume(p)
            else:
                p._fade_factor = new_factor
                self._apply_player_volume(p)

        if not self._fading_players and self._player_fade_timer.isActive():
            self._player_fade_timer.stop()

    def _normalize_console(self, console):
        if not console:
            return "TriCore"
        c = str(console).strip().upper().replace(" ", "").replace("_", "")
        if c in ("CAFE", "WIIU"):
            return "CAFE"
        if c in ("CTR", "3DS"):
            return "CTR"
        if c in ("NX", "HAC", "SWITCH"):
            return "NX"
        if c in ("TRICORE", "SYSTEM", "WELCOME"):
            return "TriCore"
        return str(console).strip()

    def _resolve_songs_path(self):
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "Songs"))
            candidates.append(os.path.join(sys._MEIPASS, "TriCoreDownloader", "Songs"))

        appdir = os.environ.get("APPDIR")
        if appdir:
            candidates.append(os.path.join(appdir, "usr", "bin", "Songs"))
            candidates.append(os.path.join(appdir, "usr", "bin", "TriCoreDownloader", "Songs"))
            candidates.append(os.path.join(appdir, "Songs"))

        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            candidates.append(os.path.join(exe_dir, "Songs"))
            candidates.append(os.path.join(exe_dir, "TriCoreDownloader", "Songs"))
            candidates.append(os.path.join(exe_dir, "_internal", "Songs"))
            candidates.append(os.path.join(exe_dir, "_internal", "TriCoreDownloader", "Songs"))
            candidates.append(os.path.join(exe_dir, "..", "Resources", "Songs"))
            candidates.append(os.path.join(exe_dir, "..", "Resources", "TriCoreDownloader", "Songs"))

        curr_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(curr_dir, "Songs"))
        candidates.append(os.path.join(os.path.dirname(curr_dir), "Songs"))
        candidates.append(os.path.join(os.getcwd(), "Songs"))
        candidates.append(os.path.join(os.getcwd(), "TriCoreDownloader", "Songs"))

        for path in candidates:
            norm = os.path.abspath(path)
            if os.path.isdir(norm) and os.path.isdir(os.path.join(norm, "TriCore")):
                return norm

        for path in candidates:
            norm = os.path.abspath(path)
            if os.path.isdir(norm):
                return norm

        return os.path.abspath(os.path.join(curr_dir, "Songs"))

    def _index_sound_directory(self):
        self._files_index.clear()
        if not os.path.isdir(self.base_path):
            logger.warning(f"Répertoire audio introuvable : {self.base_path}")
            return
        for root, _, files in os.walk(self.base_path):
            for file in files:
                if file.lower().endswith((".wav", ".ogg", ".mp3", ".flac")):
                    full_path = os.path.abspath(os.path.join(root, file))
                    if os.path.isfile(full_path) and os.path.getsize(full_path) > 0:
                        rel_dir = os.path.basename(root).upper()
                        key = f"{rel_dir}/{file.lower()}"
                        self._files_index[key] = full_path

    def _get_console_candidates(self, console):
         norm = self._normalize_console(console)
         mapping = {
             "CAFE": ["CAFE", "WIIU"],
             "CTR": ["CTR", "3DS"],
             "NX": ["NX", "HAC", "SWITCH"],
             "TRICORE": ["TRICORE"],
         }
         return mapping.get(norm.upper(), [norm.upper()])

    def _resolve_file_path(self, console, sound_type, custom_filename=None):
        if not self._files_index and os.path.isdir(self.base_path):
            self._index_sound_directory()

        console_clean = self._normalize_console(console)
        candidates = self._get_console_candidates(console_clean)

        filenames_to_try = []
        if custom_filename:
            filenames_to_try.append(custom_filename.lower())

        st = sound_type.lower()
        variants = [st]
        if st in ("stop", "cafe_stop", "ctr_stop", "nx_stop"):
            variants.extend(["stop", "cafe_stop", "ctr_stop", "nx_stop"])
        elif st in ("succes", "success", "error", "fail"):
            if st in ("succes", "success"):
                variants.extend(["succes", "success"])
            else:
                variants.extend(["fail", "error"])
        elif st in ("startup", "boot"):
            variants.extend(["startup", "boot"])

        for c_cand in candidates:
            if console_clean == "TriCore":
                for v in variants:
                    filenames_to_try.append(f"{v}.wav")
            else:
                for v in variants:
                    filenames_to_try.append(f"{c_cand.lower()}_{v}.wav")
                    filenames_to_try.append(f"{v}.wav")

        for c_cand in candidates:
            for fname in filenames_to_try:
                key = f"{c_cand}/{fname}"
                if key in self._files_index:
                    return self._files_index[key]

        if custom_filename:
            direct_check = os.path.abspath(os.path.join(self.base_path, console_clean, custom_filename))
            if os.path.isfile(direct_check) and os.path.getsize(direct_check) > 0:
                return direct_check

        return None

    def _preload_boot_sound(self):
        raw_p = self._resolve_file_path("TriCore", "Startup", "Boot.wav")
        if raw_p:
            self._ensure_standard_pcm16_wav(raw_p)

    def get_master_fade(self) -> float:
        return self._master_fade

    def set_master_fade(self, value: float):
        self._master_fade = max(0.0, min(1.0, value))
        self._update_all_active_volumes()

    master_fade = pyqtProperty(float, fget=get_master_fade, fset=set_master_fade)

    def get_bgm_fade(self) -> float:
        return self._bgm_fade

    def set_bgm_fade(self, value: float):
        self._bgm_fade = max(0.0, min(1.0, value))
        self._update_all_active_volumes()

    bgm_fade = pyqtProperty(float, fget=get_bgm_fade, fset=set_bgm_fade)

    def _update_all_active_volumes(self):
        for p_dict in list(self.console_players.values()):
            for _, p in list(p_dict.items()):
                if p and (p.isPlaying() or getattr(p, "_play_on_ready", False)):
                    self._apply_player_volume(p)

    def set_global_volume(self, volume_pct):
        prev_vol = self.global_volume
        try:
            self.global_volume = max(0.0, min(1.0, float(volume_pct) / 100.0))
        except (ValueError, TypeError):
            return

        if self.global_volume == 0.0:
            self._stop_all_audio_only(force_all=True, smooth=False)
            return

        for p_dict in list(self.console_players.values()):
            for _, player in list(p_dict.items()):
                if player and player.isPlaying():
                    player.setMuted(False)
                    self._apply_player_volume(player)

        if prev_vol <= 0.0 and not self.is_stopped and self.active_console:
            if self.current_sequence == "WELCOME" and self.active_console == "TriCore":
                intro_player = self.console_players.get("TriCore", {}).get("WelcomeIntro")
                loop_player = self._get_player("TriCore", "WelcomeLoop", "Welcome0_loop.wav")
                if (
                    (not intro_player or not intro_player.isPlaying() or getattr(intro_player, "_fading_out", False))
                    and loop_player
                    and (not loop_player.isPlaying() or getattr(loop_player, "_fading_out", False))
                ):
                    self._force_play(loop_player, is_bgm=True, stop_others=False)
            elif self.current_sequence == "DOWNLOADING":
                start_player = self.console_players.get(self.active_console, {}).get("Start")
                running_player = self._get_player(self.active_console, "Running")
                if (
                    (not start_player or not start_player.isPlaying() or getattr(start_player, "_fading_out", False))
                    and running_player
                    and (not running_player.isPlaying() or getattr(running_player, "_fading_out", False))
                ):
                    self._force_play(running_player, is_bgm=True, stop_others=False)
                    self._schedule_running_fade(running_player)

    def _promote_to_fallback_player(self, failed_player, console, sound_type):
        file_path = getattr(failed_player, "_file_path", None) or getattr(failed_player, "_raw_file_path", None)
        if not file_path or not os.path.isfile(file_path):
            return None

        want_play = getattr(failed_player, "_play_on_ready", False)
        custom_vol = getattr(failed_player, "_custom_volume", None)
        custom_fname = getattr(failed_player, "_custom_filename", None)
        is_bgm = getattr(failed_player, "_is_bgm", sound_type in BGM_TYPES)
        is_inf = getattr(failed_player, "_infinite_loop", sound_type in INFINITE_LOOP_TYPES)

        self._cleanup_player(failed_player)

        fallback = _FallbackMediaPlayer(self)
        fallback._console_name = console
        fallback._sound_type = sound_type
        fallback._custom_filename = custom_fname
        fallback._file_path = file_path
        fallback._raw_file_path = file_path
        fallback._is_bgm = is_bgm
        fallback._infinite_loop = is_inf
        fallback._custom_volume = custom_vol
        fallback._fade_factor = 1.0
        fallback._fading_out = False
        fallback._play_on_ready = want_play

        if is_inf:
            fallback.setLoopCount(QSoundEffect.Loop.Infinite)
        else:
            fallback.setLoopCount(1)

        fallback.statusChanged.connect(
            lambda *args, p=fallback, c=console, t=sound_type: self._on_player_status_changed(p, c, t)
        )
        fallback.playingChanged.connect(
            lambda *args, p=fallback, c=console, t=sound_type: self._on_playback_changed(p, c, t)
        )

        self.console_players.setdefault(console, {})[sound_type] = fallback
        fallback.setSource(QUrl.fromLocalFile(os.path.abspath(file_path)))
        return fallback

    def _verify_sfx_started(self, player, console, sound_type, play_ts):
        if (
            not player
            or getattr(player, "_cancelled", False)
            or getattr(player, "_manual_stop", False)
            or isinstance(player, _FallbackMediaPlayer)
            or getattr(player, "_last_play_ts", 0.0) != play_ts
            or self.global_volume <= 0.0
        ):
            return

        if not player.isPlaying() and player.status() == QSoundEffect.Status.Error:
            player._play_on_ready = True
            self._promote_to_fallback_player(player, console, sound_type)

    def _start_player_now(self, player):
        now = time.monotonic()
        self._cancel_player_fade(player)
        player._play_on_ready = False
        player._manual_stop = False
        player._was_interrupted = False
        if getattr(player, "_infinite_loop", False):
            try:
                player.setLoopCount(QSoundEffect.Loop.Infinite)
            except Exception:
                player.setLoopCount(-2)
        player.setMuted(False)
        self._apply_player_volume(player)
        player._last_play_ts = now
        player.play()
        if not isinstance(player, _FallbackMediaPlayer):
            cons = getattr(player, "_console_name", self.active_console or "TriCore")
            s_type = getattr(player, "_sound_type", "")
            QTimer.singleShot(
                80,
                lambda p=player, c=cons, t=s_type, ts=now: self._verify_sfx_started(p, c, t, ts),
            )

    def _on_player_status_changed(self, player, console, sound_type):
        if getattr(player, "_cancelled", False):
            return
        status = player.status()
        if status == QSoundEffect.Status.Ready:
            if getattr(player, "_play_on_ready", False):
                player._play_on_ready = False
                if self.global_volume <= 0.0:
                    return
                self._cancel_player_fade(player)
                self._start_player_now(player)
        elif status == QSoundEffect.Status.Error:
            if not isinstance(player, _FallbackMediaPlayer):
                self._promote_to_fallback_player(player, console, sound_type)
            else:
                player._play_on_ready = False
                src = getattr(player, "_file_path", "")
                logger.warning(f"Erreur de lecture audio pour {console}/{sound_type} ({src}).")

    def _stop_player(self, player):
        if not player or getattr(player, "_cancelled", False):
            return
        self._fading_players.discard(player)
        player._fading_out = False
        player._fade_factor = 1.0
        player._play_on_ready = False
        player._manual_stop = True
        if player.isPlaying():
            player._was_interrupted = True
            player.stop()

    def _cleanup_player(self, player):
        if not player:
            return
        self._fading_players.discard(player)
        player._cancelled = True
        player._fading_out = False
        player._play_on_ready = False
        player._manual_stop = True
        try:
            player.statusChanged.disconnect()
        except Exception:
            pass
        try:
            player.playingChanged.disconnect()
        except Exception:
            pass
        try:
            player.setMuted(True)
            player.setVolume(0.0)
            player.stop()
            player.deleteLater()
        except Exception:
            pass

    def switch_console(self, console):
        target = self._normalize_console(console)
        self._cancel_fades()

        if self.active_console == target:
            self.preload_console_sounds(target)
            return

        for cons, players in list(self.console_players.items()):
            if cons != target:
                for s_type, p in list(players.items()):
                    if p and (p.isPlaying() or getattr(p, "_play_on_ready", False)):
                        if s_type == "Test":
                            continue
                        self._fade_out_player(p, duration_ms=220)

        self.active_console = target
        self.preload_console_sounds(target)

    def preload_console_sounds(self, console):
        cons = self._normalize_console(console)
        if cons == "TriCore":
            for s_type, fname in (
                ("Startup", "Boot.wav"),
                ("Reset", "Reset.wav"),
                ("Test", "Test.wav"),
                ("WelcomeIntro", "Welcome0_intro.wav"),
                ("WelcomeLoop", "Welcome0_loop.wav"),
            ):
                raw_p = self._resolve_file_path("TriCore", s_type, fname)
                if raw_p:
                    self._ensure_standard_pcm16_wav(raw_p)
            return

        for s_type in ("Boot", "Click", "Start", "Running", "Succes", "Fail", "STOP"):
            raw_p = self._resolve_file_path(cons, s_type)
            if raw_p:
                self._ensure_standard_pcm16_wav(raw_p)

    def _get_player(self, console, sound_type, custom_filename=None, force_new=False):
        cons = self._normalize_console(console)
        if cons not in self.console_players:
            self.console_players[cons] = {}

        players_dict = self.console_players[cons]
        existing = players_dict.get(sound_type)

        if (
            not force_new
            and existing is not None
            and not getattr(existing, "_cancelled", False)
            and existing.status() != QSoundEffect.Status.Error
        ):
            return existing

        if existing is not None:
            self._cleanup_player(existing)
            players_dict.pop(sound_type, None)

        raw_file_path = self._resolve_file_path(cons, sound_type, custom_filename)
        if not raw_file_path:
            return None

        play_file_path = self._ensure_standard_pcm16_wav(raw_file_path)
        is_bgm = sound_type in BGM_TYPES
        is_inf = sound_type in INFINITE_LOOP_TYPES
        use_media_player = is_bgm or (not play_file_path.lower().endswith(".wav"))

        if use_media_player:
            player = _FallbackMediaPlayer(self)
        else:
            player = QSoundEffect(self)
            try:
                default_dev = QMediaDevices.defaultAudioOutput()
                if not default_dev.isNull():
                    player.setAudioDevice(default_dev)
            except Exception:
                pass

        player._cancelled = False
        player._manual_stop = False
        player._was_interrupted = False
        player._console_name = cons
        player._sound_type = sound_type
        player._custom_filename = custom_filename
        player._raw_file_path = raw_file_path
        player._file_path = play_file_path
        player._custom_volume = None
        player._fade_factor = 1.0
        player._fading_out = False
        player._fade_step = 0.08
        player._last_play_ts = 0.0
        player._is_bgm = is_bgm
        player._infinite_loop = is_inf
        player._play_on_ready = False

        player.setVolume(self._get_effective_volume(is_bgm=is_bgm))

        if is_inf:
            try:
                player.setLoopCount(QSoundEffect.Loop.Infinite)
            except Exception:
                player.setLoopCount(-2)
        else:
            player.setLoopCount(1)

        player.statusChanged.connect(
            lambda *args, p=player, c=cons, t=sound_type: self._on_player_status_changed(p, c, t)
        )
        player.playingChanged.connect(
            lambda *args, p=player, c=cons, t=sound_type: self._on_playback_changed(p, c, t)
        )

        player.setSource(QUrl.fromLocalFile(os.path.abspath(play_file_path)))
        players_dict[sound_type] = player
        return player

    def _force_play(self, player, custom_volume=None, stop_others=True, is_bgm=False, fade_others_ms=220):
        if not player:
            return None

        now = time.monotonic()
        s_type_self = getattr(player, "_sound_type", "")
        cons_self = getattr(player, "_console_name", self.active_console or "TriCore")
        custom_fname_self = getattr(player, "_custom_filename", None)

        if (
            (player.isPlaying() or getattr(player, "_play_on_ready", False))
            and not getattr(player, "_fading_out", False)
            and s_type_self in ("Boot", "Startup", "Running", "WelcomeIntro", "WelcomeLoop")
            and (now - getattr(player, "_last_play_ts", 0.0)) < 0.35
        ):
            return player

        if stop_others:
            if not (self.current_sequence == "WELCOME" and s_type_self in ("WelcomeIntro", "WelcomeLoop")):
                self._cancel_fades()

        self._cancel_player_fade(player)

        self._is_transitioning = True
        try:
            if stop_others:
                for _, players in list(self.console_players.items()):
                    for s_type, p in list(players.items()):
                        if p != player and p and (p.isPlaying() or getattr(p, "_play_on_ready", False)):
                            if s_type == "Test":
                                continue
                            if fade_others_ms > 0 and p.isPlaying() and getattr(p, "_is_bgm", False):
                                self._fade_out_player(p, duration_ms=fade_others_ms)
                            else:
                                self._stop_player(p)

            if player.isPlaying() and not isinstance(player, _FallbackMediaPlayer):
                self._stop_player(player)
        finally:
            self._is_transitioning = False

        if getattr(player, "_cancelled", False) or player.status() == QSoundEffect.Status.Error:
            player = self._get_player(cons_self, s_type_self, custom_fname_self, force_new=True)
            if not player:
                return None

        if self.global_volume <= 0.0:
            return player

        player._is_bgm = is_bgm or (s_type_self in BGM_TYPES)
        player._infinite_loop = s_type_self in INFINITE_LOOP_TYPES
        player._custom_volume = custom_volume
        player._cancelled = False
        player._fade_factor = 1.0
        player._fading_out = False

        st = player.status()
        if st == QSoundEffect.Status.Error:
            player._play_on_ready = True
            player = self._promote_to_fallback_player(player, cons_self, s_type_self)
            return player

        if st == QSoundEffect.Status.Ready:
            self._start_player_now(player)
        else:
            player._play_on_ready = True
            player._last_play_ts = now

        return player

    def _cancel_fades(self):
        if self.fade_timer.isActive():
            self.fade_timer.stop()
        if self.start_fallback_timer.isActive():
            self.start_fallback_timer.stop()
        if self.fade_anim.state() == QAbstractAnimation.State.Running:
            self.fade_anim.stop()
        if self.bgm_anim.state() == QAbstractAnimation.State.Running:
            self.bgm_anim.stop()

        self._fade_finished_callback = None
        self._master_fade = 1.0
        self._bgm_fade = 1.0
        self._update_all_active_volumes()

    def _on_fade_anim_finished(self):
        cb = self._fade_finished_callback
        self._fade_finished_callback = None
        if cb:
            cb()

    def _schedule_running_fade(self, player):
        self.fade_timer.stop()
        if self.bgm_anim.state() == QAbstractAnimation.State.Running:
            self.bgm_anim.stop()
        self._bgm_fade = 1.0
        self.running_player_to_fade = player
        self.fade_timer.start(5000)

    def _on_fade_timer_timeout(self):
        if self.current_sequence == "DOWNLOADING" and self.running_player_to_fade:
            self._start_bgm_fade_anim(self.running_player_to_fade)

    def _start_bgm_fade_anim(self, player):
        if not player or not player.isPlaying() or getattr(player, "_fading_out", False):
            return
        if self.bgm_anim.state() == QAbstractAnimation.State.Running:
            self.bgm_anim.stop()

        self.bgm_anim.setDuration(8000)
        self.bgm_anim.setStartValue(self._bgm_fade)
        self.bgm_anim.setEndValue(0.45)
        self.bgm_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.bgm_anim.start()

    def _on_start_sound_timeout(self):
        if self.current_sequence == "DOWNLOADING" and self.active_console:
            start_p = self.console_players.get(self.active_console, {}).get("Start")
            if (
                start_p
                and start_p.isPlaying()
                and not getattr(start_p, "_fading_out", False)
                and self._start_wait_retries < 3
            ):
                self._start_wait_retries += 1
                self.start_fallback_timer.start(800)
                return

            running = self._get_player(self.active_console, "Running")
            if running and (not running.isPlaying() or getattr(running, "_fading_out", False)):
                self._force_play(running, is_bgm=True, stop_others=False)
                self._schedule_running_fade(running)

    def _on_playback_changed(self, player, console, sound_type):
        if (
            getattr(player, "_cancelled", False)
            or getattr(player, "_manual_stop", False)
            or getattr(player, "_fading_out", False)
            or self._is_transitioning
            or self.global_volume <= 0.0
        ):
            return

        if not player.isPlaying():
            if self.current_sequence == "DOWNLOADING" and self.active_console == console:
                if sound_type in ("Start", "Click"):
                    if self.start_fallback_timer.isActive():
                        self.start_fallback_timer.stop()

                    running_player = self.console_players.get(console, {}).get("Running")
                    if not running_player or not running_player.isPlaying() or getattr(running_player, "_fading_out", False):
                        running = self._get_player(console, "Running")
                        if running:
                            self._force_play(running, is_bgm=True, stop_others=False)
                            self._schedule_running_fade(running)
                elif sound_type == "Running":
                    self._start_player_now(player)
            elif self.current_sequence == "WELCOME" and self.active_console == console:
                if sound_type == "WelcomeIntro":
                    loop_player = self.console_players.get("TriCore", {}).get("WelcomeLoop")
                    if not loop_player or not loop_player.isPlaying() or getattr(loop_player, "_fading_out", False):
                        loop = self._get_player("TriCore", "WelcomeLoop", "Welcome0_loop.wav")
                        if loop:
                            self._force_play(loop, is_bgm=True, stop_others=False)
                elif sound_type == "WelcomeLoop":
                    self._start_player_now(player)

    @pyqtSlot()
    def play_reset_sound(self):
        self._bgm_watchdog_timer.stop()
        self.is_stopped = False
        self.current_sequence = "RESET"
        if self.global_volume <= 0.0:
            return
        player = self._get_player("TriCore", "Reset", "Reset.wav")
        if player:
            raw = max(0.5, self.global_volume)
            self._force_play(player, custom_volume=self._to_linear_amplitude(raw), fade_others_ms=180)

    @pyqtSlot()
    def play_tricore_boot(self):
        self._bgm_watchdog_timer.stop()
        self.switch_console("TriCore")
        self.is_stopped = False
        self.current_sequence = "BOOT"
        if self.global_volume <= 0.0:
            return
        player = self._get_player("TriCore", "Startup", "Boot.wav")
        if player:
            self._force_play(player, fade_others_ms=220)

    @pyqtSlot()
    def play_welcome(self):
        self._stop_all_audio_only(force_all=False, smooth=False)
        self.switch_console("TriCore")
        self.is_stopped = False
        self.current_sequence = "WELCOME"
        self._bgm_watchdog_timer.start()

        intro = self._get_player("TriCore", "WelcomeIntro", "Welcome0_intro.wav")
        loop = self._get_player("TriCore", "WelcomeLoop", "Welcome0_loop.wav")

        if self.global_volume <= 0.0:
            return

        target_player = intro if intro is not None else loop
        if target_player:
            self._cancel_fades()
            self._master_fade = 0.0
            self._force_play(target_player, is_bgm=True, fade_others_ms=0)

            self.fade_anim.setDuration(3000)
            self.fade_anim.setStartValue(0.0)
            self.fade_anim.setEndValue(1.0)
            self.fade_anim.setEasingCurve(QEasingCurve.Type.InQuad)
            self.fade_anim.start()

    @pyqtSlot(int)
    def fade_out_fast(self, duration=240):
        self._bgm_watchdog_timer.stop()
        self._cancel_fades()
        fade_dur = max(180, int(duration)) if duration else 240

        for players in list(self.console_players.values()):
            for sound_type, player in list(players.items()):
                if player and (player.isPlaying() or getattr(player, "_play_on_ready", False)):
                    if sound_type == "Test":
                        continue
                    self._fade_out_player(player, duration_ms=fade_dur)

    @pyqtSlot(str)
    def play_boot(self, console):
        target = self._normalize_console(console)
        if self.current_sequence == "DOWNLOADING" and not self.is_stopped and self.active_console == target:
            running_p = self.console_players.get(target, {}).get("Running")
            start_p = self.console_players.get(target, {}).get("Start")
            if (running_p and running_p.isPlaying()) or (start_p and start_p.isPlaying()):
                return

        self._bgm_watchdog_timer.stop()
        s_key = "Startup" if target == "TriCore" else "Boot"
        existing = self.console_players.get(target, {}).get(s_key)

        if (
            existing is not None
            and (existing.isPlaying() or getattr(existing, "_play_on_ready", False))
            and not getattr(existing, "_fading_out", False)
        ):
            self.active_console = target
            self.is_stopped = False
            self.current_sequence = "BOOT"
            return

        self.switch_console(target)
        self.is_stopped = False
        self.current_sequence = "BOOT"
        if self.global_volume <= 0.0:
            return
        player = self._get_player(self.active_console, s_key)
        if player:
            self._force_play(player, fade_others_ms=220)

    @pyqtSlot(str)
    def play_console_click(self, console):
        target = self._normalize_console(console)
        if self.current_sequence == "DOWNLOADING" and not self.is_stopped and self.active_console == target:
            running_p = self.console_players.get(target, {}).get("Running")
            start_p = self.console_players.get(target, {}).get("Start")
            if (running_p and running_p.isPlaying()) or (start_p and start_p.isPlaying()):
                return

        self._bgm_watchdog_timer.stop()
        self.switch_console(target)
        self.is_stopped = False
        self.current_sequence = "CLICK"
        if self.global_volume <= 0.0:
            return
        player = self._get_player(self.active_console, "Click")
        if player:
            self._force_play(player, fade_others_ms=180)

    @pyqtSlot(str)
    def play_start_sequence(self, console):
        self.switch_console(console)
        self._stop_all_audio_only(force_all=False, smooth=False)
        self.is_stopped = False
        self.current_sequence = "DOWNLOADING"
        self._start_wait_retries = 0
        self._bgm_watchdog_timer.start()

        if self.global_volume <= 0.0:
            return

        player_start = self._get_player(self.active_console, "Start")
        running = self._get_player(self.active_console, "Running")
        if running:
            self._cancel_player_fade(running)

        if not player_start or not getattr(player_start, "_file_path", None):
            player_start = self._get_player(self.active_console, "Click")

        if not player_start or not getattr(player_start, "_file_path", None):
            if running:
                self._force_play(running, is_bgm=True, fade_others_ms=0)
                self._schedule_running_fade(running)
        else:
            self._force_play(player_start, fade_others_ms=0)
            self.start_fallback_timer.start(1500)

    @pyqtSlot(str, bool)
    def play_result(self, console, success):
        self._bgm_watchdog_timer.stop()
        self.switch_console(console)
        self._stop_all_audio_only(force_all=False, smooth=False)
        self.is_stopped = False
        self.current_sequence = "RESULT"

        if self.global_volume <= 0.0:
            return

        state = "Succes" if success else "Fail"
        player_result = self._get_player(self.active_console, state)
        if not player_result or not getattr(player_result, "_file_path", None):
            player_result = self._get_player(self.active_console, "Success" if success else "Error")
        if player_result:
            self._force_play(player_result, fade_others_ms=0)

    @pyqtSlot(str)
    def play_stop(self, console):
        self._bgm_watchdog_timer.stop()
        self.switch_console(console)
        self._stop_all_audio_only(force_all=False, smooth=False)
        self.is_stopped = False
        self.current_sequence = "STOP"

        if self.global_volume <= 0.0:
            return

        player_stop = self._get_player(self.active_console, "STOP")
        if not player_stop or not getattr(player_result_or_stop := player_stop, "_file_path", None):
            player_stop = self._get_player(self.active_console, "Stop")
        if player_stop:
            self._force_play(player_stop, fade_others_ms=0)

    @pyqtSlot()
    def play_test_sound(self):
        if self.global_volume <= 0.0:
            return
        now = time.monotonic()
        existing = self.console_players.get("TriCore", {}).get("Test")
        if existing and existing.isPlaying() and (now - getattr(existing, "_last_play_ts", 0.0)) < 0.08:
            return
        player_test = self._get_player("TriCore", "Test", "Test.wav")
        if player_test:
            self._force_play(player_test, stop_others=False)

    def _stop_all_audio_only(self, force_all=False, smooth=True):
        self._cancel_fades()
        self._is_transitioning = True
        try:
            for _, players in list(self.console_players.items()):
                for sound_type, player in list(players.items()):
                    if player:
                        if not force_all and sound_type == "Test":
                            continue
                        if (
                            smooth
                            and not force_all
                            and player.isPlaying()
                            and getattr(player, "_is_bgm", False)
                            and self.global_volume > 0.0
                        ):
                            self._fade_out_player(player, duration_ms=220)
                        else:
                            self._cancel_player_fade(player)
                            self._stop_player(player)
        finally:
            self._is_transitioning = False
        self.set_master_fade(1.0)
        self.set_bgm_fade(1.0)

    @pyqtSlot()
    def stop_all(self):
        self._bgm_watchdog_timer.stop()
        self.is_stopped = True
        self.current_sequence = "IDLE"
        self._stop_all_audio_only(force_all=False, smooth=True)

    def cleanup(self):
        self._bgm_watchdog_timer.stop()
        self._cancel_fades()
        if self._player_fade_timer.isActive():
            self._player_fade_timer.stop()
        self._fading_players.clear()
        self._stop_all_audio_only(force_all=True, smooth=False)
        for players in self.console_players.values():
            for player in list(players.values()):
                self._cleanup_player(player)
        self.console_players.clear()
        self._files_index.clear()
