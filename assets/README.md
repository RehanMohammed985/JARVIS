Place a short **clean** reference clip here as `jarvis_reference.wav` (mono or stereo
WAV, 5–15 seconds) if you enable **Coqui XTTS**. The clip should isolate the voice
you want to mimic. For **RVC**, train or obtain a `.pth`/`.index` pair and point the
backend environment variables to your inference CLI.

> Licensing note: do not distribute copyrighted film audio. Record an original
> performance “in the style of” a polished British AI valet, or use royalty-free
> voice talent.

If the file is absent, the backend still runs: `macos_say` uses the **Daniel** voice
as a reasonable on-device stand-in while you iterate on cloning quality.
