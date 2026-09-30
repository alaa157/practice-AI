"""Test openai/whisper-large-v3-turbo with faster-whisper (CPU-friendly).
Uses librosa to load audio -> bypasses broken PyAV 19 API.
Run with: HF_HUB_CACHE=/tmp/hf-cache python3 test_whisper.py
"""
import librosa
from faster_whisper import WhisperModel

print("Loading model large-v3-turbo (first run downloads ~800MB)...")
model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")

print("Loading sample_jfk.wav with librosa (16kHz mono)...")
audio, sr = librosa.load("sample_jfk.wav", sr=16000, mono=True)
print(f"audio len={len(audio)} samples, {len(audio)/16000:.1f}s")

print("Transcribing ...")
segments, info = model.transcribe(audio, beam_size=5)

print(f"Detected language: {info.language} (prob {info.language_probability:.2f})")
print("-" * 60)
full_text = ""
for s in segments:
    print(f"[{s.start:.1f}s -> {s.end:.1f}s] {s.text}")
    full_text += s.text + " "
print("-" * 60)
print("FULL:", full_text.strip())
print("OK - installation works!")
