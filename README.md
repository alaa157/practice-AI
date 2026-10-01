# practice-AI

Local-first AI experiments: Arabic speech recognition, multilingual text classification, and a file-grounded study RAG pipeline. Everything runs on CPU with open models — no paid APIs.

## What's inside

| Path | Description |
|------|-------------|
| `test_whisper.py` | Arabic ASR with `oddadmix/whisper-large-v3-turbo-arabic-dialectal` (fine-tune of `whisper-large-v3-turbo` for Egyptian, Gulf, Levantine, Maghrebi + MSA). CLI: file, `--model`, `--language`, `--beams`. Greedy decode by default for fast CPU inference. |
| `test_classify.py` | Multilingual classification smoke test with `laya` router (MSA news topic, Egyptian-dialect intent/churn, Gulf-dialect sentiment). |
| `test_edge.py` | Edge-case duel: `laya-multilingual` vs `AlexWortega/openjev` (negation, nonsense, 25-way choice, order-swap, long-doc). Reports accuracy + timing. |
| `study_rag/` | Local study RAG over PDFs/TXT/MD: page-aware chunking, Chroma persistent DB, figure indexing, MCP server (`study_search`, `study_inspect_asset`, `study_list_sources`, `study_ingest_status`). See `study_rag/README.md`. |
| `sample_*.wav`, `*.opus` | Sample audio for ASR tests (`sample_jfk.wav` EN, `sample_ar.wav` AR, plus `my_audio.opus` / `rec2.opus` personal recordings). |

## Quickstart

```bash
pip install torch transformers librosa laya
# Arabic ASR (first run downloads the model)
HF_HUB_CACHE=/tmp/hf-cache python3 test_whisper.py sample_ar.wav

# A/B against base turbo, slower but more accurate beam search
HF_HUB_CACHE=/tmp/hf-cache python3 test_whisper.py sample_ar.wav \
  --model openai/whisper-large-v3-turbo --beams 5

# Classification smoke test
python3 test_classify.py

# Edge-case duel (laya vs openjev)
python3 test_edge.py

# Study RAG
pip install -r study_rag/requirements.txt
python study_rag/ingest.py
python study_rag/query.py "mitosis phases" -k 4
```

## Notes

- CPU-friendly defaults: `int8` / `float32`, greedy decode, one-by-one NLI scoring to stay within RAM.
- Audio is loaded via `librosa` at 16 kHz mono (bypasses PyAV issues).
- `study_rag/chroma_db/`, `study_rag/artifacts/`, and `__pycache__/` are git-ignored rebuildable state — re-run `ingest.py` to recreate.
- Models download from Hugging Face on first use (~800 MB for Whisper Turbo family).
