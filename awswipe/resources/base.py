from abc import ABC, abstractmethod
import boto3
from typing import Any, Dict, List, Optional
from awswipe.core.config import Config

class ResourceCleaner(ABC):
    def __init__(self, session: boto3.Session, config: Config, report: Dict[str, Dict[str, List[str]]]):
        self.session = session
        self.config = config
        self.report = report

    def _record_result(self, resource_type, resource_id, success, message=''):
        # If dry-run, we might not want to record as "deleted", but for now we follow original logic
        # The original logic had a wrapper that disabled _record_result or similar in dry-run?
        # Actually original logic: if dry_run: self._record_result = lambda ...: None
        # We should probably handle this better, but let's stick to the pattern:
        # The caller (orchestrator) might handle the dry-run suppression or we check config here.
        
        if self.config.dry_run:
             # In dry run, we don't want to pollute the report with "deleted" if we didn't delete.
             # But we might want to know what WOULD have been deleted.
             # The original code just silenced _record_result in dry_run mode for the orchestrator.
             # Let's keep it simple: we record, but maybe the orchestrator handles the display?
             # Wait, original code:
             # if dry_run: self._record_result = lambda *args, **kwargs: None
             # So it didn't record anything in dry run? That seems wrong for a "report".
             # Ah, the original code printed logs but didn't populate the final report in dry run.
             # Let's respect that behavior for now to be safe, or improve it.
             # "Dry-Run Report" is Ticket 06. So for now, we just follow existing behavior.
             return

        if resource_type not in self.report:
            self.report[resource_type] = {'deleted': [], 'failed': []}
        if success:
            self.report[resource_type]['deleted'].append(resource_id)
        else:
            msg = f"{resource_id} ({message})" if message else resource_id
            self.report[resource_type]['failed'].append(msg)

    @abstractmethod
    def cleanup(self, region: Optional[str] = None):
        pass
