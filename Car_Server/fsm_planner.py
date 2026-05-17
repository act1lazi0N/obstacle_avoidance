import time
from dataclasses import dataclass
from enum import Enum


class DriveState(Enum):
    IDLE = "IDLE"
    FORWARD = "FORWARD"
    BRAKE = "BRAKE"
    REVERSE = "REVERSE"
    TURN = "TURN"
    STUCK = "STUCK"


@dataclass
class PlannerObservation:
    ai_enabled: bool
    model_ready: bool
    camera_ok: bool
    is_blind: bool
    distance_cm: float
    left_score: float
    center_score: float
    right_score: float
    visual_danger: bool
    visual_dead_end: bool
    aeb_triggered: bool
    timestamp: float


@dataclass
class PlannerDecision:
    state: DriveState
    command: str
    speed: int | None
    danger: bool
    dead_end: bool
    aeb_triggered: bool
    turn_direction: str | None
    transition_log: str | None
    reason: str


class DrivePlanner:
    def __init__(
        self,
        forward_speed=50,
        turn_speed=46,
        reverse_speed=40,
        escape_reverse_speed=42,
        escape_turn_speed=48,
        turn_duration=0.55,
        reverse_duration=0.8,
        escape_turn_duration=0.9,
        stuck_pause_duration=0.25,
        stuck_trigger_count=3,
        brake_enter_cm=12.0,
        brake_exit_cm=16.0,
        reverse_enter_cm=18.0,
        reverse_exit_cm=24.0,
        turn_enter_cm=30.0,
        turn_exit_cm=36.0,
    ):
        self.forward_speed = forward_speed
        self.turn_speed = turn_speed
        self.reverse_speed = reverse_speed
        self.escape_reverse_speed = escape_reverse_speed
        self.escape_turn_speed = escape_turn_speed
        self.turn_duration = turn_duration
        self.reverse_duration = reverse_duration
        self.escape_turn_duration = escape_turn_duration
        self.stuck_pause_duration = stuck_pause_duration
        self.stuck_trigger_count = stuck_trigger_count
        self.brake_enter_cm = brake_enter_cm
        self.brake_exit_cm = brake_exit_cm
        self.reverse_enter_cm = reverse_enter_cm
        self.reverse_exit_cm = reverse_exit_cm
        self.turn_enter_cm = turn_enter_cm
        self.turn_exit_cm = turn_exit_cm

        self.state = DriveState.IDLE
        self.command = "stop"
        self.speed = None
        self.turn_direction = None
        self.state_deadline = 0.0
        self.stuck_count = 0
        self.next_escape_turn = "left"
        self.pending_followup_turn_direction = None
        self.pending_followup_turn_speed = None
        self.pending_followup_turn_duration = 0.0
        self.brake_active = False
        self.reverse_active = False
        self.turn_active = False

    @staticmethod
    def _apply_hysteresis(active, value, enter_threshold, exit_threshold):
        if active:
            return value <= exit_threshold
        return value <= enter_threshold

    def _update_distance_zones(self, distance_cm):
        self.brake_active = self._apply_hysteresis(
            self.brake_active,
            distance_cm,
            self.brake_enter_cm,
            self.brake_exit_cm,
        )

        self.reverse_active = not self.brake_active and self._apply_hysteresis(
            self.reverse_active,
            distance_cm,
            self.reverse_enter_cm,
            self.reverse_exit_cm,
        )

        self.turn_active = (
            not self.brake_active
            and not self.reverse_active
            and self._apply_hysteresis(
                self.turn_active,
                distance_cm,
                self.turn_enter_cm,
                self.turn_exit_cm,
            )
        )

    def _choose_turn_direction(self, left_score, right_score):
        if left_score < right_score:
            return "left"
        if right_score < left_score:
            return "right"
        return self.next_escape_turn

    def _build_transition_log(self, previous_state, obs, command):
        return (
            f"{previous_state.value} -> {self.state.value} | "
            f"distance={obs.distance_cm:.1f}cm | "
            f"scores(L/C/R)=({obs.left_score:.2f}/{obs.center_score:.2f}/{obs.right_score:.2f}) | "
            f"command={command}"
        )

    def _emit_decision(self, obs, danger, dead_end, aeb_triggered, reason):
        return PlannerDecision(
            state=self.state,
            command=self.command,
            speed=self.speed,
            danger=danger,
            dead_end=dead_end,
            aeb_triggered=aeb_triggered,
            turn_direction=self.turn_direction,
            transition_log=None,
            reason=reason,
        )

    def _transition(
        self,
        obs,
        new_state,
        command,
        speed,
        danger,
        dead_end,
        aeb_triggered,
        reason,
        deadline=0.0,
        turn_direction=None,
    ):
        previous_state = self.state
        previous_command = self.command
        previous_speed = self.speed

        self.state = new_state
        self.command = command
        self.speed = speed
        self.turn_direction = turn_direction
        self.state_deadline = deadline

        transition_log = None
        if (
            previous_state != self.state
            or previous_command != self.command
            or previous_speed != self.speed
        ):
            transition_log = self._build_transition_log(previous_state, obs, command)

        return PlannerDecision(
            state=self.state,
            command=self.command,
            speed=self.speed,
            danger=danger,
            dead_end=dead_end,
            aeb_triggered=aeb_triggered,
            turn_direction=self.turn_direction,
            transition_log=transition_log,
            reason=reason,
        )

    def _start_turn(self, obs, direction, speed, duration, danger, dead_end, reason):
        return self._transition(
            obs=obs,
            new_state=DriveState.TURN,
            command=direction,
            speed=speed,
            danger=danger,
            dead_end=dead_end,
            aeb_triggered=False,
            reason=reason,
            deadline=obs.timestamp + duration,
            turn_direction=direction,
        )

    def _start_reverse(
        self,
        obs,
        speed,
        duration,
        followup_turn_direction,
        followup_turn_speed,
        followup_turn_duration,
        danger,
        dead_end,
        reason,
    ):
        self.pending_followup_turn_direction = followup_turn_direction
        self.pending_followup_turn_speed = followup_turn_speed
        self.pending_followup_turn_duration = followup_turn_duration
        return self._transition(
            obs=obs,
            new_state=DriveState.REVERSE,
            command="backward",
            speed=speed,
            danger=danger,
            dead_end=dead_end,
            aeb_triggered=False,
            reason=reason,
            deadline=obs.timestamp + duration,
            turn_direction=None,
        )

    def _enter_stuck(self, obs, danger, dead_end, reason):
        followup_turn_direction = self.next_escape_turn
        self.next_escape_turn = "right" if self.next_escape_turn == "left" else "left"
        self.pending_followup_turn_direction = followup_turn_direction
        self.pending_followup_turn_speed = self.escape_turn_speed
        self.pending_followup_turn_duration = self.escape_turn_duration
        return self._transition(
            obs=obs,
            new_state=DriveState.STUCK,
            command="stop",
            speed=None,
            danger=danger,
            dead_end=dead_end,
            aeb_triggered=False,
            reason=reason,
            deadline=obs.timestamp + self.stuck_pause_duration,
            turn_direction=followup_turn_direction,
        )

    def _clear_followup_turn(self):
        self.pending_followup_turn_direction = None
        self.pending_followup_turn_speed = None
        self.pending_followup_turn_duration = 0.0

    def plan(self, obs):
        self._update_distance_zones(obs.distance_cm)
        preferred_turn = self._choose_turn_direction(obs.left_score, obs.right_score)

        danger = self.turn_active or self.reverse_active or obs.visual_danger
        dead_end = self.reverse_active or obs.visual_dead_end
        aeb_triggered = self.brake_active or obs.aeb_triggered

        if not obs.ai_enabled:
            self.stuck_count = 0
            self._clear_followup_turn()
            return self._transition(
                obs,
                DriveState.IDLE,
                "stop",
                None,
                danger,
                dead_end,
                aeb_triggered,
                reason="AI paused",
            )

        if not obs.model_ready or not obs.camera_ok:
            self.stuck_count = 0
            self._clear_followup_turn()
            return self._transition(
                obs,
                DriveState.IDLE,
                "stop",
                None,
                danger,
                dead_end,
                aeb_triggered,
                reason="perception unavailable",
            )

        if obs.is_blind or self.brake_active or obs.aeb_triggered:
            return self._transition(
                obs,
                DriveState.BRAKE,
                "stop",
                None,
                danger,
                dead_end,
                True,
                reason="front safety brake",
            )

        if self.state == DriveState.STUCK:
            if obs.timestamp < self.state_deadline:
                return self._emit_decision(obs, danger, dead_end, aeb_triggered, "stuck pause")
            return self._start_reverse(
                obs=obs,
                speed=self.escape_reverse_speed,
                duration=self.reverse_duration,
                followup_turn_direction=self.pending_followup_turn_direction or self.next_escape_turn,
                followup_turn_speed=self.pending_followup_turn_speed or self.escape_turn_speed,
                followup_turn_duration=self.pending_followup_turn_duration or self.escape_turn_duration,
                danger=danger,
                dead_end=dead_end,
                reason="stuck recovery reverse",
            )

        if self.state == DriveState.REVERSE:
            if obs.timestamp < self.state_deadline:
                return self._emit_decision(obs, danger, dead_end, aeb_triggered, "reverse maneuver")
            if self.pending_followup_turn_direction:
                direction = self.pending_followup_turn_direction
                speed = self.pending_followup_turn_speed or self.turn_speed
                duration = self.pending_followup_turn_duration or self.turn_duration
                self._clear_followup_turn()
                return self._start_turn(
                    obs,
                    direction,
                    speed,
                    duration,
                    danger,
                    dead_end,
                    reason="post-reverse turn",
                )
            if dead_end or danger:
                self.stuck_count += 1
            else:
                self.stuck_count = 0

        if self.state == DriveState.TURN:
            if obs.timestamp < self.state_deadline:
                return self._emit_decision(obs, danger, dead_end, aeb_triggered, "turn maneuver")
            if dead_end or danger:
                self.stuck_count += 1
            else:
                self.stuck_count = 0

        if dead_end:
            if self.stuck_count >= self.stuck_trigger_count:
                return self._enter_stuck(
                    obs,
                    danger,
                    dead_end,
                    reason=f"stuck_count={self.stuck_count}",
                )
            return self._start_reverse(
                obs=obs,
                speed=self.reverse_speed,
                duration=self.reverse_duration,
                followup_turn_direction=preferred_turn,
                followup_turn_speed=self.turn_speed,
                followup_turn_duration=self.turn_duration,
                danger=danger,
                dead_end=dead_end,
                reason="reverse to clear front obstacle",
            )

        if danger:
            if self.stuck_count >= self.stuck_trigger_count:
                return self._enter_stuck(
                    obs,
                    danger,
                    dead_end,
                    reason=f"stuck_count={self.stuck_count}",
                )
            return self._start_turn(
                obs,
                preferred_turn,
                self.turn_speed,
                self.turn_duration,
                danger,
                dead_end,
                reason="turn toward clearer corridor",
            )

        self.stuck_count = max(0, self.stuck_count - 1)
        self._clear_followup_turn()
        return self._transition(
            obs,
            DriveState.FORWARD,
            "go",
            self.forward_speed,
            danger,
            dead_end,
            aeb_triggered,
            reason="clear path",
        )

