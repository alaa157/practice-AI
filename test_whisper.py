"""Transcribe Arabic audio with oddadmix/whisper-large-v3-turbo-arabic-dialectal.
Multi-dialect fine-tune of whisper-large-v3-turbo (Egyptian, Gulf, Levantine, Maghrebi, MSA).
Run: HF_HUB_CACHE=/tmp/hf-cache python3 test_whisper.py [audio_file] [--model ...] [--language ar]
"""
import argparse
import os
import time
import warnings

import librosa
import torch
from transformers.models.whisper.modeling_whisper import WhisperForConditionalGeneration
from transformers.models.whisper.processing_whisper import WhisperProcessor
from transformers.utils import logging as hf_logging

warnings.filterwarnings("ignore", message=".*generation_config.*")
hf_logging.set_verbosity_error()  # silence the harmless generation_config notice

DEFAULT_MODEL = "oddadmix/whisper-large-v3-turbo-arabic-dialectal"


def parse_args():
    p = argparse.ArgumentParser(description="Transcribe Arabic audio (fine-tuned Whisper)")
    p.add_argument("audio", nargs="?", default="sample_ar.wav", help="audio file")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help="HF repo, e.g. openai/whisper-large-v3-turbo for A/B comparison")
    p.add_argument("--language", default="ar", help="forced language (default ar)")
    p.add_argument("--beams", type=int, default=1,
                   help="1=greedy (fast, use on CPU), 5+=accurate but minutes on CPU")
    return p.parse_args()


args = parse_args()
if not os.path.isfile(args.audio):
    print(f"File not found: {args.audio}")
    print("Usage: python3 test_whisper.py [audio_file] [--model ...] [--language ar]")
    raise SystemExit(1)

device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if torch.cuda.is_available() else torch.float32
print(f"Loading {args.model} on {device} ({dtype}) ...")
proc = WhisperProcessor.from_pretrained(args.model)
model = WhisperForConditionalGeneration.from_pretrained(
    args.model, torch_dtype=dtype, low_cpu_mem_usage=True, use_safetensors=True
).to(device).eval()

print(f"Loading {args.audio} with librosa (16kHz mono)...")
audio, _ = librosa.load(args.audio, sr=16000, mono=True)
print(f"audio {len(audio)/16000:.1f}s")

print(f"Transcribing (language={args.language}, beams={args.beams}) ...")
feats = proc(audio, sampling_rate=16000, return_tensors="pt").input_features.to(device, dtype)
gen_kwargs = {
    "language": args.language,
    "task": "transcribe",
    "condition_on_prev_tokens": False,  # less hallucination loops
    "no_repeat_ngram_size": 3,
}
if args.beams <= 1:
    gen_kwargs.update(num_beams=1, do_sample=False)  # greedy: ~5x faster on CPU
else:
    gen_kwargs["num_beams"] = args.beams
t0 = time.time()
with torch.no_grad():
    ids = model.generate(feats, **gen_kwargs)
print(f"decode took {time.time()-t0:.0f}s")
text = proc.batch_decode(ids, skip_special_tokens=True)[0]
print("-" * 60)
print(text.strip())
print("-" * 60)
print("OK - done!")
