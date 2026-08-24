import logging

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from ks_includes.screen_panel import ScreenPanel

# Jog pacing.
#
# Klipper has no way to flush the motion queue, so "stop when the finger lifts"
# has to come from never letting the queue get deep in the first place. Each
# tick we command motion up to (now + LEAD_S) and no further, so the queue holds
# at most LEAD_S of travel: enough for lookahead to junction the chunks into
# continuous motion, and also the worst-case overrun on release.
#
# The target is anchored to the monotonic clock rather than accumulated per
# tick, so a late or dropped tick corrects itself instead of drifting.
# Pacing.
#
# The governing fact, measured on this machine: KLIPPER NEVER JUNCTIONS
# EXTRUDE-ONLY MOVES. Move.calc_junction() returns early when either move is
# non-kinematic, so max_start_v2 stays 0 and every pure-E move accelerates from
# a standstill and decelerates back to one, even when the next move is already
# queued behind it. Streaming 40 chunks back to back achieved 250 mm3/s against
# 420 for the same material as one move.
#
# Two consequences, and they point the same way:
#
#   - A deep queue buys nothing. It cannot smooth the motion, because the moves
#     will not merge however many are waiting. It only buys run-on.
#   - What a chunk costs is its material PLUS one acceleration ramp. So the
#     chunk length, not the tick rate, sets both the throughput and the latency.
#
# So the queue is modelled locally instead of measured. Each chunk's execution
# time is known — material/peak + peak/accel — which means the panel can track
# exactly how far ahead of real time it has committed, and simply decline to
# send when that exceeds LEAD_S. No status queries, no feedback loop chasing a
# sensor that is 250ms stale and bursty.
#
# CHUNK_S is the material in each chunk, in seconds of flow. It has a hard floor
# of 4*flow/accel — below that no peak speed exists that can average out to the
# requested flow, because the ramp eats the whole chunk. At 489 mm3/s and
# 20000 mm3/s^2 that floor is 0.098s, so 0.12 leaves a little room. Above that
# flow the chunk stops averaging out and the jog quietly runs slower than asked;
# chunk_peak() detects it and falls back rather than pretending.
TICK_MS = 40
CHUNK_S = 0.12
LEAD_S = 0.13

# Klipper schedules the first move of a burst BUFFER_TIME_START into the future
# (0.25s in this version, a module constant and not configurable). Measured: a
# 1.00s move issued from idle left print_time - estimated_print_time at 1.15s.
# Nothing recovers it, so it is seeded into the queue model rather than ignored.
START_OFFSET = 0.25

# Ceiling on a single uninterrupted hold, in mm3 of E. A touchscreen that drops
# the release event should not be able to empty the cartridge. 10000 mm3 is
# 10 mL, or about 51 auger revolutions at the current geometry.
MAX_JOG_VOL = 10000.0

# The same cap for LOAD mode, where E is mm of plunger travel rather than mm3.
# Expressed in travel because that is the quantity with a hard physical stop:
# the barrel has a finite length and the plunger can reach the end of it.
MAX_JOG_TRAVEL = 100.0

# Smallest comfortable touch target for the rows that are not the jog pads, as
# a fraction of screen height.
#
# It has to be a fraction rather than a pixel count: on this machine fbcp
# mirrors an 800x480 framebuffer down onto a 480x320 3.5" ILI9486 panel, so a
# rendered pixel is only ~0.1mm tall and a pixel-based minimum would silently
# mean different physical sizes at different render resolutions. The panel is
# ~49mm tall, so 9mm of finger is ~18.5% of the screen however many pixels that
# happens to be.
MIN_TOUCH_FRAC = 0.185
CAPTION_FRAC = 0.05

# Icon scale for the +/- and settings buttons. KlippyGtk derives a button's
# natural height from its icon, and the stock scale yields ~140px rows that
# leave the jog pads with almost nothing. 0.55 lands the control rows at
# roughly a fingertip while the pads keep the remaining height.
CTRL_ICON = 0.55

# Hold-to-repeat on the +/- buttons. A tap moves exactly one step; the value is
# only sent to Klipper on release, so a long press is one command rather than a
# burst of them.
REPEAT_DELAY_MS = 400
REPEAT_MS = 120

