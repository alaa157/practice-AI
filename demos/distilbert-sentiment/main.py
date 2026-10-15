"""Run English sentiment analysis with a pretrained Hugging Face model."""
from __future__ import annotations

import argparse
from transformers import pipeline

MODEL_ID = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"


def analyze_sentiment(text: str, classifier=None) -> dict:
    """Return the predicted label and confidence for a non-empty sentence."""
    if not text or not text.strip():
        raise ValueError("Please provide a non-empty sentence.")
    if classifier is None:
        classifier = pipeline(
            task="sentiment-analysis",
            model=MODEL_ID,
            device=-1,  # CPU by default; no GPU required
        )
    result = classifier(text.strip())[0]
    return {"label": result["label"], "score": float(result["score"])}


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify English text as POSITIVE or NEGATIVE.")
    parser.add_argument("text", nargs="*", help="Text to analyze")
    args = parser.parse_args()
    text = " ".join(args.text).strip()
    if not text:
        text = input("Enter an English sentence: ").strip()
    prediction = analyze_sentiment(text)
    print(f"Text: {text}")
    print(f"Sentiment: {prediction['label']}")
    print(f"Confidence: {prediction['score']:.2%}")


if __name__ == "__main__":
    main()
