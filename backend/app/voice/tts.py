from __future__ import annotations

import subprocess
from pathlib import Path

from app.config import settings


def _is_riff_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


class TextToSpeech:
    """Local TTS with optional RVC post-processing. Fallback: macOS `say` (British voice)."""

    def synth(
        self,
        text: str,
        out_path: Path,
        reference_wav: Path | None = None,
    ) -> Path:
        out_path = out_path.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        engine = settings.tts_engine
        if engine == "none":
            out_path.write_bytes(b"")
            return out_path
        if engine == "macos_say":
            import platform as pf
            import shutil

            raw_aiff = out_path.with_suffix(".aiff")
            voice = "Daniel"
            # Short utterances still need valid audio; escape not needed — subprocess list form.
            r = subprocess.run(
                ["say", "-v", voice, "-r", "220", "-o", str(raw_aiff), text[:5000]],
                check=False,
                capture_output=True,
            )
            if r.returncode != 0 or not raw_aiff.is_file():
                out_path.write_bytes(b"")
                return out_path
            if shutil.which("ffmpeg"):
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(raw_aiff),
                        "-acodec",
                        "pcm_s16le",
                        str(out_path),
                    ],
                    check=False,
                    capture_output=True,
                )
                raw_aiff.unlink(missing_ok=True)
            elif pf.system() == "Darwin" and shutil.which("afconvert"):
                subprocess.run(
                    ["afconvert", "-f", "WAVE", "-d", "LEI16", str(raw_aiff), str(out_path)],
                    check=False,
                    capture_output=True,
                )
                raw_aiff.unlink(missing_ok=True)
            else:
                raw_aiff.replace(out_path)
            if not out_path.is_file() or out_path.stat().st_size < 64:
                out_path.write_bytes(b"")
                return out_path
            if not _is_riff_wav(out_path.read_bytes()[:64]):
                out_path.write_bytes(b"")
                return out_path
            return self._maybe_rvc(out_path, reference_wav)
        if engine == "coqui":
            return self._coqui_xtts(text, out_path, reference_wav)
        if engine == "cli_rvc":
            return self._maybe_rvc(out_path, reference_wav)
        raise ValueError(f"Unknown TTS engine: {engine}")

    def _coqui_xtts(self, text: str, out_path: Path, ref: Path | None) -> Path:
        try:
            from TTS.api import TTS
        except ImportError as e:
            raise RuntimeError(
                "Coqui TTS not installed. Uncomment TTS in backend/requirements.txt.",
            ) from e
        device = "cpu"
        try:
            import torch

            if torch.cuda.is_available():
                device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                device = "mps"
        except Exception:
            pass
        tts = TTS(settings.coqui_model_name).to(device)
        ref_wav = str(ref) if ref and ref.is_file() else None
        if not ref_wav:
            raise RuntimeError("XTTS requires a reference speaker WAV for Jarvis cloning.")
        tts.tts_to_file(text=text, file_path=str(out_path), speaker_wav=ref_wav)
        return self._maybe_rvc(out_path, ref)

    def _maybe_rvc(self, wav: Path, _ref: Path | None) -> Path:
        cli = settings.rvc_cli_path
        model = settings.rvc_model_path
        if not cli or not model or not cli.is_file():
            return wav
        out = wav.with_suffix(".jarvis.wav")
        cmd = [
            str(cli),
            "--input",
            str(wav),
            "--model",
            str(model),
            "--output",
            str(out),
        ]
        idx = settings.rvc_index_path
        if idx and idx.is_file():
            cmd.extend(["--index", str(idx)])
        subprocess.run(cmd, check=False, capture_output=True)
        return out if out.is_file() else wav


_tts: TextToSpeech | None = None


def get_tts() -> TextToSpeech:
    global _tts
    if _tts is None:
        _tts = TextToSpeech()
    return _tts
