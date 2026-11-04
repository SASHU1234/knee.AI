"""Longitudinal comparison of stored examinations (descriptive, never diagnostic).

The platform has no patient ID: a study carries only the patient name, age, sex, side and
modality entered at upload, and is owned by one user account. "Same patient" can therefore only
mean "same account, same normalised name and sex" - the service says so in every response
(`identity_basis`) and refuses comparisons that contradict the record (different name/sex, other
side, other modality, different measurement method, non-chronological order, duplicated image,
decreasing age). Differences are plain arithmetic on the stored values; nothing is interpolated,
predicted or interpreted as disease progression.
"""

import datetime
from typing import Dict, List, Optional, Tuple

EXPLICIT_IDENTITY_BASIS = ("Both records carry the same explicit synthetic_patient_id (synthetic demonstration data); "
                           "patient identity is NOT inferred from name or sex.")
IDENTITY_BASIS = ("Patient identity is inferred from the name and sex entered at upload within one account; "
                  "the platform stores no patient ID, so identity is not independently verified.")

# (id, label, unit, getter-path) - all stored numbers, never recomputed or rounded here.
MEASUREMENTS: List[Tuple[str, str, str, Tuple]] = [
    ("meniscus:anterior_horn", "Meniscus thickness - anterior horn", "mm", ("loc", "anterior_horn")),
    ("meniscus:mid_body", "Meniscus thickness - mid-body", "mm", ("loc", "mid_body")),
    ("meniscus:posterior_horn", "Meniscus thickness - posterior horn", "mm", ("loc", "posterior_horn")),
    ("meniscus:mean", "Meniscus thickness - mean", "mm", ("path", "meniscus", "assessment", "mean_thickness_mm")),
    ("meniscus:min", "Meniscus thickness - minimum", "mm", ("path", "meniscus", "assessment", "min_thickness_mm")),
    ("bone:femoral_ml_mm", "Femoral width (ML)", "mm", ("path", "bone_measurements", "femoral_ml_mm")),
    ("bone:femoral_ap_mm", "Femoral width (AP)", "mm", ("path", "bone_measurements", "femoral_ap_mm")),
    ("bone:tibial_ml_mm", "Tibial width (ML)", "mm", ("path", "bone_measurements", "tibial_ml_mm")),
    ("bone:tibial_ap_mm", "Tibial width (AP)", "mm", ("path", "bone_measurements", "tibial_ap_mm")),
    ("bone:tibial_slope_deg", "Tibial slope", "deg", ("path", "bone_measurements", "tibial_slope_deg")),
]
MEASUREMENT_IDS = {m[0] for m in MEASUREMENTS}


# ------------------------------------------------------------------------ helpers
def normalise_name(name: Optional[str]) -> str:
    return " ".join((name or "").casefold().split())


def explicit_id(record: Dict) -> Optional[str]:
    v = record.get("synthetic_patient_id")
    return str(v).strip() or None if v is not None else None


def identity_basis(a: Dict, b: Dict) -> str:
    return EXPLICIT_IDENTITY_BASIS if explicit_id(a) and explicit_id(a) == explicit_id(b) else IDENTITY_BASIS


def same_patient(a: Dict, b: Dict) -> Tuple[bool, str]:
    """An explicit synthetic_patient_id decides identity. If either record has one, the other must have the
    same one: name/sex are then irrelevant (a namesake with a different id is a different patient).
    Without ids, fall back to the account-scoped name+sex rule."""
    ia, ib = explicit_id(a), explicit_id(b)
    if ia or ib:
        if ia and ia == ib:
            return True, "Same explicit synthetic patient ID ({}).".format(ia)
        return False, "Different (or missing) explicit patient ID ({} vs {}): different patients are never compared.".format(ia or "none", ib or "none")
    ok = patient_key(a) == patient_key(b) and patient_key(a)[0] != ""
    return ok, "Name and sex match." if ok else "Patient name or sex differs: different patients are never compared."


def exam_time(record: Dict) -> Optional[datetime.datetime]:
    """When the examination took place (examined_at), falling back to the analysis time (created_at)."""
    return parse_time(record.get("examined_at")) or parse_time(record.get("created_at"))


def patient_key(record: Dict) -> Tuple[str, str]:
    p = record.get("patient") or {}
    return normalise_name(p.get("name")), (p.get("sex") or "").casefold()


def parse_time(value: Optional[str]) -> Optional[datetime.datetime]:
    """ISO timestamp -> naive UTC-comparable datetime (None when missing/invalid)."""
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def _number(x) -> Optional[float]:
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def get_value(record: Dict, spec: Tuple) -> Optional[float]:
    if spec[0] == "loc":
        for m in ((record.get("meniscus") or {}).get("measurements") or []):
            if m.get("location") == spec[1]:
                return _number(m.get("thickness_mm"))
        return None
    cur = record
    for key in spec[1:]:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return _number(cur)


