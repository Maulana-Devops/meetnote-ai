"""Provider LLM deterministik untuk test dan pengembangan lokal.

Ini BUKAN hasil AI sungguhan. Teks selalu diberi awalan ``[MOCK]`` dan
provider melaporkan ``is_mock=True`` supaya tidak tertukar dengan hasil cloud.
Test menyuntik ``result``/``payload``/``error`` (ringkasan) atau
``action_*`` (action items) lewat konstruktor.
"""

from .base import (
    ActionItemExtractionResult,
    ActionItemInput,
    ExtractedActionItem,
    SummaryInput,
    SummaryResult,
    SummaryTopic,
    parse_action_items_payload,
    parse_summary_payload,
)
from .errors import LlmError, LlmInvalidResultError


class MockLlmProvider:
    """Provider mock yang tidak pernah melakukan panggilan jaringan."""

    name = "mock"
    _model = "mock-1"

    def __init__(
        self,
        *,
        result: SummaryResult | None = None,
        payload: dict | None = None,
        error: LlmError | None = None,
        action_result: ActionItemExtractionResult | None = None,
        action_payload: dict | None = None,
        action_error: LlmError | None = None,
    ) -> None:
        self._result = result
        self._payload = payload
        self._error = error
        self._action_result = action_result
        self._action_payload = action_payload
        self._action_error = action_error

    @property
    def model(self) -> str:
        return self._model

    def validate_configuration(self) -> None:
        return None

    def summarize(self, data: SummaryInput) -> SummaryResult:
        if self._error is not None:
            raise self._error

        if self._payload is not None:
            return parse_summary_payload(
                self._payload, provider=self.name, model=self.model, is_mock=True
            )

        if self._result is not None:
            result = self._result
            return SummaryResult(
                overview=result.overview,
                topics=list(result.topics),
                decisions=list(result.decisions),
                provider=self.name,
                model=self.model,
                is_mock=True,
            )

        if not data.segments:
            raise LlmInvalidResultError(
                "Provider mock tidak menerima segmen — tidak ada ringkasan yang dibuat."
            )

        chosen = data.segments[:3]
        segment_ids = tuple(segment.id for segment in chosen)
        start_seconds = min(segment.start_seconds for segment in chosen)
        end_seconds = max(segment.end_seconds for segment in chosen)
        first_text = chosen[0].text.strip()

        return SummaryResult(
            overview=(
                f"[MOCK] Ringkasan dari {len(data.segments)} segmen transkrip rapat "
                f"{data.meeting_title}."
            ),
            topics=[
                SummaryTopic(
                    title="[MOCK] Topik dari transkrip",
                    detail=f"[MOCK] Cuplikan awal: {first_text}",
                    segment_ids=segment_ids,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                )
            ],
            decisions=[],
            provider=self.name,
            model=self.model,
            is_mock=True,
        )

    def extract_action_items(self, data: ActionItemInput) -> ActionItemExtractionResult:
        if self._action_error is not None:
            raise self._action_error

        if self._action_payload is not None:
            return parse_action_items_payload(
                self._action_payload, provider=self.name, model=self.model, is_mock=True
            )

        if self._action_result is not None:
            result = self._action_result
            return ActionItemExtractionResult(
                items=list(result.items),
                provider=self.name,
                model=self.model,
                is_mock=True,
            )

        if not data.segments:
            return ActionItemExtractionResult(
                items=[], provider=self.name, model=self.model, is_mock=True
            )

        # Deterministik dan sengaja konservatif: tidak mengarang assignee/deadline.
        chosen = data.segments[:3]
        return ActionItemExtractionResult(
            items=[
                ExtractedActionItem(
                    title="[MOCK] Tindak lanjut dari transkrip",
                    description=f"[MOCK] Cuplikan: {chosen[0].text.strip()}",
                    assignee_speaker_label=None,
                    assignee_text=None,
                    deadline_text=None,
                    due_date=None,
                    segment_ids=tuple(segment.id for segment in chosen),
                    start_seconds=min(segment.start_seconds for segment in chosen),
                    end_seconds=max(segment.end_seconds for segment in chosen),
                )
            ],
            provider=self.name,
            model=self.model,
            is_mock=True,
        )
