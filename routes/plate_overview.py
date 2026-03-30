import io
import json
import uuid
import zipfile

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, send_file

import state as _state
from config import normalize_time_unit, unit_suffix
from db import persist_groups_for_run
from data_utils import (
    resolve_upload_set_for_request,
    load_dataset_for_upload_set,
    get_shared_groups,
    parse_optional_float,
    parse_custom_plot_titles,
    build_curve_previews,
)
from plot_utils import generate_group_vs_control_plot

plate_overview_bp = Blueprint("plate_overview_bp", __name__)

_plot_datasets      = _state._plot_datasets
_stored_upload_sets = _state._stored_upload_sets
_plot_images        = _state._plot_images
_gvc_sessions       = _state._gvc_sessions


# ── Plate overview ────────────────────────────────────────────────────────────

@plate_overview_bp.route("/plate_overview/data", methods=["POST"])
def plate_overview_data():
    try:
        upload_set_id, upload_set = resolve_upload_set_for_request()
        time_unit = normalize_time_unit(upload_set.get("time_unit", session.get("current_time_unit", "hours")))
        selected, time_sec, wells = load_dataset_for_upload_set(upload_set)
        well_halftime = {w: None for w in wells}
        curve_previews = build_curve_previews(time_sec, wells, well_halftime, time_unit=time_unit)
        invalid_wells = []
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    remembered_groups = get_shared_groups(upload_set, sorted(wells.keys()))

    plate_session_id = uuid.uuid4().hex
    _plot_datasets[plate_session_id] = {
        "upload_set_id": upload_set_id,
        "plot_type": "raw",
        "n_files": len(upload_set.get("filenames", [])),
        "chromatic": selected,
        "time_sec": time_sec,
        "wells": wells,
        "well_halftime": well_halftime,
        "selected_wells": [],
        "x_from": None,
        "x_to": None,
        "groups": remembered_groups,
        "invalid_wells": invalid_wells,
        "time_unit": time_unit,
        "custom_titles": {"x": "", "y": "", "title": ""},
        "selected_plot_groups": [],
    }

    return jsonify({
        "ok": True,
        "plate_session_id": plate_session_id,
        "n_files": len(upload_set.get("filenames", [])),
        "chromatic": selected,
        "time_unit_suffix": unit_suffix(time_unit),
        "curve_previews": curve_previews,
        "well_halftime": {w: None for w in wells},
        "groups": remembered_groups,
        "invalid_wells": invalid_wells,
        "all_wells": sorted(wells.keys()),
    })


@plate_overview_bp.route("/plate_overview/update_groups", methods=["POST"])
def plate_overview_update_groups():
    plate_session_id = (request.form.get("plate_session_id") or "").strip()
    groups_json = (request.form.get("groups_json") or "").strip()
    data = _plot_datasets.get(plate_session_id)
    if not data:
        return jsonify({"ok": False, "error": "session_missing"}), 404
    try:
        groups = json.loads(groups_json) if groups_json else {}
    except json.JSONDecodeError:
        groups = {}
    data["groups"] = groups
    upload_set_id = data.get("upload_set_id", "")
    if upload_set_id and upload_set_id in _stored_upload_sets:
        _stored_upload_sets[upload_set_id]["shared_groups"] = groups
    persist_groups_for_run(upload_set_id, groups)
    return jsonify({"ok": True})


# ── Group vs control ──────────────────────────────────────────────────────────

@plate_overview_bp.route("/plot/group_vs_control/start", methods=["POST"])
def group_vs_control_start():
    dataset_id = (request.form.get("plate_session_id") or request.form.get("dataset_id") or "").strip()
    data = _plot_datasets.get(dataset_id)
    if not data:
        return render_template("result.html", error="Session missing for group vs control. Please reload the plate overview.")
    groups = data.get("groups", {}) if isinstance(data.get("groups", {}), dict) else {}
    groups = {g: ws for g, ws in groups.items() if isinstance(ws, list) and ws}
    if not groups:
        return render_template("result.html", error="Group vs control requires at least one group in the current run.")

    return render_template(
        "group_vs_control_select.html",
        dataset_id=dataset_id,
        n_files=data["n_files"],
        chromatic=data["chromatic"],
        time_unit=data.get("time_unit", "hours"),
        time_unit_suffix=unit_suffix(data.get("time_unit", "hours")),
        all_wells=sorted(data["wells"].keys()),
        groups=groups,
    )


