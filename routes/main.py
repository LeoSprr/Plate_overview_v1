from flask import Blueprint, render_template, request, redirect, url_for, session

import state as _state
from config import normalize_time_unit
from db import current_user_id, apply_folder_policies_for_user, list_saved_runs_for_user, load_folder_policies_for_user
from data_utils import (
    get_upload_set,
    resolve_upload_set_for_request,
    list_chromatics_in_segments,
    get_all_chromatics_preview,
)

main_bp = Blueprint("main_bp", __name__)


@main_bp.route("/")
def index():
    user_id = current_user_id()
    apply_folder_policies_for_user(user_id)
    current_upload_set_id = session.get("current_upload_set_id", "")
    current_upload_set = get_upload_set(current_upload_set_id)
    current_files = current_upload_set["filenames"] if current_upload_set else []
    available_chromatics = []
    current_selected_chromatic = ""
    if current_upload_set:
        available_chromatics = current_upload_set.get("available_chromatics", [])
        if not isinstance(available_chromatics, list) or not available_chromatics:
            available_chromatics = list_chromatics_in_segments(current_upload_set.get("source_segments", []))
        current_selected_chromatic = str(current_upload_set.get("selected_chromatic", "") or "")
    current_time_unit = normalize_time_unit(
        (current_upload_set or {}).get("time_unit", session.get("current_time_unit", "hours"))
    )
    saved_runs = list_saved_runs_for_user(user_id, limit=None)
    saved_folders = sorted(
        {r.get("folder_name", "").strip() for r in saved_runs if r.get("folder_name", "").strip()},
        key=lambda s: s.lower(),
    )
    folder_policies = load_folder_policies_for_user(user_id)
    current_run_groups = {}
    if current_upload_set:
        try:
            current_run_groups = (
                current_upload_set.get("shared_groups")
                or current_upload_set.get("curve_groups")
                or {}
            )
        except Exception:
            current_run_groups = {}

    return render_template(
        "index.html",
        current_files=current_files,
        upload_set_id=current_upload_set_id if current_upload_set else "",
        current_time_unit=current_time_unit,
        saved_runs=saved_runs,
        saved_folders=saved_folders,
        folder_policies=folder_policies,
        current_run_groups=current_run_groups,
        available_chromatics=available_chromatics,
        current_selected_chromatic=current_selected_chromatic,
        upload_is_fresh=session.get("upload_is_fresh", False),
    )


@main_bp.route("/analyze", methods=["POST"])
def upload_and_open():
    try:
        upload_set_id, _ = resolve_upload_set_for_request()
        if upload_set_id:
            session["upload_is_fresh"] = True
    except Exception as exc:
        return render_template("result.html", error=f"Could not process uploaded files: {exc}")
    return redirect(url_for("main_bp.index"))


@main_bp.route("/upload/save_only", methods=["POST"])
def upload_save_only():
    upload_files = request.files.getlist("files")
    upload_files = [f for f in upload_files if f and f.filename]
    upload_format = (request.form.get("upload_format", "auto") or "auto").strip().lower()
    if upload_format not in {"auto", "csv", "dat"}:
        upload_format = "auto"
    force_chromatic = (request.form.get("force_chromatic", "") or "").strip()

    if upload_files and not force_chromatic:
        try:
            preview = get_all_chromatics_preview(upload_files, upload_format=upload_format)
            available = preview.get("available", []) if isinstance(preview, dict) else []
            if len(available) > 1:
                return render_template(
                    "result.html",
                    error="Choose a chromatic in the chromatic step before saving files.",
                )
            for f in upload_files:
                try:
                    f.seek(0)
                except Exception:
                    pass
        except Exception as exc:
            return render_template("result.html", error=f"Could not validate chromatics before save: {exc}")

    try:
        upload_set_id, _ = resolve_upload_set_for_request()
        if upload_set_id:
            session["upload_is_fresh"] = True
    except Exception as exc:
        return render_template("result.html", error=f"Could not save uploaded files: {exc}")
    return redirect(url_for("main_bp.index"))
