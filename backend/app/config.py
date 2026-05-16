import platform
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    **Filesystem / Finder:** Designed for the FastAPI process running **natively on macOS**.
    When ``running_in_docker`` is true, ``Path.home()`` and disk tools refer to the container,
    not the user's Mac, unless paths are explicitly bind-mounted.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Jarvis"
    debug: bool = False

    # Ollama
    ollama_base_url: str = "http://127.0.0.1:11434"
    # Prefer a non-reasoning chat model; DeepSeek-R1 etc. leak thinking into replies via some APIs.
    ollama_model: str = "llama3.2:latest"

    # Memory
    chroma_path: Path = Field(default_factory=lambda: Path("./data/chroma"))
    memory_collection: str = "jarvis_memory"

    # Security — comma-separated allowed root directories (merged with home + repo + cwd defaults)
    allowed_roots: str = Field(
        default="",
        validation_alias=AliasChoices("JARVIS_ALLOWED_ROOTS", "ALLOWED_ROOTS"),
    )

    # Terminal allowlist — comma-separated prefixes (empty = deny all shell)
    terminal_allow_prefixes: str = Field(
        default="ls,git status,git diff,pwd,echo,which,python --version,node --version",
        validation_alias=AliasChoices(
            "JARVIS_TERMINAL_ALLOW_PREFIXES",
            "TERMINAL_ALLOW_PREFIXES",
        ),
    )

    # Voice
    whisper_model_size: str = Field(
        default="tiny",
        validation_alias=AliasChoices("JARVIS_WHISPER_MODEL_SIZE", "WHISPER_MODEL_SIZE"),
    )
    whisper_device: Literal["cpu", "cuda", "auto"] = Field(
        default="auto",
        validation_alias=AliasChoices("JARVIS_WHISPER_DEVICE", "WHISPER_DEVICE"),
    )
    tts_engine: Literal["coqui", "cli_rvc", "macos_say", "none"] = Field(
        default="macos_say",
        validation_alias=AliasChoices("JARVIS_TTS_ENGINE", "TTS_ENGINE"),
    )
    coqui_model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    rvc_cli_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("JARVIS_RVC_CLI_PATH", "RVC_CLI_PATH"),
    )
    rvc_model_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("JARVIS_RVC_MODEL_PATH", "RVC_MODEL_PATH"),
    )
    rvc_index_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("JARVIS_RVC_INDEX_PATH", "RVC_INDEX_PATH"),
    )

    # Optional cloud TTS fallback (only if local quality insufficient)
    elevenlabs_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ELEVENLABS_API_KEY", "JARVIS_ELEVENLABS_API_KEY"),
    )

    wake_word: str = Field(
        default="jarvis",
        validation_alias=AliasChoices("JARVIS_WAKE_WORD", "WAKE_WORD"),
    )
    porcupine_access_key: str | None = None
    porcupine_keyword_path: Path | None = None

    # Voice UX: speak in the browser as soon as text arrives (skip server TTS + WAV hop).
    voice_client_tts: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "JARVIS_VOICE_CLIENT_TTS",
            "VOICE_CLIENT_TTS",
        ),
    )

    # open/show_in_finder: server = API runs macOS `open` (bare Mac only). client = browser calls local bridge.
    # auto = delegate when API is in Docker or not running on Darwin unless forced otherwise.
    file_actions_mode: Literal["auto", "server", "client"] = Field(
        default="auto",
        validation_alias=AliasChoices(
            "JARVIS_FILE_ACTIONS_MODE",
            "FILE_ACTIONS_MODE",
        ),
    )
    force_client_file_actions: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "JARVIS_FORCE_CLIENT_FILE_ACTIONS",
            "FORCE_CLIENT_FILE_ACTIONS",
        ),
    )

    # Modular macOS Finder search (opt-in; never uses unlimited disk — see file_search_tool.py).
    mac_finder_roots: str = Field(
        default="",
        validation_alias=AliasChoices("JARVIS_MAC_FINDER_ROOTS"),
    )
    mac_finder_preset: str = Field(
        default="off",
        validation_alias=AliasChoices("JARVIS_MAC_FINDER_PRESET"),
    )

    @field_validator("chroma_path", mode="before")
    @classmethod
    def expand_chroma(cls, v: str | Path) -> Path:
        return Path(v).expanduser().resolve()

    @property
    def running_in_docker(self) -> bool:
        return Path("/.dockerenv").is_file()

    @property
    def full_filesystem_access(self) -> bool:
        """Unrestricted *local* paths when sandbox env is left unset (desktop only).

        In Docker or when JARVIS_ALLOWED_ROOTS is set, this is off so containers stay contained
        and explicit roots are honored.
        """
        if self.allowed_roots.strip():
            return False
        if self.running_in_docker:
            return False
        return platform.system() in ("Darwin", "Linux")

    @property
    def allowed_root_paths(self) -> list[Path]:
        """Filesystem sandbox roots (deduped).

        If JARVIS_ALLOWED_ROOTS is unset: home + repo root + process cwd (covers dev layout).
        If set: only those paths (strict).
        """
        roots: list[Path] = []
        raw = [p.strip() for p in self.allowed_roots.split(",") if p.strip()]
        if raw:
            roots.extend(Path(p).expanduser().resolve() for p in raw)
        else:
            roots.append(Path.home().resolve())
            candidate = Path(__file__).resolve().parents[2]
            if (candidate / "backend").is_dir():
                roots.append(candidate)
            try:
                roots.append(Path.cwd().resolve())
            except OSError:
                pass
        seen: set[str] = set()
        out: list[Path] = []
        for r in roots:
            key = str(r)
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    @property
    def filesystem_walk_roots(self) -> list[Path]:
        """Roots for bounded keyword search (os.walk). Never the whole filesystem tree."""
        if self.allowed_roots.strip():
            return list(self.allowed_root_paths)
        if not self.full_filesystem_access:
            return list(self.allowed_root_paths)
        roots: list[Path] = []
        seen: set[str] = set()

        def add(p: Path) -> None:
            try:
                r = p.resolve()
            except OSError:
                return
            if not r.is_dir():
                return
            k = str(r)
            if k in seen:
                return
            seen.add(k)
            roots.append(r)

        home = Path.home()
        add(home)
        sys = platform.system()
        if sys == "Darwin":
            add(Path("/Volumes"))
            add(Path("/Users"))
            # iCloud Drive + common project/document roots for broad search
            add(home / "Library/Mobile Documents/com~apple~CloudDocs")
            for rel in (
                "Desktop",
                "Documents",
                "Downloads",
                "Projects",
                "Developer",
                "dev",
                "Code",
                "workspace",
            ):
                add(home / rel)
            add(home / "Documents/GitHub")
        elif sys == "Linux":
            add(Path("/mnt"))
            add(Path("/media"))
        if not roots:
            add(Path.cwd())
        return roots


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