@plate_overview_bp.route("/plot/group_vs_control/render", methods=["POST"])
def group_vs_control_render():
    dataset_id = request.form.get("dataset_id", "").strip()
    data = _plot_datasets.get(dataset_id)
    if not data:
        return render_template("result.html", error="Session missing for group vs control.")

    control_wells = request.form.getlist("control_well")
    excluded_wells = {w.strip() for w in request.form.getlist("exclude_well") if w.strip()}
    norm_setting = request.form.get("norm_setting", "raw")
    group_order_json = (request.form.get("group_order") or "").strip()
    custom_titles = parse_custom_plot_titles(request.form)

    try:
        group_order = json.loads(group_order_json) if group_order_json else []
    except json.JSONDecodeError:
        group_order = []

    groups = dict(data.get("groups", {}))
    if group_order:
        ordered = {g: groups[g] for g in group_order if g in groups}
        for g in groups:
            if g not in ordered:
                ordered[g] = groups[g]
        groups = ordered
    if excluded_wells:
        groups = {
            g: [w for w in (ws if isinstance(ws, list) else []) if w not in excluded_wells]
            for g, ws in groups.items()
        }
        groups = {g: ws for g, ws in groups.items() if ws}
    if not groups:
        return render_template("result.html", error="No groups left to plot after exclusions.")

    gvc_session_id = uuid.uuid4().hex
    _gvc_sessions[gvc_session_id] = {
        "dataset_id": dataset_id,
        "time_sec": data["time_sec"],
        "wells": data["wells"],
        "time_unit": data.get("time_unit", "hours"),
        "n_files": data["n_files"],
        "chromatic": data["chromatic"],
    }

    results = []
    for group_name, group_wells in groups.items():
        plots = []
        try:
            if norm_setting in ("raw", "both"):
                pid = generate_group_vs_control_plot(
                    data["time_sec"], data["wells"],
                    control_wells=control_wells, group_wells=list(group_wells),
                    normalized=False, time_unit=data.get("time_unit", "hours"),
                    custom_titles=custom_titles, group_name=group_name,
                )
                plots.append({"plot_id": pid, "normalized": False})
            if norm_setting in ("normalized", "both"):
                pid = generate_group_vs_control_plot(
                    data["time_sec"], data["wells"],
                    control_wells=control_wells, group_wells=list(group_wells),
                    normalized=True, time_unit=data.get("time_unit", "hours"),
                    custom_titles=custom_titles, group_name=group_name,
                )
                plots.append({"plot_id": pid, "normalized": True})
        except Exception:
            pass
        all_plot_wells = sorted(set(list(control_wells) + list(group_wells)))
        results.append({
            "group_name": group_name,
            "group_wells": list(group_wells),
            "plot_wells": all_plot_wells,
            "plots": plots,
        })

    return render_template(
        "group_vs_control_result.html",
        gvc_session_id=gvc_session_id,
        control_wells=control_wells,
        norm_setting=norm_setting,
        n_files=data["n_files"],
        chromatic=data["chromatic"],
        time_unit_suffix=unit_suffix(data.get("time_unit", "hours")),
        results=results,
    )


@plate_overview_bp.route("/plot/group_vs_control/replot_group", methods=["POST"])
def group_vs_control_replot():
    gvc_session_id = (request.form.get("gvc_session_id") or "").strip()
    gvc = _gvc_sessions.get(gvc_session_id)
    if not gvc:
        return jsonify({"error": "Session expired. Please regenerate plots."}), 404

    group_name = request.form.get("group_name", "")
    norm_setting = request.form.get("norm_setting", "raw")
    control_wells = request.form.getlist("control_well")
    group_wells = request.form.getlist("group_well")
    control_color = request.form.get("control_color", "#000000")
    group_color_val = request.form.get("group_color", "#E69F00")
    custom_titles = parse_custom_plot_titles(request.form)

    try:
        x_from = parse_optional_float(request.form.get("x_from"))
        x_to = parse_optional_float(request.form.get("x_to"))
    except ValueError:
        return jsonify({"error": "Invalid x range."}), 400

    plots = []
    try:
        if norm_setting in ("raw", "both"):
            pid = generate_group_vs_control_plot(
                gvc["time_sec"], gvc["wells"],
                control_wells=control_wells, group_wells=group_wells,
                normalized=False, x_from=x_from, x_to=x_to,
                control_color=control_color, group_color=group_color_val,
                time_unit=gvc.get("time_unit", "hours"),
                custom_titles=custom_titles, group_name=group_name,
            )
            plots.append({"plot_id": pid, "normalized": False})
        if norm_setting in ("normalized", "both"):
            pid = generate_group_vs_control_plot(
                gvc["time_sec"], gvc["wells"],
                control_wells=control_wells, group_wells=group_wells,
                normalized=True, x_from=x_from, x_to=x_to,
                control_color=control_color, group_color=group_color_val,
                time_unit=gvc.get("time_unit", "hours"),
                custom_titles=custom_titles, group_name=group_name,
            )
            plots.append({"plot_id": pid, "normalized": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    all_plot_wells = sorted(set(list(control_wells) + list(group_wells)))
    return jsonify({"plots": plots, "plot_wells": all_plot_wells})


@plate_overview_bp.route("/plot/group_vs_control/download_all", methods=["POST"])
def group_vs_control_download_all():
    plot_ids = request.form.getlist("plot_ids")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pid in plot_ids:
            entry = _plot_images.get(pid)
            if entry:
                zf.writestr(entry["download_name"], entry["bytes"])
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name="group_vs_control_plots.zip")


@plate_overview_bp.route("/plot/download/<plot_id>")
def download_plot_image(plot_id):
    entry = _plot_images.get(plot_id)
    if not entry:
        return "Image not found", 404
    return send_file(
        io.BytesIO(entry["bytes"]),
        mimetype="image/png",
        as_attachment=True,
        download_name=entry["download_name"],
    )


@plate_overview_bp.route("/plot/image/<plot_id>")
def serve_plot_image(plot_id):
    entry = _plot_images.get(plot_id)
    if not entry:
        return "Image not found", 404
    return send_file(
        io.BytesIO(entry["bytes"]),
        mimetype="image/png",
        as_attachment=False,
        download_name=entry["download_name"],
    )
