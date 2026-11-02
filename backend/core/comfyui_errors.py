"""Safe, actionable ComfyUI request diagnostics without provider response bodies."""


class ComfyRequestError(ValueError):
    def __init__(self, status: int, rejected_nodes: str) -> None:
        self.status_code = status
        self.rejected_nodes = rejected_nodes
        super().__init__(
            f"ComfyUI request returned HTTP {status}. "
            f"Rejected nodes: {rejected_nodes or 'see server logs'}."
        )

    def diagnostic(self) -> str:
        if self.status_code == 400:
            return (
                "ComfyUI rejected the workflow (HTTP 400). "
                f"Rejected nodes: {self.rejected_nodes or 'see ComfyUI server logs'}. "
                "Refresh the model list, select files available on this ComfyUI server, "
                "and run the preset compatibility check."
            )
        return f"ComfyUI returned HTTP {self.status_code}. Check the ComfyUI server and proxy logs."
