"""Test laya-multilingual on Arabic (MSA + Egyptian dialect). CPU-friendly."""
import time

from laya import Router

router = Router()  # lazy: builds multilingual checkpoint on first Arabic call

tests = [
    ("MSA news (your Whisper transcript)",
     "تشكلت في المحيط الأطلسي اليوم عاشر عاصفة مسماة لموسم الأعاصير",
     {"topic": {"type": "choice", "instructions": "What is the topic?",
                "criteria": {"weather": "storms, hurricanes, rain, climate",
                             "sports": "football, matches, players, goals",
                             "politics": "elections, government, ministers"}}}),
    ("Egyptian dialect (angry customer)",
     "انا اتخصم مني فلوس مرتين الشهر ده وعايز استرد المبلغ النهارده والا هلغي الاشتراك",
     {"intent": {"type": "choice", "instructions": "What does the customer want?",
                 "criteria": {"refund": "money back, duplicate charge, refund",
                              "support": "bug, error, technical problem",
                              "other": "anything else"}},
      "churn": {"type": "noul", "instructions": "Does the customer threaten to cancel?"}}),
    ("Gulf dialect (happy customer)",
     "الخدمة وايد زينة والله يعطيكم العافية على السرعة",
     {"sentiment": {"type": "choice", "instructions": "What is the sentiment?",
                    "criteria": {"positive": "happy, praise, thanks",
                                 "negative": "angry, complaint, bad",
                                 "neutral": "neither"}}})
]

for title, state, questions in tests:
    t0 = time.time()
    r = router.predict(state, questions)
    dt = time.time() - t0
    print(f"--- {title} ({dt:.1f}s, routed: {r['routing']['model']}) ---")
    for q, a in r["answers"].items():
        if "choice" in a:
            print(f"  {q}: {a['choice']} (conf {a.get('confidence', '?')})")
        elif "noul" in a:
            print(f"  {q}: P(yes)={a['noul']:.3f}")
        elif "score" in a:
            print(f"  {q}: {a['score']}")
print("OK - done!")
