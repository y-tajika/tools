import csv
import difflib
import os
import random
import sys
import time
from datetime import datetime

FIELDNAMES = [
    "score",
    "timestamp",
    "elapsed",
    "cps",
    "accuracy",
    "difficulty",
    "correct",
    "mistakes",
    "typed_chars",
    "target_chars",
]

def compare_text(target, typed):
    # Levenshtein distance to avoid penalizing single insertions too harshly.
    if not target and not typed:
        return 0, 0

    prev = list(range(len(typed) + 1))
    for i, t_char in enumerate(target, start=1):
        curr = [i]
        for j, u_char in enumerate(typed, start=1):
            cost = 0 if t_char == u_char else 1
            curr.append(
                min(
                    prev[j] + 1,      # deletion
                    curr[j - 1] + 1,  # insertion
                    prev[j - 1] + cost,  # substitution
                )
            )
        prev = curr

    distance = prev[-1]
    correct = max(len(target) - distance, 0)
    mistakes = distance
    return correct, mistakes

def calculate_cps(typed_chars, elapsed_seconds):
    if elapsed_seconds <= 0:
        return 0.0
    return typed_chars / elapsed_seconds

def load_samples(path):
    samples = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if text:
                    samples.append(text)
    except FileNotFoundError:
        pass
    return samples

def get_timestamp_label(now=None):
    now = now or datetime.now()
    return now.strftime("%y%m%d%H%M")

def calculate_difficulty_factor(text):
    if not text:
        return 1.0

    def char_group(ch):
        if ch == " ":
            return "space"
        if ch.islower():
            return "lower"
        if ch.isupper():
            return "upper"
        if ch.isdigit():
            return "digit"
        return f"symbol:{ch}"

    group_num = 0
    prev_group = None
    length = 0
    for ch in text:
        group = char_group(ch)
        if group == "space":
            continue
        length += 1
        if group.startswith("symbol:"):
            group_num += 1
            prev_group = group
            continue
        if group != prev_group:
            group_num += 1
            prev_group = group

    if length == 0:
        return 1.0
    return (length + group_num) / length

def append_result(csv_path, row):
    file_exists = os.path.exists(csv_path)
    needs_header = (not file_exists) or os.path.getsize(csv_path) == 0
    with open(csv_path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow(row)

def ensure_results_schema(csv_path):
    if not os.path.exists(csv_path):
        return

    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        return

    header = rows[0]
    old_header = [
        "timestamp",
        "elapsed",
        "cps",
        "accuracy",
        "correct",
        "mistakes",
        "typed_chars",
        "target_chars",
    ]

    mid_header = [
        "timestamp",
        "elapsed",
        "cps",
        "accuracy",
        "difficulty",
        "correct",
        "mistakes",
        "typed_chars",
        "target_chars",
    ]

    if header == FIELDNAMES:
        return

    if header not in (old_header, mid_header):
        return

    normalized = []
    for row in rows[1:]:
        if len(row) == len(old_header):
            mapped = dict(zip(old_header, row))
            mapped["difficulty"] = "1.000"
            mapped["score"] = "0.00"
            normalized.append(mapped)
        elif len(row) == len(mid_header):
            mapped = dict(zip(mid_header, row))
            mapped["score"] = "0.00"
            normalized.append(mapped)
        elif len(row) == len(FIELDNAMES):
            normalized.append(dict(zip(FIELDNAMES, row)))

    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in normalized:
            writer.writerow(row)

def load_results(csv_path):
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)

def reset_results(csv_path):
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()

def print_usage():
    print("Usage: typist [--reset|-reset] [--help|-h]")
    print("  --reset, -reset  Clear results.csv and exit")
    print("  --help, -h       Show this help and exit")

def calculate_score(cps, accuracy_percent, difficulty_factor):
    acc_rate = accuracy_percent / 100.0
    base = cps * (acc_rate ** 2) * 100.0
    return base * difficulty_factor

def build_diff_view(target, typed, width=120):
    if target == typed:
        return []

    matcher = difflib.SequenceMatcher(None, target, typed)
    t_view = []
    u_view = []
    m_view = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        t_chunk = target[i1:i2].replace("\n", "\\n")
        u_chunk = typed[j1:j2].replace("\n", "\\n")

        if tag == "equal":
            t_view.append(t_chunk)
            u_view.append(u_chunk)
            m_view.append(" " * len(t_chunk))
            continue

        if tag == "replace":
            max_len = max(len(t_chunk), len(u_chunk))
            t_view.append(t_chunk.ljust(max_len))
            u_view.append(u_chunk.ljust(max_len))
            m_view.append("^" * max_len)
        elif tag == "delete":
            t_view.append(t_chunk)
            u_view.append(" " * len(t_chunk))
            m_view.append("-" * len(t_chunk))
        elif tag == "insert":
            t_view.append(" " * len(u_chunk))
            u_view.append(u_chunk)
            m_view.append("+" * len(u_chunk))

    t_line = "".join(t_view)
    u_line = "".join(u_view)
    m_line = "".join(m_view)

    output = []
    for start in range(0, max(len(t_line), len(u_line), len(m_line)), width):
        end = start + width
        output.append("Target: " + t_line[start:end])
        output.append("Typed : " + u_line[start:end])
        output.append("Diff  : " + m_line[start:end])
    return output

