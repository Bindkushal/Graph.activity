# GraphIt — Learn coordinates by plotting on a graph
# Copyright (C) 2025 Kushal Kant Bind
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import json
import math
import os
from gettext import gettext as _

from sugar3.activity import activity
from sugar3.graphics.toolbarbox import ToolbarBox
from sugar3.activity.widgets import ActivityToolbarButton, StopButton
from sugar3.graphics.toolbutton import ToolButton
from sugar3.graphics.toggletoolbutton import ToggleToolButton

# ── Logic layer ───────────────────────────────────────────────────────────────
# All pure-Python data and math lives in logic/__init__.py.
# activity.py is the GTK shell only.
from logic import (
    CHALLENGES,
    GRID_CELLS,
    PointHistory,
    compute_step,
    grid_to_screen,
    screen_to_grid,
    validate_coord,
    check_completion,
)


class GraphIt(activity.Activity):
    """GraphIt — interactive coordinate graph learning activity."""

    def __init__(self, handle):
        activity.Activity.__init__(self, handle)

        # ── state ─────────────────────────────────────────────────────────
        self.history = PointHistory()       # logic layer owns the point list
        self.current_challenge = None
        self.connect_mode = False
        self.hover_point = None
        self.guide_point = None
        # These are updated each draw cycle via compute_step()
        self._step = 40
        self._cx   = 400
        self._cy   = 300
        self._cells = GRID_CELLS

        self._setup_css()
        self._create_toolbar()
        self._create_main_ui()

    # ── CSS ───────────────────────────────────────────────────────────────────

    def _setup_css(self):
        css = b"""
        .sidebar { background-color: #0f1923; }

        .cat-btn {
            font-size: 12pt;
            font-weight: bold;
            border-radius: 8px;
            min-height: 44px;
            margin: 3px 0;
            background-color: #1e2d3d;
            color: #a8d8ea;
        }
        .cat-btn:hover { background-color: #2a4a6b; }

        .task-btn {
            font-size: 11pt;
            border-radius: 6px;
            min-height: 38px;
            margin: 2px 4px;
            background-color: #162032;
            color: #d4e8f0;
        }
        .task-btn:hover { background-color: #1e3a55; }
        .task-btn-active {
            background-color: #e94560;
            color: white;
        }

        .challenge-title {
            font-size: 14pt;
            font-weight: bold;
            color: #e94560;
        }
        .fact-label {
            font-size: 9pt;
            color: #ffd166;
            font-style: italic;
        }
        .hint-label {
            font-size: 9pt;
            color: #a8dadc;
            font-style: italic;
        }
        .point-row {
            font-family: monospace;
            font-size: 11pt;
            color: #a8dadc;
            padding: 1px 6px;
        }
        .input-coord {
            font-family: monospace;
            font-size: 12pt;
            background-color: #162032;
            color: #e0e0e0;
            border-radius: 4px;
        }
        .plot-btn {
            font-size: 11pt;
            font-weight: bold;
            background-color: #e94560;
            color: white;
            border-radius: 6px;
            min-height: 36px;
        }
        .plot-btn:hover { background-color: #c73652; }
        .success-label {
            font-size: 13pt;
            font-weight: bold;
            color: #06d6a0;
        }
        .back-btn {
            font-size: 10pt;
            color: #a8dadc;
            border-radius: 4px;
            background-color: transparent;
        }
        .back-btn:hover { background-color: #1e2d3d; }
        """
        p = Gtk.CssProvider()
        p.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), p,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _create_toolbar(self):
        tb = ToolbarBox()
        self.set_toolbar_box(tb)
        bar = tb.toolbar
        bar.insert(ActivityToolbarButton(self), -1)

        sep = Gtk.SeparatorToolItem(); sep.props.draw = True
        bar.insert(sep, -1)

        undo_btn = ToolButton("edit-undo")
        undo_btn.set_tooltip(_("Undo last point"))
        undo_btn.connect("clicked", self._undo_cb)
        bar.insert(undo_btn, -1)

        clear_btn = ToolButton("edit-clear")
        clear_btn.set_tooltip(_("Clear all points"))
        clear_btn.connect("clicked", self._clear_cb)
        bar.insert(clear_btn, -1)

        sep2 = Gtk.SeparatorToolItem(); sep2.props.draw = True
        bar.insert(sep2, -1)

        self.connect_toggle = ToggleToolButton("format-justify-fill")
        self.connect_toggle.set_tooltip(_("Connect dots with lines"))
        self.connect_toggle.connect("toggled", self._connect_toggled_cb)
        bar.insert(self.connect_toggle, -1)

        sep3 = Gtk.SeparatorToolItem(); sep3.props.draw = True
        bar.insert(sep3, -1)

        help_btn = ToolButton("toolbar-help")
        help_btn.set_tooltip(_("Help"))
        help_btn.connect("clicked", self._help_cb)
        bar.insert(help_btn, -1)

        spacer = Gtk.SeparatorToolItem()
        spacer.props.draw = False; spacer.set_expand(True)
        bar.insert(spacer, -1)
        bar.insert(StopButton(self), -1)
        tb.show_all()

    # ── Main UI ───────────────────────────────────────────────────────────────

    def _create_main_ui(self):
        self.root_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # ── Canvas ──────────────────────────────────────────────────────
        self.canvas = Gtk.DrawingArea()
        self.canvas.set_hexpand(True)
        self.canvas.set_vexpand(True)
        self.canvas.set_size_request(500, 500)   # minimum so grid cells never vanish
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        # NOTE: do NOT use set_app_paintable(True) — in GTK3/Sugar that makes the
        # DrawingArea composite against the desktop background (transparent canvas).
        self.canvas.connect("draw", self._draw_cb)
        self.canvas.connect("realize", lambda w: w.queue_draw())
        self.canvas.connect("button-press-event", self._canvas_click_cb)
        self.canvas.connect("motion-notify-event", self._canvas_motion_cb)
        self.canvas.connect("leave-notify-event", self._canvas_leave_cb)
        self.root_hbox.pack_start(self.canvas, True, True, 0)

        # ── Sidebar stack ────────────────────────────────────────────────
        # We use a Gtk.Stack to switch between:
        #   "menu"     — category picker
        #   "tasks"    — task list for chosen category
        #   "playing"  — active challenge info + points list
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.sidebar.set_size_request(230, -1)
        self.sidebar.get_style_context().add_class("sidebar")

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(200)

        self.stack.add_named(self._build_menu_page(), "menu")
        self.stack.add_named(self._build_tasks_page(), "tasks")
        self.stack.add_named(self._build_playing_page(), "playing")

        self.sidebar.pack_start(self.stack, True, True, 0)
        self.root_hbox.pack_start(self.sidebar, False, False, 0)

        self.set_canvas(self.root_hbox)
        self.root_hbox.show_all()
        GLib.idle_add(self.canvas.queue_draw)

        # Start on blank graph, menu visible
        self.stack.set_visible_child_name("menu")

    # ── Menu page — category picker ───────────────────────────────────────────

    def _build_menu_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)

        title = Gtk.Label()
        title.set_markup('<span size="large" weight="bold" color="#a8dadc">📐 GraphIt</span>')
        title.set_xalign(0)
        box.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(label="What do you want to draw?")
        subtitle.set_line_wrap(True)
        subtitle.set_xalign(0)
        subtitle.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.6, 0.7, 0.8, 1))
        box.pack_start(subtitle, False, False, 4)

        box.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 4
        )

        # Category buttons
        icons = {
            "Triangles": "🔺",
            "Quadrilaterals": "🟦",
            "Stars & Polygons": "⭐",
            "Free Draw": "✏️",
        }
        for cat in CHALLENGES:
            btn = Gtk.Button(label=f"  {icons.get(cat,'')}  {cat}")
            btn.set_halign(Gtk.Align.START)
            btn.get_style_context().add_class("cat-btn")
            btn.connect("clicked", self._category_clicked_cb, cat)
            box.pack_start(btn, False, False, 0)

        return box

    # ── Tasks page — list of challenges in chosen category ────────────────────

    def _build_tasks_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(10)

        # Back button
        back = Gtk.Button(label="← Back")
        back.get_style_context().add_class("back-btn")
        back.connect("clicked", lambda b: self.stack.set_visible_child_name("menu"))
        box.pack_start(back, False, False, 0)

        self.tasks_title = Gtk.Label()
        self.tasks_title.set_markup('<span weight="bold" color="#a8dadc">Choose a task:</span>')
        self.tasks_title.set_xalign(0)
        box.pack_start(self.tasks_title, False, False, 4)

        box.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 2
        )

        # Scrollable task list
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.tasks_list_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4
        )
        scroll.add(self.tasks_list_box)
        box.pack_start(scroll, True, True, 0)

        return box

    # ── Playing page — active challenge + coordinate entry + points list ───────

    def _build_playing_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(10)

        # Back to tasks
        back = Gtk.Button(label="← Tasks")
        back.get_style_context().add_class("back-btn")
        back.connect("clicked", self._back_to_tasks_cb)
        box.pack_start(back, False, False, 0)

        # Challenge name
        self.playing_title = Gtk.Label(label="")
        self.playing_title.get_style_context().add_class("challenge-title")
        self.playing_title.set_line_wrap(True)
        self.playing_title.set_xalign(0)
        box.pack_start(self.playing_title, False, False, 0)

        # Description
        self.playing_desc = Gtk.Label(label="")
        self.playing_desc.set_line_wrap(True)
        self.playing_desc.set_xalign(0)
        self.playing_desc.override_color(
            Gtk.StateFlags.NORMAL, Gdk.RGBA(0.75, 0.75, 0.75, 1)
        )
        box.pack_start(self.playing_desc, False, False, 0)

        # Hint
        self.playing_hint = Gtk.Label(label="")
        self.playing_hint.get_style_context().add_class("hint-label")
        self.playing_hint.set_line_wrap(True)
        self.playing_hint.set_xalign(0)
        box.pack_start(self.playing_hint, False, False, 0)

        # Fact
        self.playing_fact = Gtk.Label(label="")
        self.playing_fact.get_style_context().add_class("fact-label")
        self.playing_fact.set_line_wrap(True)
        self.playing_fact.set_xalign(0)
        box.pack_start(self.playing_fact, False, False, 0)

        box.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 4
        )

        # Coordinate entry
        coord_lbl = Gtk.Label(label="Plot a point (x, y):")
        coord_lbl.set_xalign(0)
        coord_lbl.override_color(
            Gtk.StateFlags.NORMAL, Gdk.RGBA(0.6, 0.75, 0.85, 1)
        )
        box.pack_start(coord_lbl, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.x_entry = Gtk.Entry()
        self.x_entry.set_placeholder_text("x")
        self.x_entry.set_width_chars(4)
        self.x_entry.get_style_context().add_class("input-coord")
        self.y_entry = Gtk.Entry()
        self.y_entry.set_placeholder_text("y")
        self.y_entry.set_width_chars(4)
        self.y_entry.get_style_context().add_class("input-coord")
        plot_btn = Gtk.Button(label="Plot")
        plot_btn.get_style_context().add_class("plot-btn")
        plot_btn.connect("clicked", self._manual_plot_cb)
        self.x_entry.connect("activate", self._manual_plot_cb)
        self.y_entry.connect("activate", self._manual_plot_cb)
        row.pack_start(self.x_entry, True, True, 0)
        row.pack_start(Gtk.Label(label=","), False, False, 0)
        row.pack_start(self.y_entry, True, True, 0)
        row.pack_start(plot_btn, False, False, 0)
        box.pack_start(row, False, False, 0)

        box.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 4
        )

        # Points list
        pts_lbl = Gtk.Label(label="Your points:")
        pts_lbl.set_xalign(0)
        pts_lbl.override_color(
            Gtk.StateFlags.NORMAL, Gdk.RGBA(0.5, 0.7, 0.8, 1)
        )
        box.pack_start(pts_lbl, False, False, 0)

        scroll2 = Gtk.ScrolledWindow()
        scroll2.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll2.set_vexpand(True)
        self.points_list_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=1
        )
        scroll2.add(self.points_list_box)
        box.pack_start(scroll2, True, True, 0)

        # Success
        self.success_label = Gtk.Label(label="")
        self.success_label.get_style_context().add_class("success-label")
        self.success_label.set_line_wrap(True)
        self.success_label.set_no_show_all(True)
        box.pack_end(self.success_label, False, False, 4)

        return box

    # ── Navigation callbacks ──────────────────────────────────────────────────

    def _category_clicked_cb(self, btn, category):
        """Show task list for chosen category."""
        self.current_category = category
        self.tasks_title.set_markup(
            f'<span weight="bold" color="#a8dadc">{category}</span>'
        )
        # Clear and rebuild task buttons
        for child in self.tasks_list_box.get_children():
            self.tasks_list_box.remove(child)

        for challenge in CHALLENGES[category]:
            task_btn = Gtk.Button(label=challenge["name"])
            task_btn.set_halign(Gtk.Align.START)
            task_btn.get_style_context().add_class("task-btn")
            # Add small description under name
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name_lbl = Gtk.Label(label=challenge["name"])
            name_lbl.set_xalign(0)
            name_lbl.override_color(
                Gtk.StateFlags.NORMAL, Gdk.RGBA(0.9, 0.9, 0.9, 1)
            )
            desc_lbl = Gtk.Label(label=challenge["description"])
            desc_lbl.set_xalign(0)
            desc_lbl.set_line_wrap(True)
            desc_lbl.override_color(
                Gtk.StateFlags.NORMAL, Gdk.RGBA(0.55, 0.7, 0.8, 1)
            )
            vbox.pack_start(name_lbl, False, False, 0)
            vbox.pack_start(desc_lbl, False, False, 0)
            task_btn = Gtk.Button()
            task_btn.add(vbox)
            task_btn.get_style_context().add_class("task-btn")
            task_btn.connect("clicked", self._task_clicked_cb, challenge)
            self.tasks_list_box.pack_start(task_btn, False, False, 0)

        self.tasks_list_box.show_all()
        self.stack.set_visible_child_name("tasks")

    def _task_clicked_cb(self, btn, challenge):
        """Load the chosen challenge and switch to playing view."""
        self.current_challenge = challenge
        self.history.clear()
        self.guide_point = None
        self.success_label.hide()

        self.playing_title.set_text(challenge["name"])
        self.playing_desc.set_text(challenge["description"])
        self.playing_hint.set_text("💡 " + challenge["hint"])
        self.playing_fact.set_text(
            "📖 " + challenge["fact"] if challenge["fact"] else ""
        )
        self._refresh_points_list()
        self.canvas.queue_draw()
        self.stack.set_visible_child_name("playing")

    def _back_to_tasks_cb(self, btn):
        self.current_challenge = None
        self.history.clear()
        self.guide_point = None
        self.canvas.queue_draw()
        self.stack.set_visible_child_name("tasks")

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_cb(self, widget, cr):
        alloc = widget.get_allocation()
        W, H = alloc.width, alloc.height

        cells = GRID_CELLS
        # logic layer computes the correct step size
        step = compute_step(W, H, cells)
        cx, cy = W / 2, H / 2

        # Active grid bounds
        gx0 = cx - cells * step
        gx1 = cx + cells * step
        gy0 = cy - cells * step
        gy1 = cy + cells * step

        # Cache for mouse event handlers (screen_to_grid needs these)
        self._step  = step
        self._cx    = cx
        self._cy    = cy
        self._cells = cells

        def to_screen(x, y):
            return grid_to_screen(x, y, cx, cy, step)

        # ══════════════════════════════════════════════════════════════════════
        # 1. BACKGROUND
        # ══════════════════════════════════════════════════════════════════════
        cr.set_source_rgb(0.08, 0.12, 0.22)
        cr.paint()

        # Slightly lighter panel behind the active grid area
        cr.set_source_rgb(0.11, 0.17, 0.30)
        cr.rectangle(gx0, gy0, gx1 - gx0, gy1 - gy0)
        cr.fill()

        # ══════════════════════════════════════════════════════════════════════
        # 2. GRID LINES — span the FULL canvas so the graph feels infinite
        #    Minor lines (every 1 unit) inside grid bounds only to keep it clean
        # ══════════════════════════════════════════════════════════════════════
        cr.set_line_width(1.0)
        for i in range(-cells, cells + 1):
            # skip 0 — drawn as bold axis below
            if i == 0:
                continue

            # vertical line — full canvas height
            lx = cx + i * step
            cr.set_source_rgba(0.35, 0.52, 0.78, 0.70)
            cr.move_to(lx, 0)
            cr.line_to(lx, H)
            cr.stroke()

            # horizontal line — full canvas width
            ly = cy - i * step
            cr.move_to(0, ly)
            cr.line_to(W, ly)
            cr.stroke()

        # ══════════════════════════════════════════════════════════════════════
        # 3. AXES — bold, run the full canvas width/height
        # ══════════════════════════════════════════════════════════════════════
        cr.set_line_width(2.2)
        cr.set_source_rgba(0.60, 0.78, 1.0, 1.0)

        # x-axis  (horizontal, at cy)
        cr.move_to(0, cy)
        cr.line_to(W, cy)
        cr.stroke()

        # y-axis  (vertical, at cx)
        cr.move_to(cx, 0)
        cr.line_to(cx, H)
        cr.stroke()

        # ── Arrow heads ───────────────────────────────────────
        cr.set_source_rgba(0.60, 0.78, 1.0, 1.0)
        # right arrowhead on x-axis
        cr.move_to(W - 2, cy)
        cr.line_to(W - 12, cy - 6)
        cr.line_to(W - 12, cy + 6)
        cr.close_path(); cr.fill()
        # up arrowhead on y-axis
        cr.move_to(cx, 2)
        cr.line_to(cx - 6, 12)
        cr.line_to(cx + 6, 12)
        cr.close_path(); cr.fill()

        # ── Axis letter labels ────────────────────────────────
        cr.set_source_rgba(0.75, 0.90, 1.0, 0.95)
        cr.select_font_face("Sans", 0, 1)   # bold
        cr.set_font_size(15)
        cr.move_to(W - 22, cy - 8);  cr.show_text("x")
        cr.move_to(cx + 8,  14);     cr.show_text("y")

        # ══════════════════════════════════════════════════════════════════════
        # 4. TICK MARKS + NUMBER LABELS  (every 2 units, skip 0)
        # ══════════════════════════════════════════════════════════════════════
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgba(0.55, 0.72, 0.90, 0.90)

        for i in range(-cells, cells + 1):
            if i == 0:
                continue
            lx = cx + i * step
            ly = cy - i * step

            # tick on x-axis
            cr.set_line_width(1.2)
            cr.move_to(lx, cy - 4); cr.line_to(lx, cy + 4); cr.stroke()

            # tick on y-axis
            cr.move_to(cx - 4, ly); cr.line_to(cx + 4, ly); cr.stroke()

            if i % 2 == 0:
                lbl = str(i)
                ext = cr.text_extents(lbl)
                # x-axis number below tick
                cr.move_to(lx - ext.width / 2, cy + 16)
                cr.show_text(lbl)
                # y-axis number left of tick
                cr.move_to(cx - ext.width - 8, ly + ext.height / 2)
                cr.show_text(lbl)

        # ── Origin "0" ────────────────────────────────────────
        cr.set_font_size(10)
        cr.set_source_rgba(0.50, 0.65, 0.82, 0.80)
        cr.move_to(cx + 5, cy + 14)
        cr.show_text("0")

        # ── Guided coordinate travel:
        #     origin -> (x,0) -> (x,y), plus straight origin -> (x,y)
        #     This helps children understand axis movement before plotting.
        if self.stack.get_visible_child_name() == "playing" and self.guide_point:
            gx, gy = self.guide_point
            sx0, sy0 = to_screen(0, 0)
            sx1, sy1 = to_screen(gx, 0)
            sx2, sy2 = to_screen(gx, gy)

            # Step 1 and Step 2 (dashed travel path)
            cr.set_source_rgba(0.99, 0.82, 0.10, 0.85)
            cr.set_line_width(3.0)
            cr.set_dash([8.0, 6.0], 0)
            cr.move_to(sx0, sy0)
            cr.line_to(sx1, sy1)
            cr.line_to(sx2, sy2)
            cr.stroke()
            cr.set_dash([], 0)

            # Final straight line from origin to the selected coordinate
            cr.set_source_rgba(0.20, 0.90, 1.00, 0.85)
            cr.set_line_width(2.4)
            cr.move_to(sx0, sy0)
            cr.line_to(sx2, sy2)
            cr.stroke()

            # Small destination marker
            cr.set_source_rgba(0.20, 0.90, 1.00, 0.25)
            cr.arc(sx2, sy2, 11, 0, 2 * math.pi)
            cr.fill()

        # ── Grid border (thin bright rectangle around active area) ───────────
        cr.set_line_width(1.0)
        cr.set_source_rgba(0.40, 0.55, 0.80, 0.45)
        cr.rectangle(gx0, gy0, gx1 - gx0, gy1 - gy0)
        cr.stroke()

        # ══════════════════════════════════════════════════════════════════════
        # 5. GHOST SHAPE (challenge target)  — faint orange guide
        # ══════════════════════════════════════════════════════════════════════
        if self.current_challenge and self.current_challenge["points"]:
            ghost = self.current_challenge["points"]
            cr.set_line_width(1.5)
            cr.set_source_rgba(0.9, 0.5, 0.2, 0.25)
            sx, sy = to_screen(*ghost[0])
            cr.move_to(sx, sy)
            for p in ghost[1:]:
                sx, sy = to_screen(*p)
                cr.line_to(sx, sy)
            cr.stroke()
            for p in ghost:
                sx, sy = to_screen(*p)
                cr.set_source_rgba(0.95, 0.55, 0.20, 0.30)
                cr.arc(sx, sy, 6, 0, 2 * math.pi); cr.fill()

        # ══════════════════════════════════════════════════════════════════════
        # 6. CONNECTED LINES between plotted points
        # ══════════════════════════════════════════════════════════════════════
        if self.connect_mode and len(self.history) >= 2:
            cr.set_line_width(2.5)
            cr.set_source_rgba(0.35, 0.85, 0.65, 0.95)
            sx, sy = to_screen(*self.history[0])
            cr.move_to(sx, sy)
            for p in self.history[1:]:
                sx, sy = to_screen(*p)
                cr.line_to(sx, sy)
            cr.stroke()

        # ══════════════════════════════════════════════════════════════════════
        # 7. HOVER SNAP INDICATOR
        # ══════════════════════════════════════════════════════════════════════
        if self.hover_point:
            hx, hy = to_screen(*self.hover_point)
            # outer glow ring
            cr.set_source_rgba(1.0, 0.84, 0.0, 0.20)
            cr.arc(hx, hy, 14, 0, 2 * math.pi); cr.fill()
            # inner dot
            cr.set_source_rgba(1.0, 0.84, 0.0, 0.55)
            cr.arc(hx, hy, 7, 0, 2 * math.pi); cr.fill()
            # coordinate label
            cr.set_font_size(11)
            cr.set_source_rgba(1.0, 0.84, 0.0, 0.95)
            cr.move_to(hx + 13, hy - 5)
            cr.show_text(f"({self.hover_point[0]}, {self.hover_point[1]})")

        # ══════════════════════════════════════════════════════════════════════
        # 8. PLOTTED POINTS
        # ══════════════════════════════════════════════════════════════════════
        COLORS = [
            (0.91, 0.27, 0.37),   # red
            (0.25, 0.85, 0.63),   # green
            (0.99, 0.82, 0.10),   # yellow
            (0.38, 0.55, 0.99),   # blue
            (0.96, 0.49, 0.00),   # orange
            (0.80, 0.30, 0.90),   # purple
        ]
        n = len(self.history)
        for idx, (px, py) in enumerate(self.history):
            sx, sy = to_screen(px, py)
            is_last = (idx == n - 1)

            # choose colour: blue for latest, cycle for others
            if is_last:
                c = (0.20, 0.60, 1.00)
            else:
                c = COLORS[idx % len(COLORS)]

            # outer glow
            cr.set_source_rgba(*c, 0.25)
            cr.arc(sx, sy, 15, 0, 2 * math.pi); cr.fill()

            # main circle
            cr.set_source_rgb(*c)
            cr.arc(sx, sy, 7, 0, 2 * math.pi); cr.fill()

            # white border
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.set_line_width(1.2)
            cr.arc(sx, sy, 7, 0, 2 * math.pi); cr.stroke()

            # sequence number inside circle
            cr.set_source_rgb(1, 1, 1)
            cr.set_font_size(8)
            lbl = str(idx + 1)
            ext = cr.text_extents(lbl)
            cr.move_to(sx - ext.width / 2, sy + ext.height / 2)
            cr.show_text(lbl)

            # coordinate label outside circle
            cr.set_font_size(10)
            cr.set_source_rgba(0.75, 0.92, 1.0, 0.90)
            cr.move_to(sx + 11, sy - 6)
            cr.show_text(f"({px}, {py})")

    # ── Coordinate utilities ──────────────────────────────────────────────────

    def _screen_to_grid(self, sx, sy):
        """Delegate to logic.screen_to_grid using cached canvas metrics."""
        return screen_to_grid(sx, sy, self._cx, self._cy, self._step, self._cells)

    # ── Canvas events ─────────────────────────────────────────────────────────

    def _canvas_click_cb(self, widget, event):
        if event.button != 1:
            return
        # Only plot if we're in the playing state
        if self.stack.get_visible_child_name() != "playing":
            return
        gx, gy = self._screen_to_grid(event.x, event.y)
        self._add_point(gx, gy)

    def _canvas_motion_cb(self, widget, event):
        if self.stack.get_visible_child_name() != "playing":
            if self.hover_point:
                self.hover_point = None
                self.canvas.queue_draw()
            return
        gx, gy = self._screen_to_grid(event.x, event.y)
        if self.hover_point != (gx, gy):
            self.hover_point = (gx, gy)
            self.canvas.queue_draw()

    def _canvas_leave_cb(self, widget, event):
        self.hover_point = None
        self.canvas.queue_draw()

    # ── Point management ─────────────────────────────────────────────────────

    def _add_point(self, x, y):
        self.history.add(x, y)
        self.guide_point = (x, y)
        self._refresh_points_list()
        self.canvas.queue_draw()
        self._check_completion()

    def _manual_plot_cb(self, widget):
        raw_x = self.x_entry.get_text().strip()
        raw_y = self.y_entry.get_text().strip()
        try:
            x, y = int(raw_x), int(raw_y)
        except ValueError:
            self._flash_hint("⚠ Please enter whole numbers only")
            return
        # logic layer validates range
        ok, reason = validate_coord(x, y, self._cells)
        if not ok:
            self._flash_hint(f"⚠ {reason}")
            return
        self.x_entry.set_text("")
        self.y_entry.set_text("")
        self.x_entry.grab_focus()
        self._add_point(x, y)

    def _flash_hint(self, msg):
        orig = self.playing_hint.get_text()
        self.playing_hint.set_markup(f'<span color="#ff6b6b">{msg}</span>')
        GLib.timeout_add(2500, lambda: self.playing_hint.set_text(orig) or False)

    def _undo_cb(self, btn):
        self.history.undo()
        self.guide_point = self.history[-1] if len(self.history) else None
        self._refresh_points_list()
        self.canvas.queue_draw()

    def _clear_cb(self, btn):
        self.history.clear()
        self.guide_point = None
        self.success_label.hide()
        self._refresh_points_list()
        self.canvas.queue_draw()

    def _connect_toggled_cb(self, btn):
        self.connect_mode = btn.get_active()
        self.canvas.queue_draw()

    def _refresh_points_list(self):
        for child in self.points_list_box.get_children():
            self.points_list_box.remove(child)
        for idx, (x, y) in enumerate(self.history):
            lbl = Gtk.Label(label=f"  {idx+1}.  ({x:>3}, {y:>3})")
            lbl.get_style_context().add_class("point-row")
            lbl.set_xalign(0)
            self.points_list_box.pack_start(lbl, False, False, 0)
        self.points_list_box.show_all()

    # ── Completion check ──────────────────────────────────────────────────────

    def _check_completion(self):
        # logic layer does the set-intersection math
        matched, total = check_completion(self.history, self.current_challenge)
        if total == 0:
            return
        if matched == total:
            self.success_label.set_markup(
                f'<span color="#06d6a0" size="large">⭐ Perfect! All {total} points matched!</span>'
            )
            self.success_label.show()
        elif matched > 0:
            self.success_label.set_markup(
                f'<span color="#ffd166">{matched} / {total} points matched</span>'
            )
            self.success_label.show()

    # ── Help ─────────────────────────────────────────────────────────────────

    def _help_cb(self, btn):
        dialog = Gtk.MessageDialog(
            parent=self, flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="GraphIt — How to Play"
        )
        dialog.format_secondary_text(
            "1. Choose a shape category from the sidebar\n"
            "2. Pick a task (e.g. Right Triangle)\n"
            "3. The ghost shape shows you the TARGET\n"
            "4. Click the grid or type (x,y) to plot points\n"
            "5. Match all the ghost points to complete the task!\n\n"
            "Grid: X goes left(-) and right(+)\n"
            "      Y goes down(-) and up(+)\n\n"
            "Undo removes the last point.\n"
            "Connect toggle draws lines between your points."
        )
        dialog.run()
        dialog.destroy()

    # ── Journal ───────────────────────────────────────────────────────────────

    def read_file(self, file_path):
        if not os.path.exists(file_path):
            return
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            state = data.get("state", {})
            self.history.load(state.get("points", []))
            self.connect_mode = state.get("connect_mode", False)
            self.connect_toggle.set_active(self.connect_mode)
            cat = state.get("category")
            task_name = state.get("task_name")
            if cat and task_name:
                for ch in CHALLENGES.get(cat, []):
                    if ch["name"] == task_name:
                        self._category_clicked_cb(None, cat)
                        self._task_clicked_cb(None, ch)
                        # restore points after task_clicked_cb clears them
                        self.history.load(state.get("points", []))
                        self._refresh_points_list()
                        self.canvas.queue_draw()
                        break
        except Exception as e:
            print(f"GraphIt read_file error: {e}")

    def write_file(self, file_path):
        import time
        try:
            data = {
                "metadata": {"activity": "org.sugarlabs.GraphIt",
                              "timestamp": time.time()},
                "state": {
                    "points": self.history.as_list(),
                    "connect_mode": self.connect_mode,
                    "category": getattr(self, "current_category", None),
                    "task_name": (self.current_challenge["name"]
                                  if self.current_challenge else None),
                },
            }
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"GraphIt write_file error: {e}")
