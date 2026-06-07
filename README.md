<div align="center">

```
    __        ____             __
   / /  ___  / __/_ ____  ___ / /_ _____
  / /__/ _ \/ _// /(_-< _ \/ // // (_-<
 /____/\___/_/ /_(_)__/ .__/_/\_,_//___/
                     /_/
```

# lofiplus

**Reproductor interactivo de música Lo-Fi para tu terminal**

[![Python](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-e6b450.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macOS%20%7C%20windows-lightgrey.svg)]()
[![Textual](https://img.shields.io/badge/built%20with-Textual-9b8dd4.svg)](https://textual.textualize.io)

Espectro FFT en tiempo real · Transmisiones en vivo de YouTube · Radio por Internet · Biblioteca local · Descargador yt-dlp

</div>

---

## ✨ Características

- 🎵 **Transmisiones de Lo-Fi en vivo** — 7 estaciones seleccionadas (Lofi Girl, Chillhop, Radio Swiss Jazz…)
- 📊 **Espectro en tiempo real** — Visualizador de 32 bandas con renderizado half-block (2× resolución), peak hold y gradiente de color. Soporta CAVA, loopback y modo sintético
- ⬇️ **Descargador integrado** — Pega una URL de YouTube y obtén un MP3 en `~/.lofiplusmusic/`
- 📁 **Biblioteca local** — Detecta automáticamente MP3, FLAC, WAV, AAC, AIFF, MP4, MOV, WEBM
- ⌨️ **Controlado por teclado** — Navegación tipo Vim, no se requiere ratón
- 🔄 **Actualizaciones automáticas** — `lofiplus -a` descarga la última versión desde GitHub
- 💾 **Consumo mínimo** — ~80MB de RAM, buffers de tamaño fijo, sin fugas de memoria

---

## 🚀 Instalación rápida

### Linux / macOS

```bash
git clone https://github.com/Beardynh/lofiplus.git ~/.local/share/lofiplus
cd ~/.local/share/lofiplus
./install.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/Beardynh/lofiplus.git $env:LOCALAPPDATA\lofiplus
cd $env:LOCALAPPDATA\lofiplus
.\install.ps1
```

Después de la instalación, ejecuta:

```bash
lofiplus
```

---

## 📋 Requisitos del sistema

| Dependencia | Por qué | Instalar (Linux) | Instalar (macOS) | Instalar (Windows) |
|---|---|---|---|---|
| Python ≥3.11 | Ejecución | `sudo pacman -S python` | `brew install python` | [python.org](https://python.org) |
| mpv | Reproducción de audio | `sudo pacman -S mpv` | `brew install mpv` | `winget install mpv` |
| yt-dlp | YouTube/Descargas | `sudo pacman -S yt-dlp` | `brew install yt-dlp` | `winget install yt-dlp` |
| ffmpeg | Conversión de audio | `sudo pacman -S ffmpeg` | `brew install ffmpeg` | `winget install ffmpeg` |
| cava *(opcional)* | Visualizador de espectro | `sudo pacman -S cava` | `brew install cava` | — |

El script `install.sh` detectará las dependencias faltantes y te mostrará el comando exacto para tu plataforma.

---

## ⌨️ Atajos de teclado

| Tecla | Acción |
|---|---|
| `↑` / `↓` | Navegar por las estaciones |
| `Enter` | Reproducir estación seleccionada |
| `Espacio` | Reproducir / Pausar |
| `s` | Detener |
| `=` / `-` | Volumen +5 / -5 |
| `/` | Abrir paleta de comandos |
| `Ctrl+/` | Enfocar campo de descarga |
| `Esc` | Cancelar / Atrás |
| `q` | Salir |

### Paleta de comandos (`/`)

| Comando | Descripción |
| ----------------| --------------------------------------|
| `/act` | Buscar actualizaciones y ver registro de cambios |
| `/help` | Mostrar atajos de teclado |
| `/about` | Versión de la aplicación y créditos |
| `/sleep <min>` | Programar parada automática en N minutos |
| `/quit` | Salir de lofiplus |

---

## 🔄 Actualización

```bash
lofiplus -a            # Descargar la última versión y reiniciar
lofiplus --check       # Solo comprobar si hay actualizaciones disponibles
```

Dentro de la interfaz (TUI), presiona `/` y escribe `act` para ver las notas de la última versión.

---

## 🎨 Personalización

Edita `~/.config/lofiplus/config.toml` (creado automáticamente en la primera ejecución):

```toml
[player]
volume = 70

[appearance]
theme = "dark"

[stations]
custom = [
  { name = "Mi Radio", url = "http://example.com/stream.mp3", tag = "radio" },
]
```

---

## 🧩 Creado con

- [Textual](https://textual.textualize.io) — Framework TUI moderno para Python
- [mpv](https://mpv.io) — El motor de audio que hace el trabajo pesado
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — Descargador de YouTube y extractor de URLs
- [numpy](https://numpy.org) — Cálculo de FFT
- [sounddevice](https://python-sounddevice.readthedocs.io) — Enlaces de PortAudio para captura de audio interna (loopback)
- [CAVA](https://github.com/karlstav/cava) — Visualizador de audio en consola (backend preferido del espectro)

---

## 📜 Licencia

MIT © 2026 John Timoteo — ver [LICENSE](LICENSE)

---

<div align="center">

Hecho con ♪ para sesiones nocturnas de programación

[Reportar un error](https://github.com/Beardynh/lofiplus/issues) · [Solicitar una función](https://github.com/Beardynh/lofiplus/issues/new) · [Registro de cambios](CHANGELOG.md)

</div>
