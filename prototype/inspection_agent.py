from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Literal, NotRequired, TypedDict


EventName = Literal["meta", "delta", "done"]
AgentEvent = tuple[EventName, dict[str, Any]]


class AgentState(TypedDict, total=False):
    payload: dict[str, Any]
    message: str
    session_id: str
    active_session_id: str
    previous_messages: list[dict[str, Any]]
    summary: dict[str, Any]
    memory: dict[str, Any]
    intent: dict[str, Any]
    tool_call: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    action: str
    ai_config: dict[str, Any]
    answer_parts: list[str]
    answer: str
    job: dict[str, Any] | None
    mode: str
    streamed: bool
    confirmation_required: str
    stop_reason: str
    model_answer: str
    error: str


class AgentResult(TypedDict):
    answer: str
    action: str
    job: dict[str, Any] | None
    mode: str
    session_id: str
    sessions: list[dict[str, Any]]
    confirmation_required: NotRequired[str]
    tool_call: NotRequired[dict[str, Any] | None]
    tool_result: NotRequired[dict[str, Any] | None]


@dataclass(frozen=True)
class InspectionAgentDeps:
    begin_chat_turn: Callable[[str, str], tuple[str, list[dict[str, Any]]]]
    finish_chat_turn: Callable[[str, str], list[dict[str, Any]]]
    read_summary: Callable[[], dict[str, Any]]
    read_memory: Callable[..., dict[str, Any]]
    detect_tool_call: Callable[[str], dict[str, Any] | None]
    route_intent: Callable[[str, dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]], dict[str, Any]]
    resolve_routed_tool_call: Callable[[dict[str, Any]], dict[str, Any] | None]
    action_from_tool_call: Callable[[dict[str, Any] | None], str]
    is_inspection_related: Callable[[str, str], bool]
    out_of_scope_answer: Callable[[], str]
    tool_requires_confirmation: Callable[[dict[str, Any] | None, str], str]
    tool_title: Callable[[dict[str, Any] | str | None], str]
    execute_tool_call: Callable[[dict[str, Any] | None], dict[str, Any]]
    wait_for_job: Callable[[str, int], dict[str, Any]]
    render_failure_recovery: Callable[[dict[str, Any] | None, dict[str, Any]], str]
    call_chat_model: Callable[[str, str, dict[str, Any], dict[str, Any], list[dict[str, Any]]], str]
    call_chat_model_stream: Callable[[str, str, dict[str, Any], dict[str, Any], list[dict[str, Any]]], Iterable[str]]
    answer_chat: Callable[[str, dict[str, Any], str, str], str]
    write_memory: Callable[[dict[str, Any]], None]