def method_signature(record: Dict) -> Tuple[str, str]:
    prov = record.get("provenance") or {}
    origin = "sidecar" if record.get("sample_source") else ("synthetic" if record.get("synthetic") else "simulation")
    return origin, str(prov.get("method") or "")


def summary(record: Dict) -> Dict:
    p = record.get("patient") or {}
    men = record.get("meniscus") or {}
    variants = (record.get("images") or {}).get("variants") or {}
    return {
        "study_id": record.get("analysis_id"),
        "examined_at": record.get("examined_at") or record.get("created_at"),
        "synthetic_patient_id": explicit_id(record),
        "age": p.get("age"),
        "sex": p.get("sex"),
        "side": p.get("affected_side"),
        "modality": p.get("imaging_type"),
        "image_view": record.get("imaging_view"),  # None when the platform has no view recorded
        "image_url": record.get("demo_image_url"),
        "classification": (men.get("assessment") or {}).get("classification"),
        "mean_thickness_mm": (men.get("assessment") or {}).get("mean_thickness_mm"),
        "image": variants.get("none"),
        "method": method_signature(record)[1] or None,
        "synthetic": bool(record.get("synthetic")),
    }


# ------------------------------------------------------------ comparability checks
def check_comparability(prev: Dict, cur: Dict) -> Dict:
    """Run every comparability rule. `comparable` is False when any blocking rule fails."""
    checks: List[Dict] = []

    def add(name, ok, detail, blocking=True):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "blocking": blocking})

    pp, cp = prev.get("patient") or {}, cur.get("patient") or {}

    add("different_records", prev.get("analysis_id") != cur.get("analysis_id"),
        "The two selections are the same study." if prev.get("analysis_id") == cur.get("analysis_id") else "Two distinct studies.")
    ok_pat, pat_detail = same_patient(prev, cur)
    add("same_patient", ok_pat, pat_detail)
    add("same_side", (pp.get("affected_side") or "").casefold() == (cp.get("affected_side") or "").casefold()
        and bool(pp.get("affected_side")),
        "Both studies are {}.".format(cp.get("affected_side")) if pp.get("affected_side") == cp.get("affected_side")
        else "Anatomical side differs ({} vs {}).".format(pp.get("affected_side"), cp.get("affected_side")))
    add("same_modality", (pp.get("imaging_type") or "").casefold() == (cp.get("imaging_type") or "").casefold()
        and bool(pp.get("imaging_type")),
        "Both are {}.".format(cp.get("imaging_type")) if pp.get("imaging_type") == cp.get("imaging_type")
        else "Imaging modality differs ({} vs {}).".format(pp.get("imaging_type"), cp.get("imaging_type")))
    add("same_measurement_method", method_signature(prev) == method_signature(cur),
        "Measurements come from the same method." if method_signature(prev) == method_signature(cur)
        else "Measurement method differs between the studies, so values are not directly comparable.")
    add("units_compatible", True, "All compared measurements use the same units (mm; degrees for slope).")

    t0, t1 = exam_time(prev), exam_time(cur)
    ordered = t0 is not None and t1 is not None and t0 < t1
    add("chronological_order", ordered,
        "The previous study precedes the current one." if ordered else
        ("Examination time missing." if t0 is None or t1 is None else "The 'previous' study is not earlier than the 'current' one."))

    dup = bool(prev.get("image_hash")) and prev.get("image_hash") == cur.get("image_hash")
    add("not_duplicate_image", not dup,
        "Different image content." if not dup else "Both studies use an identical image (duplicate examination).")

    a0, a1 = _number(pp.get("age")), _number(cp.get("age"))
    age_ok = a0 is None or a1 is None or a1 >= a0
    add("age_consistent", age_ok, "Age is consistent with the chronological order." if age_ok
        else "Recorded age decreases between the studies, which contradicts a single patient.")

    v0, v1 = prev.get("imaging_view"), cur.get("imaging_view")
    if v0 and v1:
        add("same_imaging_view", str(v0).casefold() == str(v1).casefold(),
            "Both studies use the view '{}'.".format(v1) if str(v0).casefold() == str(v1).casefold()
            else "Imaging view differs ({} vs {}).".format(v0, v1))
    else:
        add("imaging_view_recorded", False,
            "The imaging view is not recorded for both studies, so positioning differences cannot be excluded.", blocking=False)
    if not (explicit_id(prev) and explicit_id(prev) == explicit_id(cur)):
        add("identity_basis", False, IDENTITY_BASIS, blocking=False)
    sc0 = (prev.get("provenance") or {}).get("scale_px_per_mm")
    sc1 = (cur.get("provenance") or {}).get("scale_px_per_mm")
    if sc0 is not None and sc1 is not None and sc0 != sc1:
        add("pixel_scale", False, "Pixel scale differs ({} vs {} px/mm).".format(sc0, sc1), blocking=False)

    blocking = [c["detail"] for c in checks if c["blocking"] and not c["ok"]]
    warnings = [c["detail"] for c in checks if not c["blocking"] and not c["ok"]]
    return {"comparable": not blocking, "blocking_reasons": blocking, "warnings": warnings, "checks": checks}


