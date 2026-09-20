from dataclasses import dataclass
import re

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
    file_probe = _task_file_probe(turn.phase_task)
    # phaseTask 可能与上回合普通 LLM 响应同时出现。文件型任务必须先读
    # 题目文件，不能让残留响应抢走这一步。
    if (
        file_probe is not None
        and not cmd_output
        and turn.llm_resp
        and not _extract_answer(turn.llm_resp)
        and not _looks_like_command_response(turn.llm_resp)
    ):
        memory.pioneer_agent_phase = "executing"
        memory.remember_sop(
            memory.task_type or "unknown",
            execute_cmd=file_probe,
        )
        return PioneerDecision(execute_cmd=file_probe)
    if (
        file_probe is not None
        and not turn.llm_resp
        and not cmd_output
        and memory.pioneer_agent_phase != "submitted"
    ):
        # 文件型任务先读取题目，再把真实内容交给 LLM。
        memory.pioneer_agent_phase = "executing"
        memory.remember_sop(
            memory.task_type or "unknown",
            execute_cmd=file_probe,
        )
        return PioneerDecision(execute_cmd=file_probe)
    if turn.llm_resp:
        answer = _extract_answer(turn.llm_resp)
        if answer:
            memory.pioneer_agent_phase = "submitted"
            memory.remember_sop(memory.task_type or "unknown", prompt=answer)
            return PioneerDecision(command=submit_answer(answer))
        command = _extract_command(turn.llm_resp)
        if command and _looks_like_command_response(turn.llm_resp):
            memory.pioneer_agent_phase = "executing"
            memory.remember_sop(
                memory.task_type or "unknown",
                execute_cmd=command,
            )
            return PioneerDecision(execute_cmd=command)
        if _looks_like_task_echo(turn.llm_resp):
            return PioneerDecision(
                prompt=_exploration_prompt(turn, cmd_output),
            )
        if memory.pioneer_agent_phase in {"answering", "exploring"} and cmd_output:
            # ANSWER: 是首选格式；接口没有强制 LLM 必须带前缀。
            # 已经有成功沙盒结果时，非空响应也允许作为最终答案提交，避免卡死。
            answer = turn.llm_resp.strip()
            if answer:
                memory.pioneer_agent_phase = "submitted"
                memory.remember_sop(
                    memory.task_type or "unknown",
                    prompt=answer,
                )
                return PioneerDecision(command=submit_answer(answer))
        if not command:
            return PioneerDecision(
                prompt=_exploration_prompt(turn, cmd_output),
            )
    if cmd_output:
        # 一次命令的成功输出不等于任务答案；文件型任务经常需要多轮探索。
        memory.pioneer_agent_phase = "exploring"
        return PioneerDecision(prompt=_exploration_prompt(turn, cmd_output))
    sop = memory.sop_library.get(memory.task_type or "")
    return PioneerDecision(
        prompt=(
            "你是自进化任务执行 Agent。请阅读任务描述：如果已经能确定最终答案，"
            "只输出 ANSWER: <答案>；否则只输出一条 CMD: <可在无网络沙盒中执行的探索命令>，"
            "只能使用基础 shell/python。若有历史 SOP，请优先验证并复用。任务：\n"
            f"{turn.phase_task}\n历史 SOP：\n{sop or '暂无'}"
        ),
    )


def _exploration_prompt(turn: Turn, output: str) -> str:
    return (
        "请根据当前自进化任务和最新沙盒输出继续完成任务："
        "如果信息不足，只输出 CMD: <一条下一步可执行命令>；"
        "如果已经得到最终答案，只输出 ANSWER: <答案>。不要输出解释。\n"
        f"任务：\n{turn.phase_task}\n沙盒输出：\n{output}"
    )


def _task_file_probe(task: str) -> str | None:
    """识别任务中要求读取的本地 md/txt 文件，先自动完成第一步探索。"""
    # 任务文件名经常紧跟中文标点；`\b` 在中英文边界上并不可靠，
    # 因此只匹配文件名本身，并用白名单限制为沙盒内常见文本文件。
    match = re.search(r"([A-Za-z0-9_.-]+\.(?:md|txt|json|csv))", task)
    if match is None:
        return None
    filename = match.group(1)
    return f"cat {filename}"


def _looks_like_command_response(response: str) -> bool:
    text = response.strip()
    return any(
        line.strip().upper().startswith("CMD:")
        for line in text.splitlines()
    ) or "```" in text


def _looks_like_task_echo(response: str) -> bool:
    text = response.lower()
    return "phase_task" in text or "phasetask" in text


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