class InspectionAgent:
    def __init__(self, deps: InspectionAgentDeps):
        self.deps = deps
        self._graph = self._build_graph()

    def invoke(self, payload: dict[str, Any]) -> AgentResult:
        state = self._run_graph(self._initial_state(payload))
        state = self._call_model_once(state)
        return self._finish(state)

    def stream(self, payload: dict[str, Any]) -> Iterator[AgentEvent]:
        state = self._run_graph(self._initial_state(payload))
        yield "meta", {
            "session_id": state.get("active_session_id", ""),
            "action": state.get("action", "none"),
        }

        if state.get("stop_reason") == "out_of_scope":
            yield from self._emit_answer(state, self.deps.out_of_scope_answer(), "inspection-scope-guard")
        elif state.get("stop_reason") == "confirmation_required":
            required = str(state.get("confirmation_required") or "")
            text = f"我识别到你想执行“{self.deps.tool_title(state.get('tool_call'))}”，但这个动作会修改线上数据。请明确输入“{required}”后再执行。"
            yield from self._emit_answer(state, text, "confirmation-required")
        elif state.get("stop_reason") == "tool_call_failed":
            yield from self._emit_answer(state, str(state.get("error") or "工具调用失败。"), "tool-call-failed")
        else:
            yield from self._stream_model_answer(state)

        result = self._finish(state)
        done_payload: dict[str, Any] = dict(result)
        yield "done", done_payload

    def _initial_state(self, payload: dict[str, Any]) -> AgentState:
        return {
            "payload": payload,
            "message": str(payload.get("message") or ""),
            "session_id": str(payload.get("session_id") or ""),
            "ai_config": payload.get("ai") if isinstance(payload.get("ai"), dict) else {},
            "answer_parts": [],
            "job": None,
            "tool_call": None,
            "tool_result": None,
            "mode": "mimo-chat-stream",
            "streamed": False,
        }

    def _build_graph(self):
        try:
            from langgraph.graph import END, StateGraph
        except Exception:
            return None

        graph = StateGraph(AgentState)
        graph.add_node("load_context", self._load_context)
        graph.add_node("scope_guard", self._scope_guard)
        graph.add_node("confirmation_gate", self._confirmation_gate)
        graph.add_node("start_action_job", self._start_action_job)
        graph.set_entry_point("load_context")
        graph.add_edge("load_context", "scope_guard")
        graph.add_conditional_edges(
            "scope_guard",
            self._route_after_scope,
            {
                "stop": END,
                "continue": "confirmation_gate",
            },
        )
        graph.add_conditional_edges(
            "confirmation_gate",
            self._route_after_confirmation,
            {
                "stop": END,
                "continue": "start_action_job",
            },
        )
        graph.add_edge("start_action_job", END)
        return graph.compile()

    def _run_graph(self, state: AgentState) -> AgentState:
        if self._graph is not None:
            return self._graph.invoke(state)
        for node in (self._load_context, self._scope_guard):
            state.update(node(state))
        if self._route_after_scope(state) == "stop":
            return state
        state.update(self._confirmation_gate(state))
        if self._route_after_confirmation(state) == "stop":
            return state
        state.update(self._start_action_job(state))
        return state

    def _load_context(self, state: AgentState) -> AgentState:
        message = str(state.get("message") or "")
        session_id = str(state.get("session_id") or "")
        active_session_id, previous_messages = self.deps.begin_chat_turn(message, session_id)
        summary = self.deps.read_summary()
        memory = self.deps.read_memory(active_session_id)
        tool_call = self.deps.detect_tool_call(message)
        action = self.deps.action_from_tool_call(tool_call)
        intent = {"action": action, "tool_call": tool_call, "source": "rules"}
        if action == "none":
            intent = self.deps.route_intent(
                message,
                summary,
                self.deps.read_memory(active_session_id, True),
                state.get("ai_config") or {},
                previous_messages,
            )
            tool_call = self.deps.resolve_routed_tool_call(intent)
            action = self.deps.action_from_tool_call(tool_call)
        return {
            "active_session_id": active_session_id,
            "previous_messages": previous_messages,
            "summary": summary,
            "memory": memory,
            "intent": intent,
            "tool_call": tool_call,
            "action": action,
        }

    def _scope_guard(self, state: AgentState) -> AgentState:
        message = str(state.get("message") or "")
        action = str(state.get("action") or "none")
        if self.deps.is_inspection_related(message, action):
            return {}
        return {
            "stop_reason": "out_of_scope",
            "mode": "inspection-scope-guard",
        }

    def _confirmation_gate(self, state: AgentState) -> AgentState:
        action = str(state.get("action") or "none")
        if action == "none":
            return {}
        required = self.deps.tool_requires_confirmation(state.get("tool_call"), str(state.get("message") or ""))
        if not required:
            return {}
        return {
            "confirmation_required": required,
            "stop_reason": "confirmation_required",
            "mode": "confirmation-required",
        }

    def _start_action_job(self, state: AgentState) -> AgentState:
        action = str(state.get("action") or "none")
        if action == "none":
            return {}
        tool_result = self.deps.execute_tool_call(state.get("tool_call"))
        if not tool_result.get("ok"):
            return {
                "tool_result": tool_result,
                "stop_reason": "tool_call_failed",
                "mode": "tool-call-failed",
                "error": str(tool_result.get("message") or tool_result.get("error") or "工具调用失败。"),
            }
        return {"job": tool_result.get("job"), "tool_result": tool_result}

    def _route_after_scope(self, state: AgentState) -> str:
        return "stop" if state.get("stop_reason") else "continue"

    def _route_after_confirmation(self, state: AgentState) -> str:
        return "stop" if state.get("stop_reason") else "continue"

    def _call_model_once(self, state: AgentState) -> AgentState:
        if state.get("stop_reason") == "out_of_scope":
            state["answer"] = self.deps.out_of_scope_answer()
            return state
        if state.get("stop_reason") == "confirmation_required":
            required = str(state.get("confirmation_required") or "")
            state["answer"] = f"我识别到你想执行“{self.deps.tool_title(state.get('tool_call'))}”，但这个动作会修改线上数据。请明确输入“{required}”后再执行。"
            return state
        if state.get("stop_reason") == "tool_call_failed":
            state["answer"] = str(state.get("error") or "工具调用失败。")
            return state

        message = str(state.get("message") or "")
        action = str(state.get("action") or "none")
        self._wait_for_action_job(state)
        summary = state.get("summary") or {}
        if action != "none":
            failure_recovery = self.deps.render_failure_recovery(state.get("job"), summary)
            if failure_recovery:
                state["answer"] = failure_recovery
                state["mode"] = "failure-recovery"
                return state

        model_answer = ""
        try:
            ai_config = dict(state.get("ai_config") or {})
            ai_config["_session_id"] = str(state.get("active_session_id") or "")
            model_answer = self.deps.call_chat_model(
                message,
                action,
                summary,
                ai_config,
                state.get("previous_messages") or [],
            )
        except Exception as exc:
            model_answer = f"模型调用暂时失败，已使用本地规则继续处理。错误：{exc}"
            state["mode"] = "model-error-fallback"

        state["model_answer"] = model_answer
        state["answer"] = self.deps.answer_chat(message, summary, action, model_answer)
        if state.get("mode") != "model-error-fallback":
            state["mode"] = "mimo-chat-with-local-actions" if model_answer else "local-action-fallback"
        return state

    def _stream_model_answer(self, state: AgentState) -> Iterator[AgentEvent]:
        action = str(state.get("action") or "none")
        if action != "none":
            prefix = f"已开始执行：{self.deps.tool_title(state.get('tool_call') or action)}。任务面板会持续刷新步骤、状态和最近日志。\n"
            yield from self._emit_text(state, prefix)
        self._wait_for_action_job(state)
        if action != "none":
            failure_recovery = self.deps.render_failure_recovery(state.get("job"), state.get("summary") or {})
            if failure_recovery:
                state["mode"] = "failure-recovery"
                yield from self._emit_text(state, failure_recovery)
                return

        try:
            ai_config = dict(state.get("ai_config") or {})
            ai_config["_session_id"] = str(state.get("active_session_id") or "")
            for chunk in self.deps.call_chat_model_stream(
                str(state.get("message") or ""),
                action,
                state.get("summary") or {},
                ai_config,
                state.get("previous_messages") or [],
            ):
                state["streamed"] = True
                yield from self._emit_text(state, chunk)
        except Exception as exc:
            fallback = f"模型调用暂时失败，已使用本地规则继续处理。错误：{exc}"
            text = fallback if action != "none" else self.deps.answer_chat(
                str(state.get("message") or ""),
                state.get("summary") or {},
                action,
                fallback,
            )
            state["mode"] = "model-error-fallback"
            yield from self._emit_text(state, text)

        if not state.get("streamed") and not state.get("answer_parts"):
            fallback = self.deps.answer_chat(
                str(state.get("message") or ""),
                state.get("summary") or {},
                action,
                "",
            )
            state["mode"] = "local-action-fallback"
            yield from self._emit_text(state, fallback)

    def _wait_for_action_job(self, state: AgentState) -> None:
        action = str(state.get("action") or "none")
        if action == "none":
            return
        job = state.get("job") or {}
        job_id = str(job.get("id") or "")
        if not job_id:
            return
        state["job"] = self.deps.wait_for_job(job_id, 60 * 60)
        state["summary"] = self.deps.read_summary()

    def _emit_answer(self, state: AgentState, text: str, mode: str) -> Iterator[AgentEvent]:
        state["mode"] = mode
        yield from self._emit_text(state, text)

    def _emit_text(self, state: AgentState, text: str) -> Iterator[AgentEvent]:
        if not text:
            return
        state.setdefault("answer_parts", []).append(text)
        yield "delta", {"text": text}

    def _finish(self, state: AgentState) -> AgentResult:
        answer = str(state.get("answer") or "".join(state.get("answer_parts") or []))
        state["answer"] = answer
        sessions = self.deps.finish_chat_turn(str(state.get("active_session_id") or ""), answer)
        result: AgentResult = {
            "answer": answer,
            "action": str(state.get("action") or "none"),
            "job": state.get("job"),
            "mode": str(state.get("mode") or "mimo-chat-stream"),
            "session_id": str(state.get("active_session_id") or ""),
            "sessions": sessions,
            "tool_call": state.get("tool_call"),
            "tool_result": state.get("tool_result"),
        }
        if state.get("confirmation_required"):
            result["confirmation_required"] = str(state["confirmation_required"])
        self.deps.write_memory(dict(state))
        return result
