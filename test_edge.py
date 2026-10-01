"""Edge-case duel: laya-multilingual vs openjev-0.8B. Same cases, accuracy + time."""
import gc
import time

import torch

CASES = [
    ("EN simple", "I was charged twice for March, refund the duplicate now.",
     {"billing": "invoices, payments, refunds", "technical": "bugs, outages, errors",
      "sales": "pricing, contracts"}, "billing"),
    ("EN negation", "The movie was not boring, I actually loved every single minute of it.",
     {"positive": "loved it, great, happy", "negative": "hated it, boring, bad"}, "positive"),
    ("AR Egyptian", "انا اتخصم مني فلوس مرتين الشهر ده وعايز استرد المبلغ النهارده",
     {"refund": "money back, duplicate charge", "support": "bug, technical problem",
      "other": "anything else"}, "refund"),
    ("AR negation", "مش عايز الغي الاشتراك، بس عايز اعرف رصيدي كام",
     {"cancel": "user wants to cancel or leave", "balance": "asks about balance or account info"},
     "balance"),
    ("Nonsense", "Colorless green ideas refund furiously through the quantum invoice.",
     {"billing": "invoices, payments, refunds", "technical": "bugs, outages, errors",
      "sales": "pricing, contracts"}, None),  # expect LOW confidence, any label
    ("25 options", "My card was declined at the ATM even though I have money in my account.",
     {f"intent_{i}": f"filler description number {i} about unrelated banking topic {i}"
      for i in range(25)} | {"atm_fail": "card declined at ATM, cash machine problems"},
     "atm_fail"),
    ("Order swap", "I was charged twice for March, refund the duplicate now.",
     {"sales": "pricing, contracts", "technical": "bugs, outages, errors",
      "billing": "invoices, payments, refunds"}, "billing"),  # same as #1, reversed
]

LONG_DOC = ("Quarterly planning memo. " * 200
            + " The hurricane season outlook predicts ten named Atlantic storms this year.")

print("=" * 70, "\nLAYA-MULTILINGUAL\n" + "=" * 70)
from laya import Router
router = Router()
laya_times, laya_hits, laya_total = [], 0, 0
for title, state, options, expected in CASES:
    t0 = time.time()
    r = router.predict(state, {"q": {"type": "choice", "instructions": "Pick the best label.",
                                     "criteria": options}})
    dt = time.time() - t0
    a = r["answers"]["q"]
    mark = ""
    if expected:
        laya_total += 1
        mark = "OK " if a["choice"] in (expected, options.get(expected, expected)) else "MISS"
        # choice returns the KEY; map: find key whose value matches expected desc
        laya_hits += mark == "OK "
    print(f"[{mark or 'INFO'}] {title}: {a['choice']} conf={a.get('confidence', 0):.3f} ({dt:.1f}s)")
    laya_times.append(dt)
t0 = time.time()
r = router.predict(LONG_DOC, {"q": {"type": "choice", "instructions": "What is the topic?",
                                    "criteria": {"weather": "storms, hurricanes, climate",
                                                 "finance": "budgets, revenue, planning"}}})
dt = time.time() - t0
print(f"[{'OK ' if r['answers']['q']['choice'] == 'weather' else 'MISS'}] Long doc: "
      f"{r['answers']['q']['choice']} ({dt:.1f}s)")
laya_total += 1
laya_hits += r["answers"]["q"]["choice"] == "weather"
laya_times.append(dt)
del router
gc.collect()
print(f"LAYA: {laya_hits}/{laya_total} correct, total {sum(laya_times):.0f}s")

print("=" * 70, "\nOPENJEV-0.8B\n" + "=" * 70)
from transformers import AutoModelForSequenceClassification, AutoTokenizer
SUB = "qwen3.5-0.8b-nli-v2s-long"
tok = AutoTokenizer.from_pretrained("AlexWortega/openjev", subfolder=SUB, trust_remote_code=True)
omodel = AutoModelForSequenceClassification.from_pretrained(
    "AlexWortega/openjev", subfolder=SUB, trust_remote_code=True,
    torch_dtype=torch.float16, low_cpu_mem_usage=True).eval()  # fp16: disk+RAM safety on CPU box
template = omodel.config.nli_template
labels = [str(x).lower() for x in omodel.config.label2id]
ent_idx = labels.index("entailment")


def jev_scores(premise, options):
    keys = list(options)
    texts = [template.format(premise=premise, hypothesis=f"{k}: {options[k]}") for k in keys]
    with torch.no_grad():
        logits = []
        for t in texts:  # one by one: CPU RAM safety
            inp = tok(t, return_tensors="pt", truncation=True, max_length=1024)
            logits.append(omodel(**inp).logits[0])
        probs = torch.softmax(torch.stack(logits), dim=0)[:, ent_idx] if False else None
        per = [torch.softmax(l, dim=-1)[ent_idx].item() for l in logits]
    best = keys[int(torch.tensor(per).argmax())]
    return best, max(per)


jev_hits, jev_total, jev_times = 0, 0, []
for title, state, options, expected in CASES:
    t0 = time.time()
    best, conf = jev_scores(state, options)
    dt = time.time() - t0
    exp_key = None
    if expected:
        exp_key = expected if expected in options else None
        jev_total += 1
        mark = "OK " if best == exp_key else "MISS"
        jev_hits += best == exp_key
    else:
        mark = "INFO"
    print(f"[{mark}] {title}: {best} entail={conf:.3f} ({dt:.1f}s)")
    jev_times.append(dt)
t0 = time.time()
best, conf = jev_scores(LONG_DOC, {"weather": "storms, hurricanes, climate",
                                   "finance": "budgets, revenue, planning"})
dt = time.time() - t0
print(f"[{'OK ' if best == 'weather' else 'MISS'}] Long doc: {best} ({dt:.1f}s)")
jev_total += 1
jev_hits += best == "weather"
print(f"JEV: {jev_hits}/{jev_total} correct, total {sum(jev_times):.0f}s")
print("OK - done!")
