---
title: historia_app
emoji: 📜
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
---

# historia_app

Aplicación de estudio para un tema de historia. Subes un texto o fotos de las páginas, la app prepara un guion en español, monta un vídeo MP4 con diapositivas y narración, y propone un examen en inglés con nota sobre 10.

La interfaz está en español. La pestaña del examen está en inglés a propósito, para practicar el vocabulario del tema.

## Qué hace

1. **Subir tema.** Acepta `.txt`, `.pdf` y `.docx`. El PDF se lee con pdfplumber y, si no sale texto, con pypdf. El Word se lee con python-docx. También puedes pegar el texto, cargar `ejemplo_tema.txt` (la Revolución francesa) o fotografiar las páginas (jpg, png, heic, webp, varias a la vez, o la cámara del iPad). El OCR por defecto es Tesseract en español. Si hay una clave de API, puedes usar un modelo de visión. El texto queda en un recuadro editable.
2. **Guion.** Explicación en español con introducción, secciones y conclusión.
3. **Vídeo.** Diapositivas de 1280×720, voz en español y un MP4 para ver y descargar.
4. **Exam (English).** Preguntas de opción múltiple y de respuesta corta, corrección y nota sobre 10, con un comentario por pregunta.

## Requisitos

- Python 3.10 o posterior
- ffmpeg, con `ffprobe`, en el PATH (solo hace falta para el vídeo)
- Tesseract con el idioma español, para leer fotos (`tesseract-ocr` y `tesseract-ocr-spa`)
- Internet si quieres voz, traducción automática al inglés, el OCR con modelo o el modo con modelo

## Instalación

Desde la carpeta del proyecto:

```bash
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
```

macOS y Linux:

```bash
source .venv/bin/activate
```

Después:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Los scripts `run.sh` (macOS y Linux) y `run.bat` (Windows) crean el entorno, instalan las dependencias y abren la aplicación.

### Instalar ffmpeg

Linux (Debian, Ubuntu y derivadas):

```bash
sudo apt update
sudo apt install ffmpeg python3-venv tesseract-ocr tesseract-ocr-spa
```

`python3-venv` hace falta para crear el entorno con `python -m venv`.

macOS (con Homebrew):

```bash
brew install ffmpeg tesseract tesseract-lang
```

Windows (con winget):

```bat
winget install Gyan.FFmpeg
winget install UB-Mannheim.TesseractOCR
```

En Windows, después de instalar Tesseract, añade su carpeta al PATH y comprueba que existe el idioma `spa` (`tesseract --list-langs`).

Cierra y vuelve a abrir la terminal para que `ffmpeg` quede en el PATH. Comprueba con `ffmpeg -version`.

## Ejecutar

```bash
streamlit run app.py
```

O bien `./run.sh` o `run.bat`. Streamlit muestra una dirección local, normalmente `http://localhost:8501`.

## Las dos formas de generar

### Sin conexión (reglas)

Es el modo por defecto y no pide clave.

- Elige frases repartidas a lo largo del texto. Cada frase se puntúa por la frecuencia de sus palabras y por si contiene fechas o nombres.
- El guion enmarca esas frases con una introducción, varios apartados y una conclusión. No redacta datos nuevos: si un hecho no está en el archivo, no aparece.
- El examen sale del propio texto. Las preguntas de opción múltiple son de tipo hueco (cloze): se tapa una fecha, un nombre o un término y las otras opciones salen de otras fechas o términos del mismo texto. Si no hay bastantes, se añaden distractores genéricos solo para completar cuatro opciones.
- La respuesta corta se puntúa por solapamiento de palabras clave (fechas, nombres y términos). Hay crédito parcial.
- El enunciado se traduce al inglés con `deep-translator`. Primero se intenta `GoogleTranslator`. Si Google no responde (a veces devuelve un error 429), se usa `MyMemoryTranslator`, también de esa biblioteca. Si ninguna traducción está disponible, el enunciado sigue en inglés y cita la frase original.

La voz no forma parte del modo «sin modelo»: gTTS y edge-tts siempre hablan a través de internet.

### Con modelo de lenguaje

En la barra lateral elige «Modelo de lenguaje (API)» y escribe una clave compatible con la API de OpenAI. También vale la variable de entorno `OPENAI_API_KEY`. Puedes cambiar la URL base (`OPENAI_BASE_URL`, por defecto `https://api.openai.com/v1`) y el modelo (`OPENAI_MODEL`, por defecto `gpt-4o-mini`).

Si el modelo responde, prepara el guion, el examen en inglés (JSON) y la nota de las respuestas cortas. Si falla o no hay clave, el guion y el examen vuelven a las reglas locales y la pantalla avisa. La nota de una respuesta corta también vuelve a las palabras clave si el modelo no contesta.

La clave se queda en la sesión del navegador. En un servidor puedes guardarla como secreto `OPENAI_API_KEY` (Streamlit Community Cloud o `.streamlit/secrets.toml`; hay un ejemplo en `.streamlit/secrets.toml.example`). No la subas al repositorio.

## Vídeo

