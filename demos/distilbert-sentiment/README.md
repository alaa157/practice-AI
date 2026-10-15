# DistilBERT Sentiment Analysis Demo

A tiny Python demo using a pretrained model from Hugging Face to classify **English** text as `POSITIVE` or `NEGATIVE`.

- **Model:** [distilbert/distilbert-base-uncased-finetuned-sst-2-english](https://huggingface.co/distilbert/distilbert-base-uncased-finetuned-sst-2-english)
- **Task:** text classification / sentiment analysis
- **Runtime:** CPU by default
- **Model license:** Apache-2.0 (see the model card)

## Run it

From the repository root:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

pip install -r demos/distilbert-sentiment/requirements.txt
python demos/distilbert-sentiment/main.py "This application is amazing!"
```

The first run downloads the pretrained model weights from Hugging Face and may take a little while. They are **not** stored in this GitHub repository.

You can also run it interactively:

```bash
python demos/distilbert-sentiment/main.py
```

## Run the offline unit tests

These tests use a small fake classifier and do not download model weights:

```bash
python -m unittest discover -s demos/distilbert-sentiment -p "test_*.py"
```

## Limitations

This checkpoint is intended for English sentiment and is trained on SST-2. It is not an Arabic sentiment model and should not be treated as a reliable measure of every kind of opinion or context.
