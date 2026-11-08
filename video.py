"""Diapositivas, narración en español y montaje MP4 con ffmpeg."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from historia.analyze import fold
from historia.errors import HistoriaError
from historia.script import Slide, parse_markdown

WIDTH = 1280
HEIGHT = 720
VOICE = "es-ES-AlvaroNeural"
PALETTES = (
    ((246, 240, 230), (226, 205, 176), (122, 31, 43)),
    ((236, 242, 246), (208, 222, 232), (27, 67, 99)),
    ((240, 244, 236), (214, 228, 206), (47, 90, 58)),
    ((245, 238, 232), (228, 208, 190), (128, 74, 32)),
    ((242, 236, 240), (224, 208, 216), (102, 42, 74)),
)
REGULAR_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/croscore/Arimo-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
BOLD_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/croscore/Arimo-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


@dataclass
class VideoResult:
    path: Path
    engine: str
    warnings: list[str]


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    raise HistoriaError(
        "No se encontró ffmpeg en el sistema, así que no puedo montar el vídeo. "
        "Instálalo y vuelve a intentarlo.\n"
        "• Linux: sudo apt install ffmpeg\n"
        "• macOS: brew install ffmpeg\n"
        "• Windows: winget install Gyan.FFmpeg"
    )


def run_ffmpeg(args: list[str]) -> None:
    require_ffmpeg()
    process = subprocess.run(args, capture_output=True, text=True)
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        raise HistoriaError(f"ffmpeg falló al crear el vídeo. Detalle: {detail[-800:]}")


def probe_streams(path: str | Path) -> list[dict]:
    require_ffmpeg()
    raw = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        text=True,
    )
    payload = json.loads(raw)
    return payload.get("streams", [])


def _frame_duration(seconds: float) -> float:
    frames = max(15, int(round(seconds * 30)))
    return frames / 30.0


def probe_duration(path: str | Path) -> float:
    require_ffmpeg()
    raw = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        text=True,
    ).strip()
    try:
        return max(float(raw), 0.4)
    except ValueError as exc:
        raise HistoriaError(f"No se pudo medir la duración del audio ({raw!r}).") from exc


def _find_font(candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def load_font_paths() -> tuple[str, str]:
    regular_path = _find_font(REGULAR_FONTS)
    if not regular_path:
        raise HistoriaError(
            "No encontré una fuente TrueType (DejaVu, Liberation, Noto o Arial). "
            "En Linux puedes instalarla con: sudo apt install fonts-dejavu-core"
        )
    bold_path = _find_font(BOLD_FONTS) or regular_path
    return regular_path, bold_path


def _font(path_kind: str, size: int) -> ImageFont.FreeTypeFont:
    regular_path, bold_path = load_font_paths()
    source = bold_path if path_kind == "bold" else regular_path
    return ImageFont.truetype(source, size)


def vertical_gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    column = Image.new("RGB", (1, HEIGHT))
    pixels = column.load()
    for y in range(HEIGHT):
        blend = y / (HEIGHT - 1)
        pixels[0, y] = tuple(int(start + (end - start) * blend) for start, end in zip(top, bottom))
    return column.resize((WIDTH, HEIGHT), Image.Resampling.BILINEAR)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    fitted: list[str] = []
    for line in lines:
        if draw.textlength(line, font=font) <= max_width:
            fitted.append(line)
            continue
        chunk = ""
        for char in line:
            if draw.textlength(chunk + char, font=font) <= max_width:
                chunk += char
            else:
                if chunk:
                    fitted.append(chunk)
                chunk = char
        if chunk:
            fitted.append(chunk)
    return fitted


def palette_for(slide: Slide, index: int, total: int) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    heading = fold(slide.heading)
    if index == 0 or heading == "introduccion":
        return PALETTES[0]
    if index == total - 1 or heading == "conclusion":
        return PALETTES[-1]
    return PALETTES[1 + (index - 1) % (len(PALETTES) - 2)]


def render_slide(slide: Slide, index: int, total: int, doc_title: str, dest: Path) -> None:
    top, bottom, accent = palette_for(slide, index, total)
    image = vertical_gradient(top, bottom).convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    pattern = ImageDraw.Draw(overlay)
    line_color = accent + (32,)
    for start in range(-HEIGHT, WIDTH, 64):
        pattern.line([(start, 0), (start + HEIGHT, HEIGHT)], fill=line_color, width=2)
    for row in range(7):
        for col in range(5):
            cx = WIDTH - 168 + col * 24
            cy = 40 + row * 24
            pattern.ellipse((cx, cy, cx + 5, cy + 5), fill=accent + (48,))
    image = Image.alpha_composite(image, overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 22, HEIGHT), fill=accent)
    draw.rectangle((0, HEIGHT - 68, WIDTH, HEIGHT), fill=accent)

    kicker_font = _font("regular", 22)
    title_font = _font("bold", 46)
    body_font = _font("regular", 30)
    footer_font = _font("regular", 22)
    max_width = WIDTH - 120
    kicker = doc_title if len(doc_title) <= 70 else doc_title[:67].rstrip() + "…"
    draw.text((56, 36), kicker, font=kicker_font, fill=accent)
    title_lines = wrap_text(draw, slide.heading, title_font, max_width)[:2]
    y = 78
    for line in title_lines:
        draw.text((56, y), line, font=title_font, fill=(31, 41, 51))
        y += 56
    draw.line((56, y + 8, 420, y + 8), fill=accent, width=4)
    y += 36
    footer_top = HEIGHT - 84
    for bullet in slide.bullets[:5]:
        lines = wrap_text(draw, bullet, body_font, max_width - 36)[:3]
        if y + 34 * len(lines) > footer_top:
            break
        draw.rounded_rectangle((56, y + 10, 74, y + 28), radius=3, fill=accent)
        for line_index, line in enumerate(lines):
            draw.text((88, y), line, font=body_font, fill=(31, 41, 51))
            y += 38
        y += 14
    footer = f"historia_app    ·    lección de historia    ·    {index + 1}/{total}"
    draw.text((56, HEIGHT - 46), footer, font=footer_font, fill=(255, 250, 244))
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="PNG")


def clean_speech(text: str) -> str:
    text = text.replace("____", "espacio en blanco")
    text = re.sub(r"[#*_`>|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def trim_speech(text: str, limit: int = 1000) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    if "." in cut[200:]:
        cut = cut.rsplit(".", 1)[0] + "."
    return cut, True


def split_for_speech(text: str, limit: int = 450) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[\.!\?…])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > limit:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(sentence), limit):
                chunks.append(sentence[start : start + limit])
            continue
        trial = f"{current} {sentence}".strip()
        if len(trial) <= limit:
            current = trial
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _run_async(coro) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    box: dict[str, Exception] = {}

    def worker() -> None:
        try:
            asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    import threading

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]


def _write_gtts(text: str, dest: Path) -> None:
    from gtts import gTTS

    try:
        speaker = gTTS(text=text, lang="es", slow=False, timeout=40)
    except TypeError:
        speaker = gTTS(text=text, lang="es", slow=False)
    speaker.save(str(dest))


def _write_edge(text: str, dest: Path) -> None:
    import edge_tts

    async def run() -> None:
        communicate = edge_tts.Communicate(text, voice=VOICE)
        await communicate.save(str(dest))

    _run_async(run())


def _concat_audio(parts: list[Path], dest: Path) -> None:
    list_file = dest.with_suffix(".concat.txt")
    list_file.write_text("\n".join(_concat_line(path) for path in parts) + "\n", encoding="utf-8")
    try:
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c:a",
                "libmp3lame",
                "-q:a",
                "4",
                str(dest),
            ]
        )
    finally:
        list_file.unlink(missing_ok=True)


def _synthesize_with(engine: str, text: str, dest: Path) -> Path:
    dest = dest.with_suffix(".mp3")
    chunks = split_for_speech(text)
    if not chunks:
        raise RuntimeError("el texto de la narración está vacío")
    writer = _write_edge if engine == "edge" else _write_gtts
    if len(chunks) == 1:
        writer(chunks[0], dest)
    else:
        parts: list[Path] = []
        for index, chunk in enumerate(chunks):
            part = dest.with_name(f"{dest.stem}_parte{index}.mp3")
            writer(chunk, part)
            parts.append(part)
        _concat_audio(parts, dest)
    if not dest.exists() or dest.stat().st_size < 200:
        raise RuntimeError("el audio generado está vacío")
    return dest


def synthesize_speech(text: str, dest: Path, engine: str) -> tuple[Path, str, list[str]]:
    """Narración en español. Si se elige edge-tts y falla, se usa gTTS, y al revés."""
    preferred = "edge" if engine == "edge" else "gtts"
    order = ["edge", "gtts"] if preferred == "edge" else ["gtts", "edge"]
    errors: list[str] = []
    for name in order:
        try:
            path = _synthesize_with(name, text, dest)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            continue
        warnings = []
        if name != preferred:
            label = "edge-tts (es-ES-AlvaroNeural)" if name == "edge" else "gTTS"
            warnings.append(f"La voz elegida no respondió. La narración se generó con {label}.")
        return path, name, warnings
    detail = " | ".join(errors)[-500:]
    raise HistoriaError(
        "No se pudo crear la narración en español. gTTS y edge-tts necesitan internet "
        f"para hablar. Detalle: {detail}"
    )


def render_segment(image: Path, audio: Path, dest: Path, duration: float) -> None:
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(image),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            "scale=1280:720:flags=lanczos,format=yuv420p",
            "-c:v",
            "libx264",
            "-profile:v",
            "main",
            "-level",
            "3.1",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-af",
            "apad=pad_dur=2",
            "-t",
            f"{duration:.3f}",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )


def _concat_line(path: Path) -> str:
    escaped = path.as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def concat_segments(segments: list[Path], dest: Path) -> None:
    list_file = dest.with_suffix(".concat.txt")
    list_file.write_text("\n".join(_concat_line(path) for path in segments) + "\n", encoding="utf-8")
    copy_cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    reencode_cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:v",
        "libx264",
        "-profile:v",
        "main",
        "-level",
        "3.1",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    try:
        try:
            run_ffmpeg(copy_cmd)
        except HistoriaError:
            run_ffmpeg(reencode_cmd)
    finally:
        list_file.unlink(missing_ok=True)


def verify_output(path: Path) -> None:
    streams = probe_streams(path)
    kinds = {stream.get("codec_type") for stream in streams}
    if "video" not in kinds or "audio" not in kinds:
        raise HistoriaError(
            "El archivo se creó, pero no contiene a la vez vídeo y audio. Revisa ffmpeg."
        )
    video = next(stream for stream in streams if stream.get("codec_type") == "video")
    audio = next(stream for stream in streams if stream.get("codec_type") == "audio")
    if video.get("codec_name") != "h264":
        raise HistoriaError("El vídeo no quedó codificado con libx264 (h264).")
    if audio.get("codec_name") != "aac":
        raise HistoriaError("El audio no quedó codificado en AAC.")
    if video.get("pix_fmt") not in {None, "yuv420p"}:
        raise HistoriaError(f"El vídeo no está en yuv420p (se obtuvo {video.get('pix_fmt')}).")


def _report(progress, fraction: float, message: str) -> None:
    if progress is not None:
        progress(max(0.0, min(fraction, 1.0)), message)


def generate_video(
    markdown: str,
    output: str | Path,
    engine: str = "gtts",
    progress=None,
    synth=None,
) -> VideoResult:
    require_ffmpeg()
    _title, slides = parse_markdown(markdown or "")
    slides = [slide for slide in slides if clean_speech(slide.narration)]
    if not slides:
        raise HistoriaError("El guion no tiene texto para narrar. Escribe algo en la pestaña del guion.")
    warnings: list[str] = []
    if len(slides) > 6:
        warnings.append(
            "El guion es largo: el vídeo incluye solo 6 secciones para que quepa en un alojamiento gratuito."
        )
        slides = slides[:6]
    synth = synth or synthesize_speech
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".partial.mp4")
    engine_used = "edge" if engine == "edge" else "gtts"
    trimmed = False
    with tempfile.TemporaryDirectory(prefix="historia_video_") as tmp_name:
        tmp = Path(tmp_name)
        segments: list[Path] = []
        total = len(slides)
        for index, slide in enumerate(slides):
            _report(progress, index / total * 0.9, f"Diapositiva {index + 1} de {total}")
            image_path = tmp / f"slide_{index:02d}.png"
            render_slide(slide, index, total, _title, image_path)
            speech, was_trimmed = trim_speech(clean_speech(slide.narration))
            trimmed = trimmed or was_trimmed
            audio_path, used, synth_warnings = synth(speech, tmp / f"audio_{index:02d}.mp3", engine)
            engine_used = used
            warnings.extend(synth_warnings)
            duration = _frame_duration(probe_duration(audio_path) + 0.45)
            segment = tmp / f"segment_{index:02d}.mp4"
            render_segment(image_path, audio_path, segment, duration)
            segments.append(segment)
        if trimmed:
            warnings.append("Alguna narración era muy larga y se recortó para el vídeo.")
        _report(progress, 0.94, "Uniendo las escenas")
        concat_segments(segments, partial)
    partial.replace(destination)
    verify_output(destination)
    _report(progress, 1.0, "Vídeo listo")
    unique_warnings: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        if warning not in seen:
            seen.add(warning)
            unique_warnings.append(warning)
    return VideoResult(path=destination, engine=engine_used, warnings=unique_warnings)