def print_ranking(rows):
    if not rows:
        print("\nRanking: no results yet.")
        return

    def to_float(value, default=0.0):
        try:
            return float(value)
        except ValueError:
            return default

    def calc_score(row):
        stored = to_float(row.get("score", "0"))
        if stored > 0:
            return stored
        cps = to_float(row.get("cps", "0"))
        accuracy = to_float(row.get("accuracy", "0"))
        difficulty = to_float(row.get("difficulty", "1"), 1.0)
        return calculate_score(cps, accuracy, difficulty)

    ranked = sorted(rows, key=calc_score, reverse=True)

    print("\nRanking (by Score):")
    for idx, row in enumerate(ranked[:10], start=1):
        cps = to_float(row.get("cps", "0"))
        accuracy = to_float(row.get("accuracy", "0"))
        difficulty = to_float(row.get("difficulty", "1"), 1.0)
        score = calc_score(row)
        print(
            f"#{idx:02d} {row.get('timestamp','----')} | "
            f"Score {score:.2f} | "
            f"Diff {difficulty:.2f} | "
            f"CPS {cps:.2f} | "
            f"Acc {accuracy:.2f}% | "
            f"Miss {to_float(row.get('mistakes','0')):.0f} | "
            f"Time {to_float(row.get('elapsed','0')):.2f}s"
        )

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    samples_path = os.path.join(script_dir, "sentences.txt")
    results_path = os.path.join(script_dir, "results.csv")

    args = sys.argv[1:]
    if args:
        known = {"-reset", "--reset", "-h", "--help"}
        unknown = [arg for arg in args if arg not in known]
        if unknown:
            print("Unknown option(s): " + " ".join(unknown))
            print_usage()
            return
        if "-h" in args or "--help" in args:
            print_usage()
            return
        if "-reset" in args or "--reset" in args:
            reset_results(results_path)
            print("results.csv をリセットしました。")
            return

    ensure_results_schema(results_path)
    samples = load_samples(samples_path)
    if not samples:
        print("sentences.txt が見つからないか空です。")
        return

    round_count = 3

    print("Typing Practice (CMD)")
    print("Press Enter to start each round. Type exactly what you see.")

    while True:
        if len(samples) >= round_count:
            chosen = random.sample(samples, round_count)
        else:
            chosen = [random.choice(samples) for _ in range(round_count)]
        target = " ".join(chosen)
        print("\nTarget:")
        print(target)
        input("\nPress Enter to begin...")

        start = time.perf_counter()
        typed = input("\nType here: ")
        elapsed = time.perf_counter() - start

        correct, mistakes = compare_text(target, typed)
        accuracy = (correct / len(target)) * 100.0 if len(target) else 0.0
        cps = calculate_cps(len(typed), elapsed)
        difficulty = calculate_difficulty_factor(target)
        score = calculate_score(cps, accuracy, difficulty)
        print("\nResults:")
        print(f"Time: {elapsed:.2f} sec")
        print(f"Chars/sec: {cps:.2f}")
        print(f"Accuracy: {accuracy:.2f}%")
        print(f"Difficulty: {difficulty:.2f}")
        print(f"Correct chars: {correct}")
        print(f"Mistakes: {mistakes}")
        print(f"Typed chars: {len(typed)}")
        print(f"Target chars: {len(target)}")
        print(f"Score: {score:.2f}")

        diff_view = build_diff_view(target, typed)
        if diff_view:
            print("\nDifferences:")
            for line in diff_view:
                print(line)

        row = {
            "score": f"{score:.6f}",
            "timestamp": get_timestamp_label(),
            "elapsed": f"{elapsed:.4f}",
            "cps": f"{cps:.6f}",
            "accuracy": f"{accuracy:.6f}",
            "difficulty": f"{difficulty:.6f}",
            "correct": str(correct),
            "mistakes": str(mistakes),
            "typed_chars": str(len(typed)),
            "target_chars": str(len(target)),
        }
        append_result(results_path, row)

        again = input("\nAnother round? (y/n): ").strip().lower()
        if again != "y":
            print_ranking(load_results(results_path))
            break

if __name__ == "__main__":
    main()
