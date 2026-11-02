"""Identify the text-model dependency separately from the image provider."""


class PromptPreparationError(RuntimeError):
    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        super().__init__("Small/Utility LLM image-prompt preparation failed.")
