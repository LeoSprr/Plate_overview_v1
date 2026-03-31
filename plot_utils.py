import os, tempfile
os.environ["MPLCONFIGDIR"] = os.path.join(tempfile.gettempdir(), "mpl-cache")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import io
import uuid
import numpy as np

import state as _state
from config import (
    normalize_time_unit,
    unit_suffix,
    time_axis_from_seconds,
)
from data_utils import (
    resolve_plot_titles,
    sanitize_groups,
    average_group_signals,
)


def _store_plot_figure(fig, filename_prefix):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    plot_id = uuid.uuid4().hex
    _state._plot_images[plot_id] = {
        "bytes": buf.getvalue(),
        "download_name": f"{filename_prefix}_{plot_id[:8]}.png",
    }
    # Keep memory bounded.
    while len(_state._plot_images) > 200:
        oldest_id = next(iter(_state._plot_images))
        _state._plot_images.pop(oldest_id, None)
    return plot_id


def generate_group_vs_control_plot(
    time_sec,
    wells_dict,
    control_wells,
    group_wells,
    normalized=False,
    x_from=None,
    x_to=None,
    control_color="#000000",
    group_color="#E69F00",
    time_unit="hours",
    custom_titles=None,
    group_name="",
):
    time_h = time_axis_from_seconds(time_sec, time_unit)

    mask = np.ones_like(time_h, dtype=bool)
    if x_from is not None:
        mask &= time_h >= x_from
    if x_to is not None:
        mask &= time_h <= x_to
    if not np.any(mask):
        raise ValueError("No data points in selected x range.")
    time_h = time_h[mask]

    fig, ax = plt.subplots(figsize=(7, 4.5))

    def _plot_wells(well_list, color, legend_label):
        shown = False
        for well in well_list:
            if well not in wells_dict:
                continue
            y = np.array(wells_dict[well], dtype=float)
            if len(y) != len(mask):
                continue
            y = y[mask]
            if normalized:
                mn, mx = np.min(y), np.max(y)
                if mx - mn == 0:
                    continue
                y = (y - mn) / (mx - mn)
            lbl = legend_label if not shown else None
            ax.plot(time_h, y, linewidth=1.4, alpha=0.8, color=color, label=lbl)
            shown = True

    _plot_wells(control_wells, control_color, "Control")
    _plot_wells(group_wells, group_color, group_name or "Group")

    suffix = unit_suffix(time_unit)
    default_x = f"Time ({suffix})"
    default_y = "Normalized fluorescence (0-1)" if normalized else "Fluorescence (a.u.)"
    default_title = group_name or "Group vs Control"
    x_label, y_label, title_label = resolve_plot_titles(custom_titles, default_x, default_y, default_title)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title_label)
    ax.grid(True, linestyle="--", linewidth=0.5)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    prefix = f"gvc_{group_name[:12]}" if group_name else "gvc_group"
    return _store_plot_figure(fig, prefix)


GVG_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


def generate_group_vs_group_plot(
    time_sec,
    wells_dict,
    groups,
    normalized=False,
    x_from=None,
    x_to=None,
    colors=None,
    time_unit="hours",
    custom_titles=None,
    plot_name="",
):
    """Plot multiple groups overlaid on the same axes.

    groups:  {group_name: [well_ids]}
    colors:  {group_name: hex_color} or None → use palette
    """
    time_h = time_axis_from_seconds(time_sec, time_unit)

    mask = np.ones_like(time_h, dtype=bool)
    if x_from is not None:
        mask &= time_h >= x_from
    if x_to is not None:
        mask &= time_h <= x_to
    if not np.any(mask):
        raise ValueError("No data points in selected x range.")
    time_h = time_h[mask]

    fig, ax = plt.subplots(figsize=(7, 4.5))

    for i, (group_name, group_wells) in enumerate(groups.items()):
        color = (colors or {}).get(group_name) or GVG_PALETTE[i % len(GVG_PALETTE)]
        shown = False
        for well in group_wells:
            if well not in wells_dict:
                continue
            y = np.array(wells_dict[well], dtype=float)
            if len(y) != len(mask):
                continue
            y = y[mask]
            if normalized:
                mn, mx = np.min(y), np.max(y)
                if mx - mn == 0:
                    continue
                y = (y - mn) / (mx - mn)
            lbl = group_name if not shown else None
            ax.plot(time_h, y, linewidth=1.4, alpha=0.8, color=color, label=lbl)
            shown = True

    suffix = unit_suffix(time_unit)
    default_x = f"Time ({suffix})"
    default_y = "Normalized fluorescence (0-1)" if normalized else "Fluorescence (a.u.)"
    default_title = plot_name or "Group vs Group"
    x_label, y_label, title_label = resolve_plot_titles(
        custom_titles, default_x, default_y, default_title
    )
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title_label)
    ax.grid(True, linestyle="--", linewidth=0.5)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    prefix = f"gvg_{(plot_name or 'plot')[:12]}"
    return _store_plot_figure(fig, prefix)
