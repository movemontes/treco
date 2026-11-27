"""Ferramentas de som: BPM e tom da música, cortar silêncios e limpar a voz.

Tudo roda no computador, com o ffmpeg que vem no Treco. O original nunca é alterado.
"""
import os
import re
import subprocess
import tempfile

from ..core.formats import FFMPEG
from ..core.i18n import english
from ..core.jobs import Job, NothingToGain
from . import media
from .quick import AUDIO_ENCODERS, X264, audio_ext, faststart, finish, guarded, new_output
from .transform import video_ext

try:
    NO_WINDOW = subprocess.CREATE_NO_WINDOW
except AttributeError:
    NO_WINDOW = 0

RATE = 22050


def decode(src, rate=RATE, start=0.0, seconds=None):
    """O som do arquivo em mono, como números de -1 a 1."""
    import numpy as np
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", src]
    if seconds:
        cmd += ["-t", f"{seconds:.2f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    p = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if p.returncode or not p.stdout:
        raise RuntimeError("áudio não reconhecido")
    return np.frombuffer(p.stdout, dtype=np.float32)


# ---------------------------------------------------------------- BPM e tom
NOTES_PT = ("Dó", "Dó#", "Ré", "Mib", "Mi", "Fá", "Fá#", "Sol", "Láb", "Lá", "Sib", "Si")
NOTES_EN = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
# perfis de Krumhansl: quanto cada nota "pesa" numa tonalidade maior e menor
MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


def _spectrogram(samples, size, hop):
    import numpy as np
    if len(samples) < size:
        samples = np.pad(samples, (0, size - len(samples)))
    count = 1 + (len(samples) - size) // hop
    index = np.arange(size)[None, :] + hop * np.arange(count)[:, None]
    frames = samples[index] * np.hanning(size).astype(np.float32)
    return np.abs(np.fft.rfft(frames, axis=1))


def find_tempo(samples, rate=RATE):
    """BPM pela regularidade dos ataques (bumbo, palmas, acordes)."""
    import numpy as np
    hop = 256  # passo curto: mede o andamento com precisão de décimos
    spec = np.log1p(100 * _spectrogram(samples, 1024, hop))
    flux = np.maximum(0, np.diff(spec, axis=0)).sum(axis=1)  # quanto o som "cresce" de um instante para o outro
    if flux.size < 64 or not flux.any():
        return None, 0.0
    flux = flux - np.convolve(flux, np.ones(32) / 32, mode="same")  # tira a tendência, fica só o pulso
    flux = np.maximum(flux, 0)
    fps = rate / hop
    n = flux.size
    spectrum = np.fft.rfft(flux - flux.mean(), 2 * n)
    corr = np.fft.irfft(spectrum * np.conj(spectrum))[:n]
    corr /= corr[0] or 1
    best, best_score = None, -1.0
    for bpm in np.arange(60.0, 200.0, 0.25):
        lag = 60 * fps / bpm
        score = 0.0
        for mult, weight in ((1, 1.0), (2, .5), (4, .25)):  # o pulso e os múltiplos dele
            pos = lag * mult
            if pos >= n - 1:
                break
            i = int(pos)
            score += weight * (corr[i] + (corr[i + 1] - corr[i]) * (pos - i))
        score *= np.exp(-.5 * (np.log2(bpm / 115) / .9) ** 2)  # prefere andamentos comuns, entre 80 e 160
        if score > best_score:
            best, best_score = bpm, score
    return float(best), float(max(0.0, min(1.0, best_score)))


def find_key(samples, rate=RATE):
    """Tom e modo (maior ou menor) pela quantidade de cada nota ao longo da música."""
    import numpy as np
    size = 8192
    spec = _spectrogram(samples, size, 4096) ** 2
    freqs = np.fft.rfftfreq(size, 1 / rate)
    useful = (freqs >= 55) & (freqs <= 2000)
    pitch = np.round(12 * np.log2(freqs[useful] / 440.0) + 69).astype(int) % 12
    energy = spec[:, useful].sum(axis=0)
    chroma = np.bincount(pitch, weights=energy, minlength=12)
    if not chroma.any():
        return None
    chroma = (chroma - chroma.mean()) / (chroma.std() or 1)
    results = []
    for mode, profile in (("maior", MAJOR), ("menor", MINOR)):
        prof = np.array(profile)
        prof = (prof - prof.mean()) / prof.std()
        for tonic in range(12):
            score = float(np.dot(chroma, np.roll(prof, tonic)) / 12)
            results.append((score, tonic, mode))
    results.sort(reverse=True)
    return results


def key_name(tonic, mode):
    if english():
        return f"{NOTES_EN[tonic]} {'major' if mode == 'maior' else 'minor'}"
    return f"{NOTES_PT[tonic]} {mode}"


def relative(tonic, mode):
    """Maior e menor que usam as mesmas notas (Dó maior ↔ Lá menor)."""
    return ((tonic + 9) % 12, "menor") if mode == "maior" else ((tonic + 3) % 12, "maior")


def tempo_and_key(src, job=None):
    job = job or Job()
    info = media.probe(src)
    if not info["audio"]:
        raise RuntimeError("não tem áudio")
    duration = info["duration"] or 0
    start = 20.0 if duration > 120 else 0.0  # pula a introdução das músicas longas
    samples = decode(src, start=start, seconds=150)
    job.progress(.4)
    if samples.size < RATE * 4:
        raise RuntimeError("áudio curto demais")
    bpm, confidence = find_tempo(samples)
    job.progress(.7)
    keys = find_key(samples)
    job.progress(1)
    result = {"bpm": bpm, "bpm_sure": confidence, "key": None, "alt": None}
    if keys:
        score, tonic, mode = keys[0]
        result["key"] = key_name(tonic, mode)
        result["key_sure"] = max(0.0, min(1.0, score / .8))
        second = keys[1]
        if second[0] > score - .03 and (second[1], second[2]) != relative(tonic, mode):
            result["alt"] = key_name(second[1], second[2])  # empate: mostra a segunda opção
    return result


# ---------------------------------------------------------------- cortar silêncios
GAPS = {"Pouca": .08, "Média": .2, "Bastante": .4}       # folga mantida antes e depois da fala
PAUSES = {"0,3 s": .3, "0,6 s": .6, "1 s": 1.0, "2 s": 2.0}  # só corta pausas maiores que isso


def loudness(src, frame=.02, rate=8000):
    """Volume (em dB) a cada 20 ms, lido aos pedaços para não pesar na memória."""
    import numpy as np
    size = int(rate * frame)
    p = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-ac", "1",
                          "-ar", str(rate), "-f", "f32le", "-"], stdout=subprocess.PIPE, creationflags=NO_WINDOW)
    levels, rest = [], np.zeros(0, dtype=np.float32)
    while True:
        chunk = p.stdout.read(size * 4 * 500)
        if not chunk:
            break
        data = np.concatenate([rest, np.frombuffer(chunk, dtype=np.float32)])
        whole = len(data) // size * size
        blocks = data[:whole].reshape(-1, size)
        levels.append(10 * np.log10(np.mean(blocks.astype(np.float64) ** 2, axis=1) + 1e-10))
        rest = data[whole:]
    p.wait()
    return np.concatenate(levels) if levels else np.zeros(0)


