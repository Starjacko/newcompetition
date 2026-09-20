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
    # 自进化任务期间离开任务点一格会直接结束任务，所以不能正常回防或寻矿。
    if memory.task_position is not None and distance(pioneer.pos, memory.task_position) > 1:
        step = next_step_near(turn, pioneer, memory.task_position)
        return PioneerDecision(command=move(step) if step else None)
    cmd_output = _usable_cmd_output(turn.last_cmd_result)
    memory.remember_sop(memory.task_type or "unknown", output=cmd_output)
    if memory.pioneer_agent_phase == "answering":
        if turn.llm_resp:
            # ANSWER: 是首选格式；但接口没有强制 LLM 必须带前缀。
            # 已经有成功沙盒结果时，非空响应也应作为最终答案提交，避免任务卡在 answering。
            answer = _extract_answer(turn.llm_resp) or turn.llm_resp.strip()
            if answer:
                memory.pioneer_agent_phase = "submitted"
                memory.remember_sop(
                    memory.task_type or "unknown",
                    prompt=answer,
                )
                return PioneerDecision(command=submit_answer(answer))
        return PioneerDecision(
            prompt="请只输出当前自进化任务的最终答案，必须使用 ANSWER: <答案> 格式，"
            "不要输出解释或代码：\n"
            f"{turn.phase_task}\n沙盒输出：\n{cmd_output}",
        )
    if cmd_output:
        # 沙盒有输出时，下一步先让 LLM 把探索结果整理成最终答案。
        memory.pioneer_agent_phase = "answering"
        memory.remember_sop(
            memory.task_type or "unknown",
            output=cmd_output,
        )
        return PioneerDecision(
            prompt="请根据当前自进化任务描述和沙盒输出生成最终答案，只输出 ANSWER: 后的答案：\n"
            f"{turn.phase_task}\n沙盒输出：\n{cmd_output}",
        )
    if turn.llm_resp:
        answer = _extract_answer(turn.llm_resp)
        if answer:
            memory.pioneer_agent_phase = "submitted"
            memory.remember_sop(memory.task_type or "unknown", prompt=answer)
            return PioneerDecision(command=submit_answer(answer))
        command = _extract_command(turn.llm_resp)
        if not command:
            return PioneerDecision(
                prompt="请为当前自进化任务输出一条可执行探索命令，格式为 CMD: <命令>。\n"
                f"{turn.phase_task}",
            )
        memory.pioneer_agent_phase = "executing"
        memory.remember_sop(
            memory.task_type or "unknown",
            execute_cmd=command,
        )
        return PioneerDecision(execute_cmd=command)
    sop = memory.sop_library.get(memory.task_type or "")
    return PioneerDecision(
        prompt=(
            "你是自进化任务执行 Agent。请阅读任务描述：如果已经能确定最终答案，"
            "只输出 ANSWER: <答案>；否则只输出一条 CMD: <可在无网络沙盒中执行的探索命令>，"
            "只能使用基础 shell/python。若有历史 SOP，请优先验证并复用。任务：\n"
            f"{turn.phase_task}\n历史 SOP：\n{sop or '暂无'}"
        ),
    )


def _extract_command(response: str) -> str:
    """Keep the LLM adapter small so command-format changes stay local."""
    text = response.strip()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("CMD:"):
            return stripped[4:].strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if "\n" in text:
                first, rest = text.split("\n", 1)
                if first.strip().lower() in {"sh", "bash", "shell", "python", "python3"}:
                    text = rest
    return text.strip()


def _extract_answer(response: str) -> str:
    for line in response.strip().splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("ANSWER:"):
            return stripped[7:].strip()
    return ""


def _usable_cmd_output(output: str) -> str:
    text = output.strip()
    if not text:
        return ""
    if text.startswith("[TIMEOUT]") or text.startswith("[JUDGER_ERROR]"):
        return ""
    if text.startswith("[exitCode:"):
        first_line, _, rest = text.partition("\n")
        if first_line != "[exitCode:0]":
            return ""
        return rest.strip()
    return text


def _best_task(turn: Turn):
    valid = [
        task for task in turn.player_tasks
        if task.is_valid and task.cooldown_rounds == 0
    ]
    return max(valid, key=lambda task: (task.gold_reward, task.score_reward), default=None)
