# Shared mutable in-memory state.

_stored_upload_sets = {}   # raw uploaded data sets
_plot_datasets      = {}   # datasets prepared for plot/select
_plot_images        = {}   # rendered PNG blobs keyed by plot_id
_gvc_sessions       = {}   # /plot/group_vs_control sessions
_gvg_sessions       = {}   # /plot/group_vs_group sessions