def find_silences(src, minimum=.3, frame=.02):
    """Trechos em silêncio: lista de (início, fim) em segundos.
    O limite se ajusta à gravação: fica entre o chiado de fundo e o volume da fala."""
    import numpy as np
    levels = loudness(src, frame)
    if levels.size < 10:
        return []
    floor = np.percentile(levels, 10)
    speech = np.percentile(levels, 90)
    if speech - floor < 8:  # quase não muda de volume: não há pausas de verdade
        return []
    threshold = floor + .3 * (speech - floor)
    quiet = levels < threshold
    silences, start = [], None
    for i, q in enumerate(np.append(quiet, False)):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * frame >= minimum:
                end = i * frame
                silences.append((start * frame, None if i >= len(quiet) else end))
            start = None
    return silences


def keep_parts(silences, duration, gap, pause):
    """O que fica: a fala com uma folga de cada lado, sem as pausas longas."""
    parts, cursor = [], 0.0
    for start, end in silences:
        end = duration if end is None else end
        if end - start < pause:
            continue
        cut_from = start + gap if start > 0 else 0.0
        cut_to = end - gap if end < duration else duration
        if cut_to - cut_from < .05:
            continue
        if cut_from > cursor:
            parts.append((cursor, cut_from))
        cursor = cut_to
    if cursor < duration:
        parts.append((cursor, duration))
    return [(round(a, 3), round(b, 3)) for a, b in parts if b - a > .02]


def silence_plan(src, gap, pause, silences=None):
    info = media.probe(src)
    duration = info["duration"] or 0
    if silences is None:
        silences = find_silences(src)
    parts = keep_parts(silences, duration, gap, pause)
    kept = sum(b - a for a, b in parts)
    return {"duration": duration, "kept": kept, "parts": parts, "silences": silences}


