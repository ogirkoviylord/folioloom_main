from dataclasses import dataclass

from translator_service.file_storage import LocalObjectStorage
from translator_service.format_adapters import DOCX_ADAPTER_VERSION
from translator_service.persistent_job_store import (
    PersistentJobStore,
    strict_docx_capability_denial_code,
)
from translator_service.persistent_planner import (
    StrictAdmissionDenied,
    StrictPersistentJobPlan,
    create_persistent_strict_docx_job_plan,
)


@dataclass(frozen=True)
class StrictDocxAdmissionServiceRequest:
    """Internal opt-in request for strict DOCX job admission only."""

    store: PersistentJobStore
    storage: LocalObjectStorage
    approval_id: str
    source_object_key: str
    order_id: str
    user_id: str
    file_name: str
    source_language: str
    target_language: str
    max_fragment_chars: int
    adapter_version: str = DOCX_ADAPTER_VERSION
    prompt_version: str = "plain-v1"
    pricing_snapshot_id: str = "prototype-pricing-v1"
    rights_confirmation: dict | None = None
    translation_mode: str | None = None
    upload_safety_id: str | None = None


def admit_strict_docx_service_request(
    request: StrictDocxAdmissionServiceRequest,
) -> StrictPersistentJobPlan | StrictAdmissionDenied:
    """Admit one explicitly requested strict DOCX job without legacy fallback."""
    denial_code = strict_docx_capability_denial_code(request.store)
    if denial_code is not None:
        return StrictAdmissionDenied(code=denial_code)
    return create_persistent_strict_docx_job_plan(
        store=request.store,
        storage=request.storage,
        approval_id=request.approval_id,
        source_object_key=request.source_object_key,
        order_id=request.order_id,
        user_id=request.user_id,
        file_name=request.file_name,
        source_language=request.source_language,
        target_language=request.target_language,
        max_fragment_chars=request.max_fragment_chars,
        adapter_version=request.adapter_version,
        prompt_version=request.prompt_version,
        pricing_snapshot_id=request.pricing_snapshot_id,
        rights_confirmation=request.rights_confirmation,
        translation_mode=request.translation_mode,
        upload_safety_id=request.upload_safety_id,
    )
