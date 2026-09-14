from __future__ import annotations


class AIToolError(Exception):
    def __init__(
        self, message: str, *, code: str, details: dict[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class AIToolNotFound(AIToolError):
    def __init__(self, tool_name: str) -> None:
        super().__init__("AI tool not found", code="ai_tool_not_found", details={"tool": tool_name})


class AIToolForbidden(AIToolError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            "AI tool is not allowed for this actor",
            code="ai_tool_forbidden",
            details={"tool": tool_name},
        )


class AIToolConfirmationRequired(AIToolError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            "explicit user confirmation is required",
            code="ai_confirmation_required",
            details={"tool": tool_name},
        )


class AIToolScopeError(AIToolError):
    def __init__(self, message: str = "AI tool scope is invalid") -> None:
        super().__init__(message, code="ai_scope_violation")