def cut_silences(src, kind, gap=.2, pause=.6, folder=None, job=None):
    job = job or Job()
    info = media.probe(src)
    if not info["audio"]:
        raise RuntimeError("não tem áudio")
    plan = silence_plan(src, gap, pause)
    parts = plan["parts"]
    if not parts or plan["duration"] - plan["kept"] < .3:
        raise NothingToGain("não achei pausas para cortar")
    keep = "+".join(f"between(t,{a},{b})" for a, b in parts)
    fade = "afade=t=in:d=0.01"  # evita estalo nas emendas
    handle, script = tempfile.mkstemp(prefix="treco_cortes_", suffix=".txt")  # o filtro pode ser muito longo
    os.close(handle)
    if kind == "video":
        dst = new_output(src, "sem silêncios", video_ext(src), folder)
        graph = (f"[0:v]select='{keep}',setpts=N/FRAME_RATE/TB[v];"
                 f"[0:a]aselect='{keep}',asetpts=N/SR/TB,{fade}[a]")
        args = ["-/filter_complex", script, "-map", "[v]", "-map", "[a]"] + X264 + \
               ["-c:a", "aac", "-b:a", "192k"] + faststart(dst)
    else:
        ext = audio_ext(src)
        dst = new_output(src, "sem silêncios", ext, folder)
        graph = f"[0:a]aselect='{keep}',asetpts=N/SR/TB,{fade}[a]"
        args = ["-/filter_complex", script, "-map", "[a]"] + AUDIO_ENCODERS[ext]
    with open(script, "w", encoding="utf-8") as f:
        f.write(graph)

    def work():
        try:
            media.run_with_progress(["-i", src, "-map_metadata", "0"] + args + [dst], plan["kept"], job)
        finally:
            try:
                os.remove(script)
            except OSError:
                pass
    guarded(dst, work)
    job.progress(1)
    return finish(src, dst)


# ---------------------------------------------------------------- limpar a voz
STRENGTH = {"Leve": 0, "Média": 1, "Forte": 2}


def voice_filter(hiss=True, noise=True, echo=False, level=1):
    """Corrente de filtros para gravação de voz: chiado, ruído de fundo e eco da sala."""
    steps = ["highpass=f=70"]  # tira o ronco grave (ar-condicionado, mesa, vento)
    if noise:
        steps.append(f"afftdn=nr={(8, 14, 22)[level]}:nf=-40:tn=1")  # ruído constante, aprendendo com o fundo
    if hiss:
        steps.append(f"anlmdn=s={(2, 4, 7)[level]}:p=0.002:r=0.006")  # chiado fino, sem deixar a voz metálica
    if echo:
        # abaixa o som entre as palavras, onde o eco da sala fica mais evidente
        steps.append(f"agate=threshold={(0.01, 0.018, 0.03)[level]}:ratio={(2, 3, 5)[level]}"
                     f":range={(0.35, 0.2, 0.1)[level]}:attack=3:release={(160, 110, 70)[level]}")
        steps.append("deesser=i=0.2")
    steps.append("alimiter=limit=0.95")
    return ",".join(steps)


def clean_voice(src, kind, hiss=True, noise=True, echo=False, level=1, folder=None, job=None):
    job = job or Job()
    info = media.probe(src)
    if not info["audio"]:
        raise RuntimeError("não tem áudio")
    if not (hiss or noise or echo):
        raise RuntimeError("escolha o que limpar")
    audio_filter = voice_filter(hiss, noise, echo, level)
    if kind == "video":
        dst = new_output(src, "voz limpa", video_ext(src), folder)
        head = ["-i", src, "-map", "0:v:0", "-map", "0:a:0", "-sn", "-dn", "-map_metadata", "0", "-af", audio_filter]
        sound = ["-c:a", "aac", "-b:a", "192k"]

        def work():
            try:
                media.run_with_progress(head + ["-c:v", "copy"] + sound + faststart(dst) + [dst], info["duration"], job)
            except RuntimeError:
                media.run_with_progress(head + X264 + sound + faststart(dst) + [dst], info["duration"], job)
    else:
        ext = audio_ext(src)
        dst = new_output(src, "voz limpa", ext, folder)
        args = ["-i", src, "-map", "0:a:0", "-vn", "-map_metadata", "0", "-af", audio_filter] + AUDIO_ENCODERS[ext]

        def work():
            media.run_with_progress(args + [dst], info["duration"], job)
    guarded(dst, work)
    job.progress(1)
    return finish(src, dst)
