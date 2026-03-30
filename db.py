"""Database helpers for plate_overview_site (no user auth — single local user, id=1)."""

import gzip
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime

import numpy as np
from werkzeug.utils import secure_filename

from config import AUTH_DB_PATH, SAVED_RUNS_DIR, normalize_time_unit
import state as _state

LOCAL_USER_ID = 1


def get_db_conn():
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def current_user_id():
    return LOCAL_USER_ID


def init_auth_db():
    conn = get_db_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_runs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL DEFAULT 1,
                data_path TEXT NOT NULL,
                source_files_json TEXT NOT NULL,
                groups_json TEXT NOT NULL DEFAULT '{}',
                run_name TEXT NOT NULL DEFAULT '',
                folder_name TEXT NOT NULL DEFAULT '',
                selected_chromatic TEXT NOT NULL,
                time_unit TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS folder_policies (
                user_id INTEGER NOT NULL DEFAULT 1,
                folder_name TEXT NOT NULL,
                policy_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, folder_name)
            )
            """
        )
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(saved_runs)").fetchall()]
        if "groups_json" not in cols:
            conn.execute("ALTER TABLE saved_runs ADD COLUMN groups_json TEXT NOT NULL DEFAULT '{}'")
        if "run_name" not in cols:
            conn.execute("ALTER TABLE saved_runs ADD COLUMN run_name TEXT NOT NULL DEFAULT ''")
        if "folder_name" not in cols:
            conn.execute("ALTER TABLE saved_runs ADD COLUMN folder_name TEXT NOT NULL DEFAULT ''")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Saved runs
# ---------------------------------------------------------------------------

def list_saved_runs_for_user(user_id, limit=50):
    conn = get_db_conn()
    try:
        if limit is None:
            rows = conn.execute(
                """SELECT id, source_files_json, selected_chromatic, time_unit, created_at,
                          groups_json, run_name, folder_name
                   FROM saved_runs ORDER BY created_at DESC"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, source_files_json, selected_chromatic, time_unit, created_at,
                          groups_json, run_name, folder_name
                   FROM saved_runs ORDER BY created_at DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        try:
            files = json.loads(row["source_files_json"])
        except Exception:
            files = []
        custom_name = (row["run_name"] or "").strip()
        label = custom_name if custom_name else (files[0] if files else row["id"])
        out.append({
            "id": row["id"],
            "label": label,
            "run_name": custom_name,
            "source_files": files,
            "selected_chromatic": row["selected_chromatic"],
            "time_unit": row["time_unit"],
            "created_at": row["created_at"],
            "has_groups": bool((row["groups_json"] or "{}").strip() not in {"", "{}", "null"}),
            "folder_name": (row["folder_name"] or "").strip(),
        })
    return out


def rename_run_for_user(user_id, run_id, new_name):
    conn = get_db_conn()
    try:
        conn.execute(
            "UPDATE saved_runs SET run_name=? WHERE id=?",
            ((new_name or "")[:120], run_id),
        )
        conn.commit()
    finally:
        conn.close()