- Voz: gTTS en español, o edge-tts con la voz `es-ES-AlvaroNeural`. Si la voz elegida falla, se prueba la otra.
- Fondo: degradados y un patrón dibujados con Pillow, sin descargar imágenes.
- Montaje: ffmpeg, vídeo H.264 (`libx264`), píxeles `yuv420p`, 30 fps, audio AAC y `-movflags +faststart`.
- El reproductor y el botón «Descargar MP4» están en la pestaña 3. El MP4 es H.264 en `yuv420p`, perfil main, 30 fps, audio AAC y `faststart`, para que Safari lo reproduzca en la propia página y pueda descargarlo.
- Como mucho hay 6 diapositivas, para que un alojamiento gratuito no se quede sin memoria.

## Usarla en el iPad

El iPad no ejecuta Python. La app tiene que estar en un servidor con dirección https. Luego se abre con Safari. La cámara del iPad solo funciona en https, así que en el servidor publicado sí pide permiso; en un `http://` local, no.

Los botones ocupan todo el ancho y se pueden pulsar con el dedo. No hay acciones que solo aparezcan al pasar el ratón.

### Opción A. Streamlit Community Cloud (gratis, con cuenta de GitHub)

1. Crea una cuenta gratis en [https://github.com](https://github.com).
2. Crea un repositorio nuevo, por ejemplo `historia-app`.
3. Sube **el contenido** de la carpeta `historia_app` a la raíz de ese repositorio: tienen que verse `app.py`, `requirements.txt`, `packages.txt` y la carpeta `historia`. No dejes todo dentro de otra carpeta.
4. Entra en [https://share.streamlit.io](https://share.streamlit.io), inicia sesión con GitHub y pulsa **Create app**.
5. Elige el repositorio, la rama `main` y el archivo `app.py`.
6. En **Advanced settings**, si quieres el modelo o el OCR de visión, abre **Secrets** y pega:

```toml
OPENAI_API_KEY = "tu-clave"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-4o-mini"
```

7. Pulsa **Deploy**. El archivo `packages.txt` instala ffmpeg y Tesseract en español. Espera a que termine y copia la dirección `https://....streamlit.app`.
8. Ábrela en Safari en el iPad.

### Opción B. Hugging Face Spaces (con el Dockerfile)

1. Crea una cuenta en [https://huggingface.co](https://huggingface.co).
2. **New Space**. Nombre, por ejemplo, `historia-app`. Elige el SDK **Docker** y déjalo público.
3. Sube los mismos archivos, incluido el `Dockerfile`. El contenedor instala ffmpeg y `tesseract-ocr-spa` y escucha en el puerto 7860.
4. En **Settings → Secrets**, si hace falta, añade `OPENAI_API_KEY`.
5. Cuando el Space esté en verde, abre su dirección en Safari.

Render u otro servicio con Docker usa el mismo `Dockerfile`. Si la plataforma define la variable `PORT`, la app la respeta.

### Poner el icono en la pantalla de inicio

1. Abre la dirección de la app en **Safari** (no dentro de otra aplicación).
2. Pulsa el botón **Compartir** (el cuadrado con la flecha).
3. Elige **Añadir a pantalla de inicio**.
4. Ponle el nombre `historia` y pulsa **Añadir**.
5. A partir de ahí se abre como una ficha, a pantalla casi completa.

Para estudiar: pestaña 1, fotos de las páginas en orden (o la cámara), **Leer las fotos**, corrige el texto, pestaña 2 el guion, pestaña 3 el vídeo. El botón **Descargar MP4** guarda el archivo en la app Archivos.

## Pruebas

Con el entorno activado:

```bash
pytest
```

Eso cubre la extracción, el guion, la nota del examen y un vídeo corto con audio silencioso generado por ffmpeg, sin llamar a Google ni a un modelo.

Para recorrer el ejemplo real (texto, PDF, DOCX, voz gTTS, ffprobe y un examen corregido):

```bash
python scripts/headless_demo.py
```

Ese script necesita ffmpeg e internet para la narración y, si está disponible, para la traducción.

## Limitaciones

- El modo local no «entiende» el tema como un profesor: selecciona frases y las ordena. La prosa del vídeo es tan clara como el archivo de partida.
- El OCR de Tesseract se equivoca con letra pequeña, sombras o páginas giradas raras. Por eso el texto se puede corregir. Un PDF que solo contiene una imagen sigue sin tener texto seleccionable: súbelo como foto.
- Las fotos HEIC necesitan `pillow-heif`. El iPhone las usa por defecto y la app las acepta.
- La traducción al inglés necesita internet. Se intenta Google Translate y, si ese servicio bloquea la petición, MyMemory. Sin ninguno de los dos, el examen usa una plantilla en inglés con la frase original.
- gTTS y edge-tts necesitan internet. edge-tts puede dejar de funcionar si cambia el servicio de Microsoft; en ese caso se usa gTTS.
- La nota local de las respuestas cortas mira palabras clave. Una buena paráfrasis que no usa esas palabras puede quedar baja. El modo con modelo juzga mejor el sentido, siempre que la API responda.
- El modelo puede ignorar la instrucción de no inventar. Conviene leer el guion antes de estudiarlo.
- El vídeo son diapositivas con voz, no una animación ni un documental.
- Los archivos y la clave viven en la sesión de esa ventana. Al pulsar «Empezar de nuevo» se borran de la sesión.
- La voz, la traducción y el modo con modelo envían el texto del tema a servicios de fuera. El guion y el examen locales no llaman a un modelo.