# ----------------------------------------------------------------- arithmetic
def difference(previous: Optional[float], current: Optional[float]) -> Dict:
    """Absolute and percentage difference from the original (unrounded) values."""
    if previous is None or current is None:
        return {"difference": None, "percentage_difference": None,
                "note": "A value is missing in one of the studies."}
    diff = current - previous
    if previous == 0:
        return {"difference": diff, "percentage_difference": None,
                "note": "Percentage difference is undefined because the previous value is zero."}
    return {"difference": diff, "percentage_difference": (current - previous) / previous * 100, "note": None}


def compare(prev: Dict, cur: Dict) -> Dict:
    check = check_comparability(prev, cur)
    result = {
        "previous": summary(prev), "current": summary(cur),
        "identity_basis": identity_basis(prev, cur),
        "comparability": check,
        "measurements": [],
        "interpretation_note": "Observed measurement difference between the selected examinations. It is a "
                               "descriptive number, not a statement of disease progression or improvement.",
    }
    if not check["comparable"]:
        return result
    for mid, label, unit, spec in MEASUREMENTS:
        v0, v1 = get_value(prev, spec), get_value(cur, spec)
        row = {"id": mid, "label": label, "unit": unit, "previous": v0, "current": v1}
        row.update(difference(v0, v1))
        row["available"] = v0 is not None and v1 is not None
        result["measurements"].append(row)
    return result


# ------------------------------------------------------------- timeline / series
def candidate_timeline(current: Dict, others: List[Dict]) -> Dict:
    """All studies that could be compared with `current`, oldest first, each with its verdict."""
    rows, seen = [], set()
    for r in [current] + list(others):
        sid = r.get("analysis_id")
        if sid in seen:
            continue
        seen.add(sid)
        entry = summary(r)
        entry["is_current"] = sid == current.get("analysis_id")
        if not entry["is_current"]:
            t_r, t_c = exam_time(r), exam_time(current)
            earlier = t_r is not None and t_c is not None and t_r < t_c
            first, second = (r, current) if earlier else (current, r)
            verdict = check_comparability(first, second)
            entry["relation"] = "earlier" if earlier else "later"
            entry["comparable_with_current"] = verdict["comparable"]
            entry["reasons"] = verdict["blocking_reasons"]
        rows.append(entry)
    rows.sort(key=lambda e: (parse_time(e["examined_at"]) or datetime.datetime.max, str(e["study_id"])))
    explicit = bool(explicit_id(current))
    return {"identity_basis": EXPLICIT_IDENTITY_BASIS if explicit else IDENTITY_BASIS, "studies": rows}


def build_series(current: Dict, others: List[Dict], measurement_id: str) -> Dict:
    """Chronological values of one measurement across studies comparable with `current`."""
    if measurement_id not in MEASUREMENT_IDS:
        raise ValueError("Unknown measurement.")
    spec = next(m for m in MEASUREMENTS if m[0] == measurement_id)
    points, excluded, seen_hash = [], [], set()
    pool = [current] + [o for o in others if o.get("analysis_id") != current.get("analysis_id")]
    for r in pool:
        if r is not current:
            t_r, t_c = exam_time(r), exam_time(current)
            first, second = (r, current) if (t_r and t_c and t_r < t_c) else (current, r)
            verdict = check_comparability(first, second)
            # duplicates/chronology of the pair are handled below; other blockers exclude the study
            hard = [c for c in verdict["checks"] if c["blocking"] and not c["ok"]
                    and c["name"] not in ("chronological_order", "not_duplicate_image")]
            if hard:
                excluded.append({"study_id": r.get("analysis_id"), "reasons": [c["detail"] for c in hard]})
                continue
        h = r.get("image_hash")
        if h and h in seen_hash:
            excluded.append({"study_id": r.get("analysis_id"), "reasons": ["Duplicate of an already included examination."]})
            continue
        if h:
            seen_hash.add(h)
        if exam_time(r) is None:
            excluded.append({"study_id": r.get("analysis_id"), "reasons": ["Examination time missing."]})
            continue
        points.append({"study_id": r.get("analysis_id"), "examined_at": r.get("examined_at") or r.get("created_at"),
                       "value": get_value(r, spec[3]), "is_current": r is current})
    points.sort(key=lambda p: parse_time(p["examined_at"]))
    with_values = [p for p in points if p["value"] is not None]
    return {
        "measurement": {"id": spec[0], "label": spec[1], "unit": spec[2]},
        "identity_basis": EXPLICIT_IDENTITY_BASIS if explicit_id(current) else IDENTITY_BASIS,
        "points": points,                 # missing values stay None: never interpolated
        "excluded": excluded,
        "trend_available": len(with_values) >= 3,
        "note": ("Direct comparison only: fewer than three examinations with a value." if len(with_values) < 3
                 else "Plotted values are the stored measurements at the actual examination dates; "
                      "missing values are not interpolated and nothing is extrapolated."),
    }