def load_saved_run_by_id(run_id, expected_user_id=None):
    if not run_id:
        return None
    conn = get_db_conn()
    try:
        row = conn.execute(
            """SELECT id, user_id, data_path, source_files_json, groups_json,
                      run_name, folder_name, selected_chromatic, time_unit, created_at
               FROM saved_runs WHERE id = ?""",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None
    try:
        with gzip.open(row["data_path"], "rt", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None

    try:
        source_files = json.loads(row["source_files_json"])
    except Exception:
        source_files = []
    try:
        groups = json.loads(row["groups_json"] or "{}")
    except Exception:
        groups = {}
    if not isinstance(groups, dict):
        groups = {}

    return {
        "saved_paths": [],
        "filenames": source_files,
        "time_unit": normalize_time_unit(row["time_unit"]),
        "selected_chromatic": payload.get("selected_chromatic"),
        "available_chromatics": payload.get("available_chromatics", []),
        "time_sec": payload.get("time_sec", []),
        "wells": payload.get("wells", {}),
        "source_segments": payload.get("source_segments", []),
        "source": "persisted",
        "owner_user_id": LOCAL_USER_ID,
        "run_id": row["id"],
        "folder_name": (row["folder_name"] or "").strip(),
        "shared_groups": groups,
        "curve_groups": groups,
        "thalf_groups": groups,
    }


def persist_minimal_run(
    user_id,
    source_filenames,
    selected_chromatic,
    time_sec,
    wells,
    time_unit,
    groups_json_override=None,
    run_name_override="",
    folder_name_override="",
    payload_extra=None,
):
    run_id = uuid.uuid4().hex
    user_dir = os.path.join(SAVED_RUNS_DIR, str(LOCAL_USER_ID))
    os.makedirs(user_dir, exist_ok=True)
    base_name = "run"
    if source_filenames:
        first = secure_filename(os.path.basename(str(source_filenames[0])))
        if first:
            base_name = os.path.splitext(first)[0]
    data_path = os.path.join(user_dir, f"{base_name}_{run_id[:8]}.json.gz")
    # Auto-name: strip trailing _file{N} (and anything after it) from the stem
    auto_name = re.sub(r'_file\d+.*$', '', base_name, flags=re.IGNORECASE).strip("_- ")
    if not auto_name:
        auto_name = base_name
    payload = {
        "selected_chromatic": str(selected_chromatic),
        "time_sec": [int(v) for v in list(time_sec)],
        "wells": {k: [int(x) for x in v] for k, v in (wells or {}).items()},
    }
    if isinstance(payload_extra, dict):
        payload.update(payload_extra)
    with gzip.open(data_path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))

    groups_payload = groups_json_override if isinstance(groups_json_override, dict) else {}
    conn = get_db_conn()
    try:
        conn.execute(
            """INSERT INTO saved_runs
               (id, user_id, data_path, source_files_json, groups_json,
                run_name, folder_name, selected_chromatic, time_unit, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, LOCAL_USER_ID, data_path,
                json.dumps(list(source_filenames or [])),
                json.dumps(groups_payload, ensure_ascii=True),
                (run_name_override or auto_name).strip()[:120],
                (folder_name_override or "").strip()[:120],
                str(selected_chromatic),
                normalize_time_unit(time_unit),
                datetime.utcnow().isoformat() + "Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def persist_groups_for_run(upload_set_id, groups):
    if not upload_set_id:
        return
    payload = groups if isinstance(groups, dict) else {}
    conn = get_db_conn()
    try:
        conn.execute(
            "UPDATE saved_runs SET groups_json = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=True), upload_set_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_minimal_run_dataset(run_id, user_id, source_filenames, selected_chromatic,
                                time_sec, wells, source_segments=None, available_chromatics=None):
    if not run_id:
        return False
    conn = get_db_conn()
    try:
        row = conn.execute(
            "SELECT data_path FROM saved_runs WHERE id = ?", (str(run_id),)
        ).fetchone()
        if not row:
            return False
        payload = {
            "selected_chromatic": str(selected_chromatic),
            "time_sec": [int(v) for v in list(time_sec or [])],
            "wells": {k: [int(x) for x in v] for k, v in (wells or {}).items()},
            "source_segments": source_segments if isinstance(source_segments, list) else [],
            "available_chromatics": available_chromatics if isinstance(available_chromatics, list) else [],
        }
        with gzip.open(row["data_path"], "wt", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        conn.execute(
            "UPDATE saved_runs SET source_files_json=?, selected_chromatic=? WHERE id=?",
            (json.dumps(list(source_filenames or [])), str(selected_chromatic), str(run_id)),
        )
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Folder policies
# ---------------------------------------------------------------------------

def _sanitize_folder_policy(raw):
    if not isinstance(raw, dict):
        raw = {}
    except_grouping = [str(v).strip() for v in raw.get("except_grouping_run_ids", []) if str(v).strip()]
    return {
        "global_grouping": bool(raw.get("global_grouping", False)),
        "except_grouping_run_ids": sorted(list(dict.fromkeys(except_grouping))),
        "grouping_source_run_id": str(raw.get("grouping_source_run_id", "") or "").strip(),
    }


def load_folder_policies_for_user(user_id):
    conn = get_db_conn()
    try:
        rows = conn.execute(
            "SELECT folder_name, policy_json FROM folder_policies WHERE user_id = ?",
            (LOCAL_USER_ID,),
        ).fetchall()
    finally:
        conn.close()
    out = {}
    for row in rows:
        fname = (row["folder_name"] or "").strip()
        try:
            payload = json.loads(row["policy_json"] or "{}")
        except Exception:
            payload = {}
        out[fname] = _sanitize_folder_policy(payload)
    return out


def save_folder_policy_for_user(user_id, folder_name, policy):
    folder_name = (folder_name or "").strip()
    clean = _sanitize_folder_policy(policy)
    conn = get_db_conn()
    try:
        conn.execute(
            """INSERT INTO folder_policies (user_id, folder_name, policy_json, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, folder_name)
               DO UPDATE SET policy_json=excluded.policy_json, updated_at=excluded.updated_at""",
            (LOCAL_USER_ID, folder_name, json.dumps(clean, ensure_ascii=True),
             datetime.utcnow().isoformat() + "Z"),
        )
        conn.commit()
    finally:
        conn.close()


def apply_folder_policies_for_user(user_id):
    folder_policies = load_folder_policies_for_user(LOCAL_USER_ID)
    if not folder_policies:
        return
    conn = get_db_conn()
    try:
        rows = conn.execute(
            "SELECT id, folder_name, groups_json FROM saved_runs ORDER BY created_at DESC"
        ).fetchall()
        by_folder = {}
        for row in rows:
            folder = (row["folder_name"] or "").strip()
            by_folder.setdefault(folder, []).append(row)

        changed = False
        for folder_name, policy in folder_policies.items():
            p = _sanitize_folder_policy(policy)
            if not p["global_grouping"]:
                continue
            candidates = [
                r for r in by_folder.get(folder_name, [])
                if str(r["id"]) not in set(p["except_grouping_run_ids"])
            ]
            if len(candidates) < 2:
                continue
            source_groups_json = None
            source_groups_dict = None
            selected_source_id = p.get("grouping_source_run_id", "")
            if selected_source_id:
                for r in candidates:
                    if str(r["id"]) != selected_source_id:
                        continue
                    try:
                        g = json.loads(r["groups_json"] or "{}")
                    except Exception:
                        g = {}
                    if isinstance(g, dict) and g:
                        source_groups_json = json.dumps(g, ensure_ascii=True)
                        source_groups_dict = g
                    break
            if source_groups_json is None:
                for r in candidates:
                    try:
                        g = json.loads(r["groups_json"] or "{}")
                    except Exception:
                        g = {}
                    if isinstance(g, dict) and g:
                        source_groups_json = json.dumps(g, ensure_ascii=True)
                        source_groups_dict = g
                        break
            if source_groups_json is not None:
                for r in candidates:
                    if (r["groups_json"] or "").strip() != source_groups_json:
                        conn.execute(
                            "UPDATE saved_runs SET groups_json=? WHERE id=?",
                            (source_groups_json, r["id"]),
                        )
                        changed = True
                    rid = str(r["id"])
                    if rid in _state._stored_upload_sets and isinstance(source_groups_dict, dict):
                        _state._stored_upload_sets[rid]["shared_groups"] = source_groups_dict
                        _state._stored_upload_sets[rid]["curve_groups"] = source_groups_dict
        if changed:
            conn.commit()
    finally:
        conn.close()
