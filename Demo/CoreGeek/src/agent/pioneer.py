from dataclasses import dataclass

from .commands import accept_task, move, submit_answer
from .config import StrategyConfig
from .grid import next_step_near
from .memory import PersistentMemory
from .protocol import Turn, Unit, distance


@dataclass(frozen=True, slots=True)
class PioneerDecision:
    command: dict | None = None
    prompt: str = ""
    execute_cmd: str = ""


def plan(
    turn: Turn,
    pioneer: Unit,
    memory: PersistentMemory,
    config: StrategyConfig,
) -> PioneerDecision:
    if turn.phase_task:
        memory.pioneer_phase = "active_task"
        return _active_task(turn, pioneer, memory)

    if memory.completed_tasks >= config.task_count_target:
        memory.pioneer_phase = "support"
        return PioneerDecision()

    task = _best_task(turn)
    if task is None:
        memory.pioneer_phase = "find_task"
        return PioneerDecision()
    memory.task_position = task.position
    memory.task_type = task.task_type
    memory.pioneer_phase = "go_task"
    if distance(pioneer.pos, task.position) <= 1:
        memory.task_started_round = turn.round_no
        return PioneerDecision(command=accept_task())
    step = next_step_near(turn, pioneer, task.position)
    return PioneerDecision(command=move(step) if step else None)


def _active_task(turn: Turn, pioneer: Unit, memory: PersistentMemory) -> PioneerDecision:
    # During a self-evolution task, leaving the task point ends the task.
    if memory.task_position is not None and distance(pioneer.pos, memory.task_position) > 1:
        step = next_step_near(turn, pioneer, memory.task_position)
        return PioneerDecision(command=move(step) if step else None)
    memory.remember_sop(
        memory.task_type or "unknown",
        output=turn.last_cmd_result,
    )
    if memory.pioneer_agent_phase == "answering":
        if turn.llm_resp:
            memory.pioneer_agent_phase = "submitted"
            memory.remember_sop(
                memory.task_type or "unknown",
                prompt=turn.llm_resp,
            )
            return PioneerDecision(command=submit_answer(turn.llm_resp))
        return PioneerDecision(
            prompt="请只输出当前自进化任务的最终答案，不要解释过程：\n"
            f"{turn.phase_task}\n沙盒输出：\n{turn.last_cmd_result}",
        )
    if turn.last_cmd_result:
        memory.pioneer_agent_phase = "answering"
        memory.remember_sop(
            memory.task_type or "unknown",
            output=turn.last_cmd_result,
        )
        return PioneerDecision(
            prompt="请根据当前自进化任务描述和沙盒输出，生成最终答案：\n"
            f"{turn.phase_task}\n沙盒输出：\n{turn.last_cmd_result}",
        )
    if turn.llm_resp:
        memory.pioneer_agent_phase = "executing"
        command = _extract_command(turn.llm_resp)
        memory.remember_sop(
            memory.task_type or "unknown",
            execute_cmd=command,
        )
        return PioneerDecision(execute_cmd=command)
    sop = memory.sop_library.get(memory.task_type or "")
    return PioneerDecision(
        prompt=(
            "你是自进化任务执行 Agent。请阅读任务描述，先给出可在无网络沙盒中执行的"
            "最小探索命令，只使用基础 shell/python，并在下一轮根据输出继续。"
            "如果下方有历史 SOP，请优先验证并复用。任务：\n"
            f"{turn.phase_task}\n历史 SOP：\n{sop or '暂无'}"
        ),
    )


def _extract_command(response: str) -> str:
    """Keep the LLM adapter small so command-format changes stay local."""
    text = response.strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if "\n" in text:
                first, rest = text.split("\n", 1)
                if first.strip().lower() in {"sh", "bash", "shell", "python", "python3"}:
                    text = rest
    return text.strip()


def _best_task(turn: Turn):
    valid = [
        task for task in turn.player_tasks
        if task.is_valid and task.cooldown_rounds == 0
    ]
    return max(valid, key=lambda task: (task.gold_reward, task.score_reward), default=None)
