from flask import Blueprint, request, redirect, url_for, session, jsonify

import state as _state
from db import current_user_id
from data_utils import (
    get_upload_set,
    list_chromatics_in_segments,
    merge_source_segments,
    get_all_chromatics_preview,
    get_all_chromatics_preview_from_segments,
)

chromatic_bp = Blueprint("chromatic_bp", __name__)

_stored_upload_sets = _state._stored_upload_sets


# ── Chromatic preview (new upload) ────────────────────────────────────────────

@chromatic_bp.route("/upload/preview_chromatics", methods=["POST"])
def upload_preview_chromatics():
    upload_files = request.files.getlist("files")
    upload_files = [f for f in upload_files if f and f.filename]
    upload_format = (request.form.get("upload_format", "auto") or "auto").strip().lower()
    if upload_format not in {"auto", "csv", "dat"}:
        upload_format = "auto"

    if not upload_files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400

    try:
        preview = get_all_chromatics_preview(upload_files, upload_format=upload_format)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, **preview})


# ── Chromatic preview (existing session) ─────────────────────────────────────

@chromatic_bp.route("/upload/preview_chromatics_session", methods=["POST"])
def upload_preview_chromatics_session():
    upload_set_id = (request.form.get("upload_set_id", "") or "").strip()
    if not upload_set_id:
        upload_set_id = session.get("current_upload_set_id", "")
    upload_set = get_upload_set(upload_set_id)
    if not upload_set:
        return jsonify({"ok": False, "error": "No active upload session"}), 400

    segments = upload_set.get("source_segments", [])
    if not isinstance(segments, list) or not segments:
        return jsonify({"ok": False, "error": "No source segments available for this session"}), 400

    try:
        preview = get_all_chromatics_preview_from_segments(
            segments,
            source_names=upload_set.get("filenames", []),
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, **preview})


# ── Set chromatic for existing session ────────────────────────────────────────

@chromatic_bp.route("/files/set_chromatic", methods=["POST"])
def set_session_chromatic():
    upload_set_id = (request.form.get("upload_set_id", "") or "").strip()
    if not upload_set_id:
        upload_set_id = session.get("current_upload_set_id", "")
    chromatic = (request.form.get("chromatic", "") or "").strip()
    if not upload_set_id or not chromatic:
        return redirect(url_for("main_bp.index"))

    upload_set = get_upload_set(upload_set_id)
    if not upload_set:
        return redirect(url_for("main_bp.index"))

    segments = upload_set.get("source_segments", [])
    if not isinstance(segments, list) or not segments:
        return redirect(url_for("main_bp.index"))

    available = list_chromatics_in_segments(segments)
    if chromatic not in available:
        return redirect(url_for("main_bp.index"))

    merged = merge_source_segments(segments, selected_chromatic=chromatic)
    if chromatic not in merged:
        return redirect(url_for("main_bp.index"))
    time_sec = merged[chromatic]["time"]
    wells = merged[chromatic]["wells"]
    if not time_sec or not wells:
        return redirect(url_for("main_bp.index"))

    upload_set["available_chromatics"] = available
    upload_set["force_chromatic"] = chromatic
    upload_set["selected_chromatic"] = chromatic
    upload_set["time_sec"] = time_sec
    upload_set["wells"] = wells
    _stored_upload_sets[upload_set_id] = upload_set
    if current_user_id() is not None:
        session["current_upload_set_id"] = upload_set_id
    return redirect(url_for("main_bp.index"))
