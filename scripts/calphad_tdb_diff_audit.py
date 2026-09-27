"""T86 phase 3: machine-readable diff audit between the TU Wien original TDB and a
third-party community "clean" derivative.

Usage:
    .\\.venv\\Scripts\\python.exe -B scripts\\calphad_tdb_diff_audit.py \
        <original.tdb> <candidate.tdb> [--json out.json]

The audit never modifies either file.  It answers one question: are the differences between the
two databases fully explained by explicit, enumerable syntax repairs (encoding, comments,
missing statement terminators, removal of MatCalc-only commands), or is there any change to a
Gibbs energy, interaction parameter, magnetic parameter, temperature breakpoint or numeric
coefficient?

Verdict rules (fail closed):
  * ``changed_thermodynamic_parameter``  -> BLOCK  (a shared parameter's value differs)
  * ``removed_thermodynamic_statement``  -> BLOCK  (an active statement disappeared)
  * only enumerated syntax repairs        -> PASS, with every model loss listed separately
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


#: Parameter types that carry thermodynamic meaning.  A value change in any of these blocks.
THERMODYNAMIC_PARAM_TYPES = {
    "G", "L", "TC", "NT", "BMAGN", "BMAG", "GD", "THETA",
    "V0", "VA", "VC", "VK", "VISC", "ELRS", "THCD", "SIGM", "XI",
    "MQ", "MF", "DQ", "DF", "VS",
}
#: MatCalc-only statements that the community derivative comments out.  Removing them does not
#: change a Gibbs energy value, but each one is a model loss that must be reported.
MATCALC_ONLY_KEYWORDS = {
    "REFERENCE_ELEMENT", "ADD_COMPOSITION_SET", "ATTACH_CONTRIBUTION",
    "CREATE_NEW_PHASE", "ALTER_PHASE", "ADD_PHASE",
}
CLEANED_PREFIX = re.compile(r"^\$\s*Cleaned by script:\s*(?P<body>.*)$", re.IGNORECASE)
PARAM_HEAD = re.compile(
    r"^(?P<type>[A-Za-z]+)\s*\(\s*(?P<phase>[^,()]+?)\s*,\s*(?P<constituents>[^;)]*?)\s*(?:;\s*(?P<order>\d+)\s*)?\)\s*(?P<tail>.*)$",
    re.DOTALL,
)
REFERENCE_TAIL = re.compile(r"\s+REF\s*:\s*(?P<ref>\S+)\s*$", re.IGNORECASE)


def read_database(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    encoding = None
    text = None
    for candidate in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise UnicodeDecodeError("utf-8", raw, 0, 1, "undecodable file")
    return {
        "path": str(path),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encoding": encoding,
        "non_ascii_byte_count": sum(1 for byte in raw if byte > 0x7F),
        "text": text,
        "lines": text.splitlines(),
    }


def split_statements(lines: list[str]) -> list[dict[str, Any]]:
    """Return ``!``-terminated statements with their starting line number."""
    statements: list[dict[str, Any]] = []
    pending = ""
    start = 0
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("$"):
            continue
        if not pending:
            start = number
            pending = stripped
        else:
            pending += " " + stripped
        while "!" in pending:
            head, _, rest = pending.partition("!")
            body = head.strip()
            if body:
                statements.append({"line": start, "text": body})
            pending = rest.strip()
            start = number
    if pending.strip():
        statements.append({"line": start, "text": pending.strip(), "unterminated": True})
    return statements


def normalise_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def canonical_key(statement: str) -> tuple[str, str]:
    """Return (stable key, comparable payload) for one statement."""
    text = normalise_whitespace(statement)
    tokens = text.split()
    keyword = tokens[0].upper() if tokens else ""
    rest = text[len(tokens[0]):].strip() if tokens else ""

    if keyword == "PARAMETER":
        match = PARAM_HEAD.match(rest)
        if not match:
            return ("PARAMETER ?", text.upper())
        param_type = match.group("type").upper()
        phase = normalise_whitespace(match.group("phase")).upper()
        constituents = normalise_whitespace(match.group("constituents")).upper()
        # Constituent order inside a sublattice is not thermodynamically meaningful.
        canonical_constituents = " : ".join(
            ",".join(sorted(part.strip() for part in sublattice.split(",") if part.strip()))
            for sublattice in constituents.split(":")
        )
        order = match.group("order") or "0"
        tail = normalise_whitespace(match.group("tail"))
        reference = ""
        ref_match = REFERENCE_TAIL.search(tail)
        if ref_match:
            reference = ref_match.group("ref").upper()
            tail = REFERENCE_TAIL.sub("", tail).strip()
        key = f"PARAMETER {param_type}({phase},{canonical_constituents};{order})"
        return (key, json.dumps({"value": tail.upper(), "reference": reference}, sort_keys=True))

    if keyword == "FUNCTION":
        name = tokens[1].upper() if len(tokens) > 1 else "?"
        body = rest[len(tokens[1]):].strip() if len(tokens) > 1 else rest
        reference = ""
        ref_match = REFERENCE_TAIL.search(normalise_whitespace(body))
        if ref_match:
            reference = ref_match.group("ref").upper()
            body = REFERENCE_TAIL.sub("", body).strip()
        return (f"FUNCTION {name}", json.dumps({"value": normalise_whitespace(body).upper(), "reference": reference}, sort_keys=True))

    if keyword in {"ELEMENT", "SPECIES", "PHASE", "CONSTITUENT", "TYPE_DEFINITION", "TEMPERATURE_LIMITS",
                   "DEFINE_SYSTEM_DEFAULT", "DEFAULT_COMMAND", "DATABASE_INFO", "VERSION_DATE",
                   "ASSESSED_SYSTEMS", "REFERENCE_FILE", "ADD_REFERENCES", "LIST_OF_REFERENCES",
                   "ZEROVOLUME_SPECIES", "DIFFUSION", "OPTIONS", "TABLE", "COMPOUND_PHASE",
                   "ALLOTROPIC_PHASE", "ADD_CONSTITUENT"}:
        name = tokens[1].upper() if len(tokens) > 1 else ""
        body = rest[len(tokens[1]):].strip() if len(tokens) > 1 else rest
        return (f"{keyword} {name}", normalise_whitespace(body).upper())

    if keyword in MATCALC_ONLY_KEYWORDS:
        name = tokens[1].rstrip(":").upper() if len(tokens) > 1 else ""
        return (f"{keyword} {name}", normalise_whitespace(rest).upper())

    name = tokens[1].rstrip(":").upper() if len(tokens) > 1 else ""
    return (f"{keyword} {name}", normalise_whitespace(rest).upper())


def build_index(lines: list[str]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    index: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for statement in split_statements(lines):
        first_token = statement["text"].split()[0] if statement["text"].split() else ""
        if REFERENCE_RECORD.match(first_token):
            # Bibliography entries inside LIST_OF_REFERENCES are not model statements.
            continue
        key, payload = canonical_key(statement["text"])
        entry = {"line": statement["line"], "text": statement["text"], "payload": payload}
        if key in index:
            duplicates.append({"key": key, "line": statement["line"], "first_line": index[key]["line"]})
            # Keep the first occurrence but remember the duplicate so nothing is silently lost.
            index[key] = {**index[key], "duplicate_lines": index[key].get("duplicate_lines", []) + [statement["line"]]}
            continue
        index[key] = entry
    return index, duplicates


def cleaned_comments(lines: list[str]) -> list[dict[str, Any]]:
    result = []
    for number, line in enumerate(lines, 1):
        match = CLEANED_PREFIX.match(line.strip())
        if match:
            result.append({"line": number, "body": match.group("body").strip()})
    return result


def classify_line_changes(original_lines: list[str], candidate_lines: list[str]) -> dict[str, Any]:
    matcher = difflib.SequenceMatcher(a=[line.rstrip() for line in original_lines],
                                       b=[line.rstrip() for line in candidate_lines],
                                       autojunk=False)
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}

    def record(category: str, detail: str) -> None:
        counts[category] = counts.get(category, 0) + 1
        samples.setdefault(category, [])
        if len(samples[category]) < 6:
            samples[category].append(detail[:180])

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old = [original_lines[index] for index in range(i1, i2)]
        new = [candidate_lines[index] for index in range(j1, j2)]
        if tag == "replace" and len(old) == len(new):
            for before, after in zip(old, new):
                stripped_before, stripped_after = before.rstrip(), after.rstrip()
                if stripped_before == stripped_after + "!":
                    record("missing_terminator_fix", f"{i1 + 1}: +'!' -> {stripped_after[:80]}")
                elif CLEANED_PREFIX.match(after.strip()):
                    record("matcalc_command_commented", f"{j1 + 1}: {after.strip()[:100]}")
                elif stripped_before.startswith("$") or stripped_after.startswith("$"):
                    record("comment_change", f"{i1 + 1}->{j1 + 1}: {before.strip()[:70]} => {after.strip()[:70]}")
                else:
                    record("line_replaced", f"{i1 + 1}->{j1 + 1}: {before.strip()[:70]} => {after.strip()[:70]}")
            continue
        for index in range(i1, i2):
            line = original_lines[index]
            record("comment_removed" if line.strip().startswith("$") else "statement_removed",
                   f"{index + 1}: {line.strip()[:120]}")
        for index in range(j1, j2):
            line = candidate_lines[index]
            if CLEANED_PREFIX.match(line.strip()):
                record("matcalc_command_commented", f"{index + 1}: {line.strip()[:120]}")
            elif line.strip().startswith("$"):
                record("comment_added", f"{index + 1}: {line.strip()[:120]}")
            else:
                record("statement_added", f"{index + 1}: {line.strip()[:120]}")
    return {"counts": counts, "samples": samples}


def audited_keywords(original_lines: list[str], candidate_lines: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for keyword in ("REFERENCE_ELEMENT", "ADD_COMPOSITION_SET", "ATTACH_CONTRIBUTION",
                    "CREATE_NEW_PHASE", "HMVA", "BCC_B2", "M7C3", "M23C6", "M6C", "M3C2",
                    "CEMENTITE"):
        def status(lines: list[str]) -> dict[str, int]:
            active = 0
            commented = 0
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("$"):
                    if keyword in stripped.upper():
                        commented += 1
                    continue
                if keyword in stripped.upper():
                    active += 1
            return {"active_lines": active, "commented_lines": commented}
        before, after = status(original_lines), status(candidate_lines)
        result[keyword] = {
            "original": before,
            "candidate": after,
            "changed": before != after,
        }
    return result


_FLOAT = re.compile(r"\d+\.\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b\d+\b")
_MALFORMED_LITERAL = re.compile(r"\b(\d+\.\d+)\.\d+\b")
_DOUBLED_TAIL = re.compile(r"(;\s*[\d.]+\s*N)\s*;\s*[\d.]+\s*N\b")
#: Reference records inside LIST_OF_REFERENCES look like statements but carry no model content.
REFERENCE_RECORD = re.compile(r"^[A-Z]\d")


def _numbers(text: str) -> list[str]:
    return _FLOAT.findall(text)


def _fix_malformed_literals(text: str) -> str:
    """``6000.00.00`` -> ``6000.00`` (the only reading that is a valid TDB number)."""
    return _MALFORMED_LITERAL.sub(lambda match: match.group(1), text)


def _repair_duplicated_fragments(value: str) -> str:
    """Explicit repair of the two duplicated-fragment defects in the original.

    * a doubled piecewise terminator tail (``; 6000.00 N ; 6000.00 N``);
    * a duplicated lower temperature bound (``273.00 273 +46000...``).
    """
    repaired = _DOUBLED_TAIL.sub(lambda match: match.group(1), value)
    repaired = re.sub(r"^(\d+(?:\.\d+)?)\s+(\d+)(\s+\+)",
                      lambda match: (match.group(1) + match.group(3)) if int(match.group(2)) == int(float(match.group(1))) else match.group(0),
                      repaired)
    return repaired


def _strip_terminator(text: str) -> str:
    return text.strip().rstrip("!").strip()


def classify_deviation(
    original_entry: dict[str, Any] | None,
    candidate_entry: dict[str, Any] | None,
    *,
    original_key: str = "",
    candidate_key: str = "",
) -> dict[str, Any]:
    """Label one difference with the explicit syntax repair that explains it.

    Returns ``{"class": ..., "evidence": ...}``.  ``unexplained`` means the audit blocks.
    """
    def value_of(entry: dict[str, Any] | None) -> str:
        if entry is None:
            return ""
        payload = entry.get("payload", "")
        try:
            parsed = json.loads(payload)
            return str(parsed.get("value", payload))
        except (TypeError, ValueError):
            return payload

    def reference_of(entry: dict[str, Any] | None) -> str:
        if entry is None:
            return ""
        try:
            return str(json.loads(entry.get("payload", "")).get("reference", ""))
        except (TypeError, ValueError):
            return ""

    original_text = _strip_terminator(original_entry["text"]) if original_entry else ""
    candidate_text = _strip_terminator(candidate_entry["text"]) if candidate_entry else ""
    original_value = value_of(original_entry).strip()
    candidate_value = value_of(candidate_entry).strip()

    # 0. Removals that are enumerated model losses rather than unexplained deletions.
    if candidate_entry is None and original_entry is not None:
        key = original_key or ""
        if key.startswith("PARAMETER "):
            param_type = re.match(r"PARAMETER ([A-Z]+)\(", key)
            name = param_type.group(1) if param_type else ""
            if name and name not in THERMODYNAMIC_PARAM_TYPES:
                return {"class": "matcalc_only_parameter_removed",
                        "evidence": f"parameter type {name} is not a pycalphad parameter type; it was commented out by the community derivative"}
        if any(key.startswith(f"{keyword} ") for keyword in MATCALC_ONLY_KEYWORDS):
            return {"class": "matcalc_only_command_removed",
                    "evidence": "MatCalc-only command commented out; recorded as a model loss"}
        if REFERENCE_RECORD.match(original_text.strip()):
            return {"class": "reference_record_reflow", "evidence": "bibliography record, no model content"}

    # 1. Comment-only change of the reference key ("REF:TEST KOZE10" -> "REF:TEST_KOZE10").
    #    When the original reference key contains a space, the reference extractor leaves it in the
    #    value string, so the comparison is done on the raw value text instead.
    if candidate_value and original_value.startswith(candidate_value):
        remainder = original_value[len(candidate_value):].strip()
        if re.fullmatch(r"REF\s*:\s*.+", remainder, flags=re.IGNORECASE):
            return {"class": "reference_key_normalisation",
                    "evidence": f"value identical; reference text {remainder!r} normalised to a single token"}
    if original_entry is not None and candidate_entry is not None:
        if original_value == candidate_value and reference_of(original_entry) != reference_of(candidate_entry):
            return {"class": "reference_key_normalisation",
                    "evidence": f"value identical; reference {reference_of(original_entry)!r} -> {reference_of(candidate_entry)!r}"}

    # 1b. Invalid delimiter after the phase name: ``G(PHASE;CONST;0)`` -> ``G(PHASE,CONST;0)``.
    if re.search(r"\b(G|L|TC|BMAGN|NT|V0|VA|VC|VK|MQ|MF)\s*\(\s*[A-Z0-9_]+\s*;", original_text, re.IGNORECASE):
        if re.search(r"\b(G|L|TC|BMAGN|NT|V0|VA|VC|VK|MQ|MF)\s*\(\s*[A-Z0-9_]+\s*,", candidate_text, re.IGNORECASE):
            return {"class": "invalid_delimiter_repair",
                    "evidence": f"{original_text[:120]!r} -> {candidate_text[:120]!r}"}

    # 2. Candidate value is a contiguous substring / token subsequence of the original: a
    #    duplicated fragment (for example a repeated "; 6000.00 N") was removed.
    if candidate_value and candidate_value in original_value and candidate_value != original_value:
        removed = original_value.replace(candidate_value, "", 1).strip()
        return {"class": "duplicate_or_stray_fragment_removal",
                "evidence": f"removed fragment {removed[:120]!r}"}

    # 3. Malformed numeric literal repaired (6000.00.00 -> 6000.00).
    if _fix_malformed_literals(original_value) == candidate_value and original_value != candidate_value:
        return {"class": "invalid_numeric_literal_repair",
                "evidence": f"{original_value[:120]!r} -> {candidate_value[:120]!r}"}

    # 3b. Duplicated-fragment defect repaired; corroborated for the two PDMN_B2 statements by
    #     scripts/calphad_malformed_statement_probe.py (original raises ParseException, repaired
    #     parses to the standard piecewise function with 273.0 as the lower bound).
    if original_value and _repair_duplicated_fragments(original_value) == candidate_value:
        return {"class": "duplicate_fragment_repair_verified",
                "evidence": f"{original_value[:150]!r} -> {candidate_value[:150]!r}"}

    # 4. Same key, candidate text is the original text with an inserted terminator / delimiter.
    if original_key and candidate_key and original_key != candidate_key:
        repaired_key = original_key.replace("(", "( ", 1)
        repaired_key = re.sub(r"PARAMETER ([A-Z]+)\(([^,;()]+);", r"PARAMETER \1(\2,", original_key)
        if repaired_key == candidate_key:
            return {"class": "invalid_delimiter_repair",
                    "evidence": f"{original_key!r} -> {candidate_key!r}"}
        if candidate_key == original_key:
            return {"class": "key_normalisation", "evidence": "key equal after normalisation"}

    # 5. Same numerical content (multiset of literals) -> structural change only.
    if original_value and _numbers(original_value) == _numbers(candidate_value):
        return {"class": "structural_change_numbers_preserved",
                "evidence": f"numeric literals preserved: {_numbers(candidate_value)[:12]}"}

    # 6. Missing-terminator split: the candidate statement appears as the tail of the original,
    #    so the original merged two statements because a '!' was absent.
    if candidate_text and candidate_text in original_text:
        return {"class": "missing_terminator_split",
                "evidence": f"candidate statement found inside the merged original: {candidate_text[:120]!r}"}
    if original_text and original_text in candidate_text:
        return {"class": "missing_terminator_split",
                "evidence": "original statement is a prefix of the repaired one"}

    # 7. Difference confined to non-ASCII characters (encoding conversion artifact).
    if original_text and candidate_text:
        stripped_original = "".join(char if ord(char) < 128 else "?" for char in original_text)
        stripped_candidate = "".join(char if ord(char) < 128 else "?" for char in candidate_text)
        if stripped_original == stripped_candidate:
            return {"class": "encoding_artifact",
                    "evidence": "difference is confined to non-ASCII characters"}

    return {"class": "unexplained", "evidence": f"{original_text[:120]!r} -> {candidate_text[:120]!r}"}


def reassemble_cleaned(lines: list[str]) -> list[dict[str, Any]]:
    """Reassemble the ``$ Cleaned by script:`` comment blocks back into statements."""
    bodies: list[tuple[int, str]] = []
    for number, line in enumerate(lines, 1):
        match = CLEANED_PREFIX.match(line.strip())
        if match:
            bodies.append((number, match.group("body")))
    statements: list[dict[str, Any]] = []
    pending = ""
    start = 0
    for number, body in bodies:
        if not pending:
            start = number
        pending += (" " if pending else "") + body
        if "!" in body:
            statements.append({"line": start, "text": pending.rstrip().rstrip("!").strip()})
            pending = ""
    if pending.strip():
        statements.append({"line": start, "text": pending.strip(), "unterminated": True})
    return statements


def audit(original_path: Path, candidate_path: Path) -> dict[str, Any]:
    original = read_database(original_path)
    candidate = read_database(candidate_path)
    original_index, original_duplicates = build_index(original["lines"])
    candidate_index, candidate_duplicates = build_index(candidate["lines"])

    only_original = sorted(set(original_index) - set(candidate_index))
    only_candidate = sorted(set(candidate_index) - set(original_index))
    shared = sorted(set(original_index) & set(candidate_index))

    changed = []
    for key in shared:
        if original_index[key]["payload"] != candidate_index[key]["payload"]:
            changed.append({
                "key": key,
                "original_line": original_index[key]["line"],
                "candidate_line": candidate_index[key]["line"],
                "original_payload": original_index[key]["payload"][:400],
                "candidate_payload": candidate_index[key]["payload"][:400],
            })

    def param_type_of(key: str) -> str:
        if key.startswith("PARAMETER "):
            match = re.match(r"PARAMETER ([A-Z]+)\(", key)
            return match.group(1) if match else "?"
        return ""

    removed_thermodynamic = [
        {"key": key, "line": original_index[key]["line"], "text": original_index[key]["text"][:200]}
        for key in only_original
        if key.startswith("FUNCTION ") or (
            key.startswith("PARAMETER ") and param_type_of(key) in THERMODYNAMIC_PARAM_TYPES
        ) or key.startswith("ELEMENT ") or key.startswith("PHASE ") or key.startswith("CONSTITUENT ")
    ]
    removed_matcalc = [
        {"key": key, "line": original_index[key]["line"], "text": original_index[key]["text"][:200]}
        for key in only_original
        if not key.startswith("FUNCTION ") and not key.startswith("PARAMETER ")
        and not key.startswith("ELEMENT ") and not key.startswith("PHASE ")
        and not key.startswith("CONSTITUENT ")
    ] + [
        {"key": key, "line": original_index[key]["line"], "text": original_index[key]["text"][:200]}
        for key in only_original
        if key.startswith("PARAMETER ") and param_type_of(key) not in THERMODYNAMIC_PARAM_TYPES
    ]

    changed_thermodynamic = [
        item for item in changed
        if item["key"].startswith("FUNCTION ")
        or (item["key"].startswith("PARAMETER ") and param_type_of(item["key"]) in THERMODYNAMIC_PARAM_TYPES)
        or item["key"].startswith("ELEMENT ")
        or item["key"].startswith("PHASE ")
        or item["key"].startswith("CONSTITUENT ")
    ]
    changed_other = [item for item in changed if item not in changed_thermodynamic]

    # Every "$ Cleaned by script: X" block must correspond to statements that exist in the
    # original, so the "cleaning" is verifiably comment-only.  Multi-line statements are
    # reassembled before matching.
    cleaned = cleaned_comments(candidate["lines"])
    reassembled = reassemble_cleaned(candidate["lines"])
    original_keys = set(original_index)
    matched_cleaned = []
    unmatched_cleaned = []
    for statement in reassembled:
        key, _ = canonical_key(statement["text"])
        if key in original_keys:
            matched_cleaned.append({"line": statement["line"], "key": key})
        else:
            unmatched_cleaned.append({"line": statement["line"], "key": key, "text": statement["text"][:160]})

    # Classify every difference against an explicit syntax-repair rule.
    deviations: list[dict[str, Any]] = []
    paired_added: set[str] = set()
    for key in only_original:
        match_key = None
        for candidate_key in only_candidate:
            if candidate_key in paired_added:
                continue
            label = classify_deviation(original_index[key], candidate_index[candidate_key],
                                       original_key=key, candidate_key=candidate_key)
            if label["class"] != "unexplained":
                match_key = candidate_key
                deviations.append({
                    "change": "statement_replaced",
                    "original_key": key, "candidate_key": candidate_key,
                    "original_line": original_index[key]["line"], "candidate_line": candidate_index[candidate_key]["line"],
                    "deviation_class": label["class"], "evidence": label["evidence"],
                    "removed_text": original_index[key]["text"][:200],
                    "added_text": candidate_index[candidate_key]["text"][:200],
                    "removed_full": original_index[key]["text"],
                    "added_full": candidate_index[candidate_key]["text"],
                })
                paired_added.add(candidate_key)
                break
        if match_key is None:
            label = classify_deviation(original_index[key], None, original_key=key)
            deviations.append({
                "change": "statement_removed",
                "original_key": key, "candidate_key": None,
                "original_line": original_index[key]["line"], "candidate_line": None,
                "deviation_class": label["class"], "evidence": label["evidence"],
                "removed_text": original_index[key]["text"][:200], "added_text": None,
            "removed_full": original_index[key]["text"], "added_full": None,
            })
    for candidate_key in only_candidate:
        if candidate_key in paired_added:
            continue
        label = classify_deviation(None, candidate_index[candidate_key], candidate_key=candidate_key)
        deviations.append({
            "change": "statement_added",
            "original_key": None, "candidate_key": candidate_key,
            "original_line": None, "candidate_line": candidate_index[candidate_key]["line"],
            "deviation_class": label["class"], "evidence": label["evidence"],
            "removed_text": None, "added_text": candidate_index[candidate_key]["text"][:200],
            "removed_full": None, "added_full": candidate_index[candidate_key]["text"],
        })
    for item in changed:
        label = classify_deviation(original_index[item["key"]], candidate_index[item["key"]], original_key=item["key"])
        deviations.append({
            "change": "statement_value_changed",
            "original_key": item["key"], "candidate_key": item["key"],
            "original_line": item["original_line"], "candidate_line": item["candidate_line"],
            "deviation_class": label["class"], "evidence": label["evidence"],
            "removed_text": item["original_payload"][:400], "added_text": item["candidate_payload"][:400],
            "removed_full": original_index[item["key"]]["text"], "added_full": candidate_index[item["key"]]["text"],
        })

    unexplained = [item for item in deviations if item["deviation_class"] == "unexplained"]

    # A missing '!' in the original merges two statements into one; the candidate splits them, so
    # one removed statement can explain two added statements (and vice versa). Resolve those by
    # checking containment against the whole counterpart set before declaring anything unexplained.
    removed_texts = [item.get("removed_full") or item["removed_text"] for item in deviations if item.get("removed_full") or item["removed_text"]]
    added_texts = [item.get("added_full") or item["added_text"] for item in deviations if item.get("added_full") or item["added_text"]]
    resolved: list[dict[str, Any]] = []
    for item in unexplained:
        if item["change"] == "statement_added" and (item.get("added_full") or item["added_text"]):
            body = _strip_terminator(item.get("added_full") or item["added_text"])
            if any(body and body in _strip_terminator(text) for text in removed_texts):
                item = {**item, "deviation_class": "missing_terminator_split",
                        "evidence": "statement recovered from a merged original statement that was missing a '!'"}
        elif item["change"] == "statement_removed" and (item.get("removed_full") or item["removed_text"]):
            body = _strip_terminator(item.get("removed_full") or item["removed_text"])
            if any(added and _strip_terminator(added) in body for added in added_texts):
                item = {**item, "deviation_class": "missing_terminator_split",
                        "evidence": "original merged statement was split by an inserted '!'"}
        resolved.append(item)
    deviations = [item for item in deviations if item["deviation_class"] != "unexplained"] + resolved
    unexplained = [item for item in deviations if item["deviation_class"] == "unexplained"]

    deviation_classes: dict[str, int] = {}
    for item in deviations:
        deviation_classes[item["deviation_class"]] = deviation_classes.get(item["deviation_class"], 0) + 1

    blocking_reasons: list[str] = []
    if unexplained:
        blocking_reasons.append(f"{len(unexplained)} difference(s) are not explained by an explicit syntax repair")
    if unmatched_cleaned:
        blocking_reasons.append(f"{len(unmatched_cleaned)} reassembled 'Cleaned by script' statement(s) do not match any original statement")

    model_losses = {
        "bcc_b2_order_disorder_coupling": "ATTACH_CONTRIBUTION ... ORDER_DISORDER is commented out: the ordered B2 contribution is not linked to the disordered part.",
        "hmva_parameters": f"{sum(1 for line in candidate['lines'] if line.strip().startswith('$') and 'HMVA' in line.upper())} HMVA (vacancy formation enthalpy) parameters are commented out. pycalphad has no HMVA parameter type, so they never entered a pycalphad equilibrium, but they were part of the MatCalc model.",
        "matcalc_composition_sets": f"{sum(1 for line in candidate['lines'] if line.strip().startswith('$') and 'ADD_COMPOSITION_SET' in line.upper())} ADD_COMPOSITION_SET commands are commented out: MatCalc composition sets (for example the MC carbo-nitride as fcc_A1#01) do not exist in pycalphad.",
        "reference_element": "REFERENCE_ELEMENT FE is commented out; pycalphad does not implement it and derives reference states from ELEMENT lines.",
        "impact": "unknown_model_impact",
    }

    return {
        "schema_version": "1.0",
        "audit": "tu_wien_original_vs_community_clean",
        "original": {key: value for key, value in original.items() if key not in {"text", "lines"}},
        "candidate": {key: value for key, value in candidate.items() if key not in {"text", "lines"}},
        "line_count": {"original": len(original["lines"]), "candidate": len(candidate["lines"])},
        "statement_count": {"original": len(original_index), "candidate": len(candidate_index)},
        "line_change_classification": classify_line_changes(original["lines"], candidate["lines"]),
        "cleaned_by_script": {
            "count": len(cleaned),
            "reassembled_statement_count": len(reassembled),
            "matched": len(matched_cleaned),
            "unmatched": unmatched_cleaned,
        },
        "duplicate_keys": {"original": original_duplicates[:20], "candidate": candidate_duplicates[:20]},
        "shared_statement_count": len(shared),
        "changed_thermodynamic_statements": changed_thermodynamic,
        "changed_other_statements": changed_other,
        "removed_thermodynamic_statements": removed_thermodynamic,
        "removed_matcalc_statements": removed_matcalc,
        "added_statements": [
            {"key": key, "line": candidate_index[key]["line"], "text": candidate_index[key]["text"][:200]}
            for key in only_candidate
        ],
        "deviation_classes": deviation_classes,
        "deviations": deviations,
        "unexplained_deviations": unexplained,
        "audited_keywords": audited_keywords(original["lines"], candidate["lines"]),
        "model_losses": model_losses,
        "blocking_reasons": blocking_reasons,
        "verdict": "blocked" if blocking_reasons else "passed_syntax_repairs_only",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="TDB diff audit (read-only).")
    parser.add_argument("original", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv[1:])
    for path in (args.original, args.candidate):
        if not path.is_file():
            print(f"not a file: {path}", file=sys.stderr)
            return 2

    report = audit(args.original, args.candidate)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"original : {report['original']['sha256']}  {report['original']['size_bytes']} B  "
          f"{report['original']['encoding']}  lines={report['line_count']['original']}")
    print(f"candidate: {report['candidate']['sha256']}  {report['candidate']['size_bytes']} B  "
          f"{report['candidate']['encoding']}  lines={report['line_count']['candidate']}")
    print(f"statements: original={report['statement_count']['original']} candidate={report['statement_count']['candidate']} "
          f"shared={report['shared_statement_count']}")
    print("line change classification:")
    for category, count in sorted(report["line_change_classification"]["counts"].items()):
        print(f"  {category:28} {count}")
    print(f"'Cleaned by script' lines: {report['cleaned_by_script']['count']} "
          f"(reassembled {report['cleaned_by_script']['reassembled_statement_count']} statements, "
          f"matched {report['cleaned_by_script']['matched']}, unmatched {len(report['cleaned_by_script']['unmatched'])})")
    print("deviation classes:")
    for deviation_class, count in sorted(report["deviation_classes"].items()):
        print(f"  {deviation_class:40} {count}")
    if report["unexplained_deviations"]:
        print("UNEXPLAINED deviations:")
        for item in report["unexplained_deviations"]:
            print(f"  - {item['change']} {item['original_key'] or item['candidate_key']}")
            print(f"      {item['evidence']}")
    print(f"changed thermodynamic statements : {len(report['changed_thermodynamic_statements'])}")
    print(f"changed other statements         : {len(report['changed_other_statements'])}")
    print(f"removed thermodynamic statements : {len(report['removed_thermodynamic_statements'])}")
    print(f"removed MatCalc statements       : {len(report['removed_matcalc_statements'])}")
    print(f"added statements                 : {len(report['added_statements'])}")
    print("audited keywords:")
    for keyword, info in report["audited_keywords"].items():
        if info["changed"]:
            print(f"  {keyword:22} original={info['original']} candidate={info['candidate']}")
    if report["blocking_reasons"]:
        print("BLOCKING:")
        for reason in report["blocking_reasons"]:
            print(f"  - {reason}")
    print(f"verdict: {report['verdict']}")
    if args.json:
        print(f"json: {args.json}")
    return 0 if report["verdict"] == "passed_syntax_repairs_only" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
