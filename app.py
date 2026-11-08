"""historia_app: lección de historia en español, vídeo y examen en inglés."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# --- Compatibilidad: funciona aunque los archivos de "historia/" esten sueltos en la raiz ---
import os as _os, sys as _sys, types as _types
_root = _os.path.dirname(_os.path.abspath(__file__))
if not _os.path.isdir(_os.path.join(_root, "historia")) and "historia" not in _sys.modules:
    _pkg = _types.ModuleType("historia")
    _pkg.__path__ = [_root]
    _sys.modules["historia"] = _pkg
    _init = _os.path.join(_root, "__init__.py")
    if _os.path.exists(_init):
        exec(compile(open(_init, encoding="utf-8").read(), _init, "exec"), _pkg.__dict__)
# --------------------------------------------------------------------------------------
from historia import __version__
from historia.analyze import analyze
from historia.errors import HistoriaError
from historia.extract import extract_bytes
from historia.llm import ocr_with_vision
from historia.ocr import IMAGE_SUFFIXES, MAX_PHOTOS, ocr_tesseract_many, tesseract_status
from historia.script import parse_markdown
from historia.service import generate_exam, generate_script, grade_answers
from historia.settings import GenerationSettings
from historia.video import generate_video

ROOT = Path(__file__).resolve().parent
EXAMPLE = ROOT / "ejemplo_tema.txt"
OUTPUT = Path(tempfile.gettempdir()) / "historia_app"
OUTPUT.mkdir(parents=True, exist_ok=True)

STATUS_LABELS = {
    "correct": "Correct",
    "partial": "Partial credit",
    "incorrect": "Incorrect",
    "unanswered": "Not answered",
}


def read_secret(name: str) -> str:
    """Lee un secreto de Streamlit Community Cloud y, si no existe, la variable de entorno."""
    try:
        if name in st.secrets:
            value = st.secrets[name]
            if value:
                return str(value).strip()
    except Exception:
        pass
    return os.environ.get(name, "").strip()


def init_state() -> None:
    if "source_text" not in st.session_state:
        st.session_state.source_text = ""
    if "script_md" not in st.session_state:
        st.session_state.script_md = ""
    if "mode_label" not in st.session_state:
        st.session_state.mode_label = "Sin conexión (reglas)"
    if "tts_label" not in st.session_state:
        st.session_state.tts_label = "gTTS (español)"
    if "ocr_mode" not in st.session_state:
        st.session_state.ocr_mode = "Tesseract (español)"
    if "api_key" not in st.session_state:
        st.session_state.api_key = read_secret("OPENAI_API_KEY")
    if "base_url" not in st.session_state:
        st.session_state.base_url = read_secret("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    if "model_name" not in st.session_state:
        st.session_state.model_name = read_secret("OPENAI_MODEL") or "gpt-4o-mini"
    defaults = {
        "source_name": "",
        "script_mode": "",
        "script_warnings": [],
        "video_path": "",
        "video_engine": "",
        "video_warnings": [],
        "exam": None,
        "exam_warnings": [],
        "exam_token": 0,
        "grade": None,
        "ocr_note": "",
        "ocr_warnings": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def current_settings() -> GenerationSettings:
    tts = st.session_state.get("tts_label", "gTTS (español)")
    return GenerationSettings(
        use_llm=str(st.session_state.get("mode_label", "")).startswith("Modelo"),
        api_key=st.session_state.get("api_key", ""),
        base_url=st.session_state.get("base_url", ""),
        model=st.session_state.get("model_name", ""),
        tts_engine="edge" if "edge" in str(tts) else "gtts",
    )


def adopt_text(text: str, name: str) -> None:
    st.session_state.source_text = text
    st.session_state.source_name = name
    st.session_state.script_md = ""
    st.session_state.script_mode = ""
    st.session_state.script_warnings = []
    st.session_state.video_path = ""
    st.session_state.video_engine = ""
    st.session_state.video_warnings = []
    st.session_state.exam = None
    st.session_state.exam_warnings = []
    st.session_state.grade = None
    st.session_state.exam_token = int(st.session_state.get("exam_token", 0)) + 1
    st.session_state.ocr_note = ""
    st.session_state.ocr_warnings = []


def enable_inline_playback() -> None:
    """Safari en el iPad no reproduce el vídeo dentro de la página si falta playsinline."""
    components.html(
        """
        <script>
        const mark = () => {
          const doc = window.parent.document;
          doc.querySelectorAll("video").forEach((node) => {
            node.setAttribute("playsinline", "");
            node.setAttribute("webkit-playsinline", "");
            node.playsInline = true;
          });
        };
        mark();
        setTimeout(mark, 500);
        </script>
        """,
        height=0,
    )


def fmt_points(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.1f}"


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.4rem; max-width: 1080px;}
        h1 {letter-spacing: -0.03em; margin-bottom: 0.2rem;}
        div[data-testid="stMetric"] {
            background: #fffdf8;
            border: 1px solid #eadfce;
            padding: 0.55rem 0.75rem;
            border-radius: 12px;
        }
        div.stButton > button,
        div.stDownloadButton > button,
        div.stFormSubmitButton > button {
            min-height: 3rem;
            font-size: 1.05rem;
        }
        textarea, input, select {
            font-size: 16px !important;
        }
        @media (max-width: 820px) {
            .block-container {padding-left: 0.7rem; padding-right: 0.7rem;}
            div[data-testid="stHorizontalBlock"] {flex-wrap: wrap;}
            div[data-testid="column"] {min-width: 46%; flex: 1 1 46%;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    with st.sidebar:
        st.header("Configuración")
        st.radio(
            "Modo de generación",
            ["Sin conexión (reglas)", "Modelo de lenguaje (API)"],
            key="mode_label",
        )
        st.caption(
            "Sin conexión se arma todo con el propio texto. "
            "El modo con modelo usa la clave solo si la escribes o si existe OPENAI_API_KEY."
        )
        with st.expander("Modelo de lenguaje", expanded=st.session_state.mode_label.startswith("Modelo")):
            st.text_input("Clave API", type="password", key="api_key")
            st.text_input("URL base", key="base_url", help="Compatible con la API de OpenAI. Ejemplo: https://api.openai.com/v1")
            st.text_input("Modelo", key="model_name")
        st.radio(
            "Voz de la narración",
            ["gTTS (español)", "edge-tts (es-ES-AlvaroNeural)"],
            key="tts_label",
        )
        st.caption("Si edge-tts no responde, el vídeo prueba con gTTS. Las dos voces necesitan internet.")
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            st.success("ffmpeg está listo para montar el vídeo.")
        else:
            st.error("No está ffmpeg. Sin él no se puede crear el MP4. Mira el README para instalarlo.")
        st.caption(
            "La voz, la traducción, el OCR con modelo y el modo con modelo envían el contenido fuera. "
            "Tesseract y el examen local se quedan en el servidor."
        )
        st.caption(f"historia_app {__version__}")
        if st.button("Empezar de nuevo", width="stretch"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


def _photo_payloads(uploaded_files, camera) -> list[tuple[str, bytes]]:
    photos: list[tuple[str, bytes]] = []
    for item in uploaded_files or []:
        suffix = Path(item.name).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            continue
        photos.append((item.name, item.getvalue()))
    if camera is not None:
        photos.append(("camara.jpg", camera.getvalue()))
    return photos


def render_upload() -> None:
    st.subheader("Texto del tema")
    st.write(
        "Pega el tema, sube un .txt, .pdf o .docx, o haz fotos a las páginas del libro. "
        "En el iPad puedes usar la cámara. El texto queda abajo para corregir errores del OCR."
    )
    if st.button("Cargar ejemplo", width="stretch"):
        if not EXAMPLE.is_file():
            st.error("No encuentro ejemplo_tema.txt junto a la aplicación.")
        else:
            adopt_text(EXAMPLE.read_text(encoding="utf-8"), EXAMPLE.name)
            st.session_state.upload_sig = ""

    uploaded = st.file_uploader(
        "Archivo de texto, PDF o Word",
        type=["txt", "pdf", "docx"],
        help="PDF con texto seleccionable. Si el PDF es una foto, usa el apartado de imágenes.",
    )
    if uploaded is not None:
        signature = f"{uploaded.name}:{uploaded.size}"
        if st.session_state.get("upload_sig") != signature:
            try:
                adopt_text(extract_bytes(uploaded.name, uploaded.getvalue()), uploaded.name)
                st.session_state.upload_sig = signature
            except HistoriaError as exc:
                st.error(str(exc))

    st.markdown("**Fotos de páginas**")
    photo_files = st.file_uploader(
        "Varias fotos, en el orden de las páginas",
        type=["jpg", "jpeg", "png", "heic", "webp"],
        accept_multiple_files=True,
        help="jpg, png, heic o webp. Se leen en el orden en que las eliges.",
        key="photo_files",
    )
    camera = st.camera_input("O una foto con la cámara del iPad")
    st.radio(
        "Cómo leer las fotos",
        ["Tesseract (español)", "Modelo de visión (mejor, usa la clave)"],
        key="ocr_mode",
    )
    ready, tess_message = tesseract_status()
    if not ready:
        st.warning(tess_message)
    if st.button("Leer las fotos", type="primary", width="stretch"):
        photos = _photo_payloads(photo_files, camera)
        if not photos:
            st.error("Elige una o varias fotos, o haz una con la cámara.")
        else:
            extra = ""
            if len(photos) > MAX_PHOTOS:
                extra = f" Solo se leen las primeras {MAX_PHOTOS} para no saturar el servidor."
                photos = photos[:MAX_PHOTOS]
            use_vision = st.session_state.ocr_mode.startswith("Modelo")
            warnings: list[str] = []
            try:
                with st.spinner("Leyendo las fotos…"):
                    if use_vision:
                        try:
                            text = ocr_with_vision(photos, current_settings())
                            engine_name = "modelo de visión"
                        except HistoriaError as exc:
                            warnings.append(str(exc) + " Se usa Tesseract en español.")
                            text = ocr_tesseract_many(photos)
                            engine_name = "Tesseract (español)"
                    else:
                        text = ocr_tesseract_many(photos)
                        engine_name = "Tesseract (español)"
                adopt_text(text, f"{len(photos)} foto(s), {engine_name}")
                st.session_state.ocr_note = (
                    f"Texto leído con {engine_name}, en el orden de las fotos.{extra} "
                    "Corrige fechas y nombres en el recuadro antes de generar el guion."
                )
                st.session_state.ocr_warnings = warnings
            except HistoriaError as exc:
                st.error(str(exc))
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudieron leer las fotos: {exc}")
    for warning in st.session_state.get("ocr_warnings", []):
        st.warning(warning)
    if st.session_state.get("ocr_note"):
        st.caption(st.session_state.ocr_note)

    st.text_area(
        "Texto con el que se trabaja",
        key="source_text",
        height=280,
        placeholder="Pega aquí el tema o carga un archivo.",
    )
    text = st.session_state.source_text.strip()
    if st.session_state.source_name:
        st.caption(f"Fuente actual: {st.session_state.source_name}")
    if not text:
        st.info("Todavía no hay tema. Cuando haya texto, aquí verás fechas, nombres y términos detectados.")
        return
    try:
        found = analyze(text)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"No pude analizar el texto: {exc}")
        return
    metrics = st.columns(4)
    metrics[0].metric("Caracteres", f"{len(text):,}".replace(",", "."))
    metrics[1].metric("Frases", str(len(found.sentences)))
    metrics[2].metric("Fechas", str(len(found.dates)))
    metrics[3].metric("Nombres", str(len(found.names)))
    st.write("**Fechas:** " + (", ".join(found.dates[:12]) or "no se detectaron"))
    st.write("**Nombres y lugares:** " + (", ".join(found.names[:12]) or "no se detectaron"))
    st.write("**Términos frecuentes:** " + (", ".join(found.keywords[:12]) or "no se detectaron"))


def render_script() -> None:
    st.subheader("Guion en español")
    st.write(
        "El guion tiene introducción, desarrollo y conclusión. "
        "Puedes corregirlo antes de grabar el vídeo: el montaje usa este texto."
    )
    if st.button("Generar guion", type="primary", width="stretch"):
        try:
            with st.spinner("Preparando el guion…"):
                script, warnings = generate_script(st.session_state.source_text, current_settings())
            st.session_state.script_md = script.markdown
            st.session_state.script_mode = script.mode
            st.session_state.script_warnings = warnings
        except HistoriaError as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Ocurrió un problema inesperado al crear el guion: {exc}")
    for warning in st.session_state.script_warnings:
        st.warning(warning)
    if not st.session_state.script_md.strip():
        st.info("Genera el guion cuando el texto del tema esté listo.")
        return
    mode = st.session_state.script_mode or "offline"
    st.caption(f"Modo: {mode}. Edita el markdown si quieres cambiar lo que se dice en el vídeo.")
    st.text_area("Guion", key="script_md", height=460)
    _title, slides = parse_markdown(st.session_state.script_md)
    st.caption(f"Secciones que pasarán al vídeo: {len(slides)}.")
    st.download_button(
        "Descargar guion (.txt)",
        data=st.session_state.script_md,
        file_name="guion_historia.txt",
        mime="text/plain",
        key="dl_script",
        width="stretch",
    )


def render_video() -> None:
    st.subheader("Vídeo de la lección")
    st.write(
        "Cada sección del guion se convierte en una diapositiva de 1280×720 "
        "y en un fragmento de voz en español. ffmpeg une las escenas en un MP4."
    )
    settings = current_settings()
    voice = "edge-tts, es-ES-AlvaroNeural" if settings.tts_engine == "edge" else "gTTS, español"
    st.caption(f"Voz seleccionada: {voice}.")
    if st.button("Generar vídeo", type="primary", width="stretch"):
        if not st.session_state.script_md.strip():
            st.error("Primero genera o escribe un guion en la pestaña 2.")
        elif not shutil.which("ffmpeg"):
            st.error(
                "No se encontró ffmpeg. Instálalo (Linux: sudo apt install ffmpeg; "
                "macOS: brew install ffmpeg; Windows: winget install Gyan.FFmpeg) y reinicia la app."
            )
        else:
            progress = st.progress(0.0, text="Preparando el vídeo…")
            output = OUTPUT / f"leccion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

            def on_progress(fraction: float, message: str) -> None:
                progress.progress(fraction, text=message)

            try:
                result = generate_video(
                    st.session_state.script_md,
                    output,
                    engine=settings.tts_engine,
                    progress=on_progress,
                )
                st.session_state.video_path = str(result.path)
                st.session_state.video_engine = result.engine
                st.session_state.video_warnings = result.warnings
            except HistoriaError as exc:
                st.error(str(exc))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ocurrió un problema inesperado al crear el vídeo: {exc}")
            finally:
                progress.empty()
    for warning in st.session_state.video_warnings:
        st.warning(warning)
    path = Path(st.session_state.video_path) if st.session_state.video_path else None
    if path and path.is_file():
        engine = st.session_state.video_engine
        spoken = "edge-tts (es-ES-AlvaroNeural)" if engine == "edge" else "gTTS"
        st.caption(
            f"Narración usada: {spoken}. En el iPad el vídeo se reproduce aquí mismo. "
            "Descargar MP4 lo guarda en Archivos."
        )
        st.video(str(path), format="video/mp4")
        enable_inline_playback()
        st.download_button(
            "Descargar MP4",
            data=path.read_bytes(),
            file_name="leccion_historia.mp4",
            mime="video/mp4",
            key="dl_video",
            width="stretch",
        )
    else:
        st.info("El vídeo aparece aquí, con botón de descarga, cuando termine el montaje.")


def render_exam() -> None:
    st.subheader("Exam in English")
    st.write(
        "Multiple choice and short answers about the topic you loaded. "
        "Submit to see a score out of 10 and feedback on every question."
    )
    if st.button("Generate exam", type="primary", width="stretch"):
        try:
            with st.spinner("Preparing the exam…"):
                exam, warnings = generate_exam(st.session_state.source_text, current_settings())
            st.session_state.exam = exam
            st.session_state.exam_warnings = warnings
            st.session_state.exam_token = int(st.session_state.exam_token) + 1
            st.session_state.grade = None
        except HistoriaError as exc:
            st.error(exc.message_en)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not build the exam: {exc}")
    exam = st.session_state.exam
    for warning in st.session_state.exam_warnings:
        st.warning(warning)
    if exam is None:
        st.info("Generate an exam after loading a topic. Your answers stay on this page until you submit.")
        return
    st.caption(f"Topic: {exam.title}. Mode: {exam.mode}.")
    token = st.session_state.exam_token
    responses: dict[str, str] = {}
    with st.form(f"exam_form_{token}"):
        for number, question in enumerate(exam.questions, start=1):
            kind = "Multiple choice" if question.kind == "mc" else "Short answer"
            st.markdown(f"**Question {number}** · {kind} · {fmt_points(question.points)} points")
            st.write(question.prompt)
            if question.kind == "mc":
                choice = st.radio(
                    "Choose one answer",
                    question.options,
                    index=None,
                    key=f"ans_{token}_{question.id}",
                )
                responses[question.id] = choice or ""
            else:
                responses[question.id] = st.text_area(
                    "Your answer",
                    key=f"ans_{token}_{question.id}",
                    height=110,
                )
            st.divider()
        submitted = st.form_submit_button("Submit answers")
    if submitted:
        try:
            with st.spinner("Grading…"):
                st.session_state.grade = grade_answers(exam, responses, current_settings())
        except HistoriaError as exc:
            st.error(exc.message_en)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not grade the exam: {exc}")
    grade = st.session_state.grade
    if grade is None:
        return
    st.subheader(f"Score: {grade.score_out_of_10:.1f} / 10")
    st.write(grade.summary)
    if not current_settings().use_llm:
        st.caption(
            "Offline grading matches keywords, names, and dates. "
            "A correct idea written in different words can receive less credit."
        )
    questions = {question.id: question for question in exam.questions}
    for number, item in enumerate(grade.items, start=1):
        label = STATUS_LABELS.get(item.status, item.status)
        title = f"Question {number}: {label} · {item.awarded:.2f} / {item.maximum:.2f}"
        if item.status == "correct":
            st.success(title)
        elif item.status == "partial":
            st.warning(title)
        else:
            st.error(title)
        question = questions.get(item.question_id)
        if item.user_answer:
            st.write(f"Your answer: {item.user_answer}")
        elif question is not None and question.kind == "mc":
            st.write("Your answer: (no option selected)")
        st.write(item.feedback)


def main() -> None:
    st.set_page_config(
        page_title="historia_app",
        page_icon="📜",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    init_state()
    inject_css()
    render_sidebar()
    st.title("historia_app")
    st.caption(
        "Estudia un tema de historia en el iPad o en el ordenador: foto del libro, explicación en español "
        "y examen en inglés."
    )
    upload_tab, script_tab, video_tab, exam_tab = st.tabs(
        ["1. Subir tema", "2. Guion", "3. Vídeo", "4. Exam (English)"]
    )
    with upload_tab:
        render_upload()
    with script_tab:
        render_script()
    with video_tab:
        render_video()
    with exam_tab:
        render_exam()


main()