# Flow spans two working regimes — a few hundred mm3/s for printing, the full
# ceiling for loading and purging — so a single step size cannot serve both. The
# repeat accelerates after ACCEL_AFTER ticks (~1.4s) to cross that range without
# giving up fine control on a tap.
#
# Two tiers, because the balance band now reaches 1:20 — 390 steps end to end at
# a step that has to stay 0.05, since trimming pressure around 1:1 is the whole
# point of the control. A tap still moves one step; ~1.4s in it moves five; ~5s
# in it moves twenty-five, which crosses the whole band in a few more seconds.
ACCEL_AFTER = 12
ACCEL_FACTOR = 5
ACCEL_AFTER_2 = 40
ACCEL_FACTOR_2 = 25
ACCEL_FIELDS = ("rate", "balance")


class Panel(ScreenPanel):
    """Clay extrusion control.

    Everything here is volumetric: one mm of commanded E is one mm3 of clay,
    and flow is in mm3/s. Volume is the only unit the screw and the piston
    share, so it is the only unit in which either a rate or a ratio between
    them means anything. RPM is each motor's private business and appears only
    as a derived readout.

      Flow      mm3/s of clay leaving the nozzle.
      Balance   the auger's side of a Plunger:Auger ratio. 1:1.00 means the
                plunger supplies exactly what the auger delivers. Raising it
                turns the auger further per mm of plunger travel, so pressure
                falls; lowering it advances the plunger further per auger turn,
                so the clay is compressed harder.

    The two are orthogonal: flow is what you want out, balance is how hard it
    is pressed out, and changing the balance leaves the flow where you set it —
    the auger simply turns faster or slower to keep delivering it. That only
    works because flow is the stored setting; in auger RPM, every pressure trim
    would silently have moved the output rate too.

    LOAD mode replaces both with a single plunger speed in RPM. Charging a
    barrel is not extrusion: the plunger runs alone at up to its full motor
    speed, far faster than any auger could follow, so there is no flow to meter
    and no ratio to hold. The unit changes with the mode because the operation
    does — volume is the common unit only while both motors are moving.
    """

    def __init__(self, screen, title):
        title = title or _("Clay")
        super().__init__(screen, title)

        cfg = self._printer.config.get("gcode_macro CLAY", {})
        self.base_rd = self._cfg_float(cfg, "variable_plunger_base_rd", 0.4)
        self.barrel_area = self._cfg_float(cfg, "variable_barrel_area", 3216.99)
        self.vol_rev = self._cfg_float(cfg, "variable_auger_vol_rev", 195.6)
        self.balance = self._cfg_float(cfg, "variable_balance", 25.0)
        self.balance_min = self._cfg_float(cfg, "variable_balance_min", 0.5)
        self.balance_max = self._cfg_float(cfg, "variable_balance_max", 50.0)
        self.balance_step = self._cfg_float(cfg, "variable_balance_step", 0.05)
        self.flow = self._cfg_float(cfg, "variable_flow", 100.0)
        self.flow_step = self._cfg_float(cfg, "variable_flow_step", 5.0)
        self.flow_min = self._cfg_float(cfg, "variable_flow_min", 5.0)
        # THE process ceiling. Both motors' caps derive from it. Set from the
        # console (CLAY_SET_LIMITS) — it is a commissioning value, not something
        # to be nudged mid-job, so it does not earn a button.
        self.max_flow = self._cfg_float(cfg, "variable_max_flow", 200.0)
        self.jog_velocity = self._cfg_float(cfg, "variable_jog_velocity", 1000.0)
        # Motor limits — what each can physically turn, whatever the process wants.
        self.plunger_max_rpm = self._cfg_float(cfg, "variable_plunger_max_rpm", 800.0)
        self.auger_motor_max = self._cfg_float(cfg, "variable_auger_motor_max_rpm", 1500.0)
        # LOAD mode: the plunger alone, in its own motor RPM.
        self.mode = str(cfg.get("variable_mode", "extrude")).strip("'\" ").lower()
        self.load_rpm = self._cfg_float(cfg, "variable_load_rpm", 500.0)
        self.load_max_rpm = self._cfg_float(cfg, "variable_load_max_rpm", 500.0)
        self.load_rpm_step = self._cfg_float(cfg, "variable_load_rpm_step", 10.0)
        self.load_rpm_min = self._cfg_float(cfg, "variable_load_rpm_min", 5.0)

        self._jog_dir = 0
        self._jog_timer = None
        self._jog_active = False
        self._jog_t0 = 0.0
        self._jog_sent = 0.0
        self._q_end = 0.0   # when the queued motion is modelled to finish
        self._adjust = None
        self._adjust_timer = None
        self._adjust_ticks = 0

        self.vertical = self._screen.vertical_mode
        # Rows other than the jog pads get a fixed slice sized for a fingertip;
        # the pads take everything left over. Capped so that on a short screen
        # the control rows can never crowd the pads out.
        self.row_h = min(
            int(self._screen.height * MIN_TOUCH_FRAC),
            int(self._gtk.content_height * 0.22),
        )
        self.caption_h = int(self._screen.height * CAPTION_FRAC)

        self.buttons = {
            "up": self._gtk.Button("arrow-up", _("Plunger Up"), "color1"),
            "down": self._gtk.Button("arrow-down", _("Plunger Down"), "color4"),
            # CTRL_ICON keeps these rows short enough that the jog pads keep the
            # rest of the screen: a button's natural height is driven by its
            # icon, and the default scale makes a row ~140px tall.
            "balance_down": self._gtk.Button("decrease", None, "color3", CTRL_ICON),
            "balance_up": self._gtk.Button("increase", None, "color3", CTRL_ICON),
            "flow_down": self._gtk.Button("decrease", None, "color2", CTRL_ICON),
            "flow_up": self._gtk.Button("increase", None, "color2", CTRL_ICON),
            # lines=1: KlippyGtk reserves two text lines by default, which alone
            # adds ~40px to the row these sit in.
            "resync": self._gtk.Button("refresh", _("Re-sync"), "color3", CTRL_ICON, lines=1),
            "mode": self._gtk.Button("extrude", _("Extrude"), "color2", CTRL_ICON, lines=1),
        }
        # Up advances the plunger on this machine, so up is +E. Inverted from
        # the usual convention, which is why it is stated here rather than
        # inferred: the plunger's physical sense per E sign is a fact about the
        # hardware, and printing depends on positive E extruding, so this must
        # never be "fixed" by touching extruder1's dir_pin.
        for name, direction in (("up", 1), ("down", -1)):
            btn = self.buttons[name]
            btn.connect("button-press-event", self.jog_start, direction)
            btn.connect("button-release-event", self.jog_stop)
            btn.connect("leave-notify-event", self.jog_leave)
        for name, field, steps in (
            ("balance_down", "balance", -1),
            ("balance_up", "balance", 1),
            ("flow_down", "rate", -1),
            ("flow_up", "rate", 1),
        ):
            btn = self.buttons[name]
            btn.connect("button-press-event", self.adjust_start, field, steps)
            btn.connect("button-release-event", self.adjust_stop)
            btn.connect("leave-notify-event", self.adjust_leave)
        self.buttons["resync"].connect("clicked", self.resync)
        self.buttons["mode"].connect("clicked", self.toggle_mode)

        for key in ("readout", "balance", "flow"):
            self.labels[key] = Gtk.Label(hexpand=True, vexpand=True)
            self.labels[key].set_justify(Gtk.Justification.CENTER)
        self.labels["readout"].set_vexpand(False)

        self.labels["clay_menu"] = self._build_main()

        self.menu = ["clay_menu"]
        self.content.add(self.labels["clay_menu"])
        self.update_readout()

    # ── layout ──────────────────────────────────────────────────────────────

    def _build_main(self):
        # A vertical box, not a row-homogeneous grid: homogeneous rows all take
        # the tallest row's minimum, which overflowed the screen and pushed the
        # bottom row off. Here the two control rows take their natural height
        # (kept small by CTRL_ICON) and the jog pads expand into the rest.
        jog_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL
            if self.vertical
            else Gtk.Orientation.HORIZONTAL,
            homogeneous=True,
        )
        jog_box.add(self.buttons["up"])
        jog_box.add(self.buttons["down"])

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        layout.pack_start(self.labels["readout"], False, False, 0)
        layout.pack_start(jog_box, True, True, 0)
        for dec, value, inc, extra in (
            ("balance_down", "balance", "balance_up", "resync"),
            ("flow_down", "flow", "flow_up", "mode"),
        ):
            row = Gtk.Box(homogeneous=True)
            row.add(self.buttons[dec])
            row.add(self.labels[value])
            row.add(self.buttons[inc])
            row.add(self.buttons[extra])
            layout.pack_start(row, False, False, 0)
        return layout

    @staticmethod
    def _cfg_float(cfg, key, fallback):
        try:
            return float(cfg.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    # ── lifecycle ───────────────────────────────────────────────────────────

    def activate(self):
        self.update_sensitivity()
        # KlipperScreen never subscribes to gcode_macro objects, so the live
        # settings have to be pulled explicitly whenever the panel is opened.
        self._screen._ws.send_method(
            "printer.objects.query",
            {"objects": {"gcode_macro CLAY": None}},
            self._got_clay_state,
        )

    def deactivate(self):
        self.jog_stop()
        self.adjust_stop()
        # Never leave the machine unsynced behind us. A print started from any
        # other panel would otherwise drive the auger with the plunger parked.
        if self.mode == "load":
            self.set_mode("extrude")

    def _got_clay_state(self, response, *args):
        try:
            state = response["result"]["status"]["gcode_macro CLAY"]
        except (KeyError, TypeError):
            logging.warning("Clay panel: no gcode_macro CLAY, is clay_macros.cfg included?")
            return
        for attr, key in (
            ("base_rd", "plunger_base_rd"),
            ("barrel_area", "barrel_area"),
            ("vol_rev", "auger_vol_rev"),
            ("balance", "balance"),
            ("balance_min", "balance_min"),
            ("balance_max", "balance_max"),
            ("balance_step", "balance_step"),
            ("flow", "flow"),
            ("flow_step", "flow_step"),
            ("flow_min", "flow_min"),
            ("max_flow", "max_flow"),
            ("jog_velocity", "jog_velocity"),
            ("load_accel_eff", "load_accel_eff"),
            ("plunger_max_rpm", "plunger_max_rpm"),
            ("auger_motor_max", "auger_motor_max_rpm"),
            ("load_rpm", "load_rpm"),
            ("load_rpm_step", "load_rpm_step"),
            ("load_rpm_min", "load_rpm_min"),
            ("load_max_rpm", "load_max_rpm"),
        ):
            setattr(self, attr, self._cfg_float(state, key, getattr(self, attr)))
        self.mode = str(state.get("mode", self.mode)).strip("'\" ").lower()
        self.update_sensitivity()
        self.update_readout()

    def process_update(self, action, data):
        if action != "notify_status_update":
            return
        # "paused" belongs here as much as "ready". The print-start handover
        # pauses ON PURPOSE so the operator can prime by hand, and this guard
        # fired on every status update during that pause — killing the hold
        # after a single chunk. Symptom: the clay only moves per button press
        # instead of flowing while the button is held.
        if self._printer.state not in ("ready", "paused") and self._jog_timer is not None:
            self.jog_stop()
        self.update_sensitivity()


    def update_sensitivity(self):
        # Loading clay is an idle-only job: it drives the same E axis the print
        # is using. The flow settings stay live so they can be tuned mid-print.
        # Paused counts as available. The print-start handover pauses on purpose
        # so the operator can prime by hand and settle the ratio, so jogging,
        # the mode switch and re-sync all have to work in that state.
        idle = self._printer.state in ("ready", "paused")
        live = self._printer.state in ("ready", "printing", "paused")
        for name in ("up", "down"):
            self.buttons[name].set_sensitive(idle)
        for name in ("flow_up", "flow_down"):
            self.buttons[name].set_sensitive(live)
        # Balance is meaningless with the auger parked — there is no ratio when
        # only one motor turns.
        for name in ("balance_up", "balance_down"):
            self.buttons[name].set_sensitive(live and self.mode != "load")
        # Both of these swap the active extruder, which would corrupt a running job.
        for name in ("resync", "mode"):
            self.buttons[name].set_sensitive(idle)

    # ── jog ─────────────────────────────────────────────────────────────────

    def jog_start(self, widget, event, direction):
        if self._jog_timer is not None:
            return False
        if self._printer.state not in ("ready", "paused"):
            self._screen.show_popup_message(_("Only available when idle or paused"))
            return False
        self._jog_dir = direction
        self._jog_t0 = GLib.get_monotonic_time() / 1e6
        self._jog_sent = 0.0
        self._q_end = self._jog_t0 + START_OFFSET
        widget.get_style_context().add_class("button_active")
        # Before the first chunk: a move's acceleration is fixed when it is
        # planned, so raising it afterwards would not shorten this hold's stop.
        self._screen._ws.api.gcode_script("CLAY_JOG_BEGIN")
        self._jog_active = True
        self._jog_tick()  # prime the queue without waiting for the first tick
        self._jog_timer = GLib.timeout_add(TICK_MS, self._jog_tick)
        return False

    def jog_accel(self):
        """Acceleration the macros will be using, in the active E unit."""
        cfg = self._printer.config.get("gcode_macro CLAY", {})
        # load_accel_eff, not load_accel: the auger's own acceleration ceiling
        # can cut it hard at low load speeds, and a queue model that used the
        # uncut figure would under-estimate every chunk and let the queue grow.
        key = "variable_load_accel_eff" if self.mode == "load" else "variable_jog_accel"
        return self._cfg_float(cfg, key, 40.0 if self.mode == "load" else 20000.0)

    def chunk_peak(self, feed, accel):
        """Peak feedrate that makes a CHUNK_S chunk AVERAGE out to `feed`.

        A chunk of material m run at peak p takes m/p + p/accel — the ramp is
        pure overhead, since the move cannot inherit speed from the one before
        it. Asking for exactly `feed` would therefore deliver noticeably less,
        so the peak is raised until the average lands where it was asked to.
        Solves m/p + p/a = CHUNK_S for p, taking the slower of the two roots.
        """
        disc = CHUNK_S * CHUNK_S - 4.0 * CHUNK_S * feed / accel
        if disc <= 0:
            # Chunk too short for any peak to average out: the ramp would eat
            # all of it. Run as fast as is sensible and accept the shortfall.
            return feed * 2.0
        return (CHUNK_S - disc ** 0.5) * accel / 2.0

    def peak_cap(self):
        """Hard ceiling on the commanded peak, in the active E unit.

        In load mode this is the plunger's load ceiling: the ramp compensation
        above deliberately asks for more than the setpoint, and without a cap
        that would push the plunger past the very limit load_max_rpm exists to
        enforce."""
        if self.mode == "load":
            return min(self.load_max_rpm, self.plunger_max_rpm) * self.base_rd / 60.0
        return self.jog_velocity

    def jog_leave(self, widget, event):
        # Safety net for a finger sliding off the pad. GTK also synthesises
        # enter/leave pairs when it takes and drops the implicit pointer grab
        # around a press; acting on those would abort every hold the instant it
        # started, so only a real pointer-out counts.
        if event.mode != Gdk.CrossingMode.NORMAL:
            return False
        return self.jog_stop()

    def jog_stop(self, widget=None, event=None):
        if self._jog_timer is not None:
            GLib.source_remove(self._jog_timer)
            self._jog_timer = None
        self._jog_dir = 0
        # Guarded: jog_stop is reached from release, pointer-out, the distance
        # cap and deactivate(), and only the first of those should restore the
        # acceleration.
        if self._jog_active:
            self._jog_active = False
            self._screen._ws.api.gcode_script("CLAY_JOG_END")
        for name in ("up", "down"):
            self.buttons[name].get_style_context().remove_class("button_active")
        return False

    def jog_feed(self):
        """Rate in whatever unit E currently carries: mm3/s when synced, mm/s of
        plunger travel in load mode."""
        if self.mode == "load":
            return self.effective_load_rpm() * self.base_rd / 60.0
        return self.e_rate()

    def jog_cap(self):
        return MAX_JOG_TRAVEL if self.mode == "load" else MAX_JOG_VOL

    def _jog_tick(self):
        if self._jog_dir == 0:
            return False
        feed = self.jog_feed()
        cap = self.jog_cap()
        now = GLib.get_monotonic_time() / 1e6
        if self._q_end < now:
            self._q_end = now          # the machine has caught up and gone idle
        if self._q_end - now < LEAD_S and self._jog_sent < cap:
            accel = self.jog_accel()
            peak = max(feed, min(self.chunk_peak(feed, accel), self.peak_cap()))
            delta = min(feed * CHUNK_S, cap - self._jog_sent)
            self._jog_sent += delta
            self._screen._ws.api.gcode_script(
                f"CLAY_JOG D={self._jog_dir * delta:.3f} F={peak * 60:.0f}"
            )
            # What that chunk will cost the machine: its material at the peak
            # rate, plus the one ramp it can never avoid.
            self._q_end += delta / peak + peak / accel
        if self._jog_sent >= cap:
            logging.info(f"Clay jog reached the {cap} limit, stopping")
            # Returning False already drops this source; clear the handle first
            # so jog_stop() does not try to remove it a second time.
            self._jog_timer = None
            self.jog_stop()
            return False
        return True

    # ── derived quantities ──────────────────────────────────────────────────
    #
    # These mirror _CLAY_RECALC rather than reading its cached results, so the
    # display tracks a balance change immediately instead of waiting for the
    # macro round-trip.

    def e_rate(self):
        """Commanded E rate, mm3/s — identical to the flow, because E is
        plunger-referenced and the plunger supplies exactly 1 mm3 per E mm at
        every ratio."""
        return self.effective_flow()

    def auger_rpm(self):
        """Screw revolutions per minute.

        NOT e_rate/vol_rev. E is plunger-referenced — one mm of E is one mm3 out
        of the nozzle at any ratio — so the auger's rotation distance is
        vol_rev/balance and the ratio multiplies its speed directly. Dropping
        the balance here under-reported the screw by exactly the ratio: 10 RPM
        displayed while it was turning at 212."""
        return self.e_rate() * 60.0 * self.balance / self.vol_rev

    def plunger_rpm(self):
        return self.effective_flow() * 60.0 / (self.barrel_area * self.base_rd)

    def flow_cap(self):
        """The process ceiling after both motors have had their say, all three
        expressed as mm3/s out of the nozzle so they can be compared."""
        by_plunger = self.plunger_max_rpm * self.barrel_area * self.base_rd / 60.0
        by_auger = self.auger_motor_max * self.vol_rev / (60.0 * self.balance)
        return min(self.max_flow, by_plunger, by_auger)

    def effective_flow(self):
        return max(self.flow_min, min(self.flow, self.flow_cap()))

    def effective_load_rpm(self):
        cap = min(self.load_max_rpm, self.plunger_max_rpm)
        return max(self.load_rpm_min, min(self.load_rpm, cap))

    # ── settings ────────────────────────────────────────────────────────────

    def adjust_start(self, widget, event, field, steps):
        if self._adjust_timer is not None:
            return False
        self._adjust = (field, steps)
        self._adjust_ticks = 0
        self._apply_step(field, steps)
        self._adjust_timer = GLib.timeout_add(REPEAT_DELAY_MS, self._adjust_first)
        return False

    def _adjust_first(self):
        # The pause before auto-repeat kicks in, so a tap is exactly one step.
        if self._adjust is None:
            return False
        self._apply_step(*self._adjust)
        self._adjust_timer = GLib.timeout_add(REPEAT_MS, self._adjust_repeat)
        return False

    def _adjust_repeat(self):
        if self._adjust is None:
            return False
        field, steps = self._adjust
        self._adjust_ticks += 1
        if field in ACCEL_FIELDS and self._adjust_ticks > ACCEL_AFTER:
            steps *= ACCEL_FACTOR_2 if self._adjust_ticks > ACCEL_AFTER_2 else ACCEL_FACTOR
        self._apply_step(field, steps)
        return True

    def adjust_leave(self, widget, event):
        if event.mode != Gdk.CrossingMode.NORMAL:
            return False
        return self.adjust_stop()

    def adjust_stop(self, widget=None, event=None):
        if self._adjust_timer is not None:
            GLib.source_remove(self._adjust_timer)
            self._adjust_timer = None
        if self._adjust is not None:
            field = self._adjust[0]
            self._adjust = None
            self._commit(field)
        return False

    def _apply_step(self, field, steps):
        # Local only — the value is pushed to Klipper once, on release.
        if field == "balance":
            new = round(self.balance + steps * self.balance_step, 2)
            self.balance = max(self.balance_min, min(self.balance_max, new))
            # A balance that costs the auger more turns per mm3 drags the
            # working flow down with it.
            self.flow = self.effective_flow()
        elif field == "rate":
            # One pair of buttons, whichever rate the mode is about.
            if self.mode == "load":
                new = round(self.load_rpm + steps * self.load_rpm_step)
                cap = min(self.load_max_rpm, self.plunger_max_rpm)
                self.load_rpm = max(self.load_rpm_min, min(cap, new))
            else:
                new = round(self.flow + steps * self.flow_step)
                self.flow = max(self.flow_min, min(self.flow_cap(), new))
        self.update_readout()

    def _commit(self, field):
        if field == "balance":
            self._screen._ws.api.gcode_script(f"CLAY_SET_BALANCE BALANCE={self.balance:.2f}")
            self._screen._ws.api.gcode_script(f"CLAY_SET_FLOW FLOW={self.flow:.0f}")
        elif self.mode == "load":
            self._screen._ws.api.gcode_script(f"CLAY_SET_LOAD_RPM RPM={self.load_rpm:.0f}")
        else:
            self._screen._ws.api.gcode_script(f"CLAY_SET_FLOW FLOW={self.flow:.0f}")

    def resync(self, widget):
        self._screen._ws.api.gcode_script("CLAY_RESYNC")

    def toggle_mode(self, widget):
        self.set_mode("extrude" if self.mode == "load" else "load")

    def set_mode(self, mode):
        # Stop any hold first: the active extruder and E units are about to
        # change under it, and a queued chunk would be interpreted in the new
        # frame — mm3 of clay read as mm of plunger travel, or the reverse.
        self.jog_stop()
        self.mode = mode
        self._screen._ws.api.gcode_script(f"CLAY_MODE MODE={mode.upper()}")
        self.update_sensitivity()
        self.update_readout()

    def update_readout(self):
        loading = self.mode == "load"
        self.buttons["mode"].set_label(_("Load") if loading else _("Extrude"))

        # Each value carries its own caption — on this panel a bare "489" next
        # to a bare "1.00" tells the operator nothing.
        self.labels["balance"].set_markup(
            f"<small>{_('Plunger : Auger')}</small>\n"
            + (f"<big><b>1 : {self.balance:.2f}</b></big>" if not loading
               else f"<big><b>—</b></big>")
        )

        if loading:
            rpm = self.effective_load_rpm()
            mms = rpm * self.base_rd / 60.0
            self.labels["flow"].set_markup(
                f"<small>{_('Plunger RPM')}</small>\n<big><b>{rpm:.0f}</b></big>"
            )
            self.labels["readout"].set_markup(
                f"<b>{_('LOAD')}</b> · {_('plunger only')} · <b>{mms:.2f}</b> mm/s"
                + f" · {_('max')} <b>{min(self.load_max_rpm, self.plunger_max_rpm):.0f}</b> RPM"
            )
            return

        flow = self.effective_flow()
        cap = self.flow_cap()
        motor_limited = self.auger_motor_max * self.vol_rev / (60.0 * self.balance) <= cap
        self.labels["flow"].set_markup(
            f"<small>{_('Flow mm³/s')}</small>\n<big><b>{flow:.0f}</b></big>"
        )

        # RPM belongs here rather than on a control: it is what each motor ends
        # up doing, not something the operator sets.
        limit = _("motor max") if motor_limited else _("max")
        if self.vertical:
            text = (
                f"<b>{flow * 0.06:.1f}</b> mL/min  ·  "
                + _("auger")
                + f" <b>{self.auger_rpm():.0f}</b>  ·  "
                + _("plunger")
                + f" <b>{self.plunger_rpm():.0f}</b> RPM"
            )
        else:
            text = (
                f"<b>{flow * 0.06:.1f}</b> mL/min   →   "
                + _("auger")
                + f" <b>{self.auger_rpm():.0f}</b> RPM  ·  "
                + _("plunger")
                + f" <b>{self.plunger_rpm():.0f}</b> RPM"
                + f"   ·   {limit} <b>{cap:.0f}</b>"
            )
        self.labels["readout"].set_markup(text)
