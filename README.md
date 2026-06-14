# chuja

Separate a song into its stems — **vocals, drums, bass, other** — from a local
audio file, or (opt-in) from a YouTube / SoundCloud / direct URL. One command,
portable output, cross-platform.

![chuja mixing console](docs/03-console.png)

> *The `chuja serve` mixing console — one channel strip per stem with a live
> waveform, solo/mute, faders, and sample-accurate synced playback.*

`chuja` is a thin, friendly wrapper around two excellent open-source engines:

- **[Demucs](https://github.com/facebookresearch/demucs)** (Meta) — state-of-the-art neural source separation.
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** — used *only* for the optional URL-fetching feature.

It does not reinvent either. What it adds is the glue: one pipeline from a
source to clean, named, downloadable stem files, with sensible defaults and a
polished CLI + Python API.

---

## Screenshots

**Intake** — drop a file or paste a URL, pick a model / format / split:

![chuja intake screen](docs/01-intake.png)

**Progress** — a real, per-chunk separation progress bar (not a fake spinner):

![chuja separation progress](docs/02-progress.png)

**Console** — the per-stem mixing board shown at the top of this README.

---

## Install

Install from source (not yet published to PyPI):

```bash
git clone https://github.com/dnakitare/chuja
cd chuja

# Core: separate LOCAL files. Pulls in Demucs (PyTorch).
pip install .

# Optional: add URL ingestion (YouTube/SoundCloud/etc.)
pip install '.[url]'
```

### Install globally (run `chuja` from anywhere)

```bash
./install.sh
```

If this project already has a `.venv`, the installer just symlinks its `chuja`
onto your PATH (`~/.local/bin` by default) — instant, nothing re-downloaded.
With no `.venv`, it falls back to an isolated [pipx](https://pipx.pypa.io)
install. Override the link location with `CHUJA_BIN=/usr/local/bin ./install.sh`.

Prefer to do it by hand? `pipx install '.[url]'` from the project root, or
`pip install --user '.[url]'`.

### Requirements

Requires **Python 3.9+** and **ffmpeg** on your PATH:

| Platform | Install ffmpeg |
| --- | --- |
| macOS | `brew install ffmpeg` |
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| Windows | `winget install Gyan.FFmpeg` |

> The first separation downloads the model weights (~150 MB) once and caches them.

## Usage (CLI)

```bash
# Local file → 4 stems as WAV under ./stems/<track>/
chuja separate song.mp3

# Pick a format and bundle into a portable zip
chuja separate song.flac --format mp3 --zip -o ~/Desktop/stems

# Karaoke / acapella split: one stem + everything else
chuja separate song.mp3 --two-stems vocals

# From a URL (requires the [url] extra)
chuja separate "https://www.youtube.com/watch?v=..." --format mp3

# Best-quality (slower) model, force a device
chuja separate song.wav --model htdemucs_ft --device cpu

# List available models
chuja models
```

## Usage (library)

```python
import chuja

result = chuja.separate(
    "song.mp3",
    out_dir="stems",
    fmt="mp3",
    two_stems=None,        # or "vocals" for a 2-stem split
    zip_output=True,
)
print(result.track)        # "song"
print(result.stems)        # {"vocals": Path(...), "drums": Path(...), ...}
print(result.archive)      # Path("stems/song.zip")
```

## Models

| Model | Stems | Notes |
| --- | --- | --- |
| `htdemucs` *(default)* | 4 | Best balance of speed and quality |
| `htdemucs_ft` | 4 | Fine-tuned — best quality, ~4× slower |
| `htdemucs_6s` | 6 | Adds piano + guitar (experimental) |
| `mdx_extra` | 4 | Alternative MDX-challenge model |

## A note on quality

Separation quality is bounded by your **source** quality. Demucs is excellent,
but it cannot recover information that lossy compression already discarded — a
128 kbps MP3 in means audible artifacts in the stems out. Feed it the highest-
fidelity source you have (WAV/FLAC > 320 kbps MP3 > a low-bitrate stream) for
the cleanest results. `chuja` deliberately does **not** transcode before
separation, so it never throws away quality you started with.

Performance: separation is compute-heavy. It runs on CPU everywhere, and uses
your GPU automatically when available — **CUDA** (NVIDIA) or **MPS** (Apple
Silicon). GPU is many times faster than CPU for full songs.

## Responsible use

The optional URL feature uses `yt-dlp`. Downloading content from YouTube,
SoundCloud, and similar platforms may violate their Terms of Service, and the
audio is almost always copyrighted. **You are solely responsible** for ensuring
you have the right to download and process any audio you give to `chuja`
(e.g. your own recordings, public-domain works, or content you are licensed to
use). The core install ships *without* this capability for exactly this reason.

## License

MIT.
