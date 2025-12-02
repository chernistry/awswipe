from dataclasses import dataclass
from typing import Optional

@dataclass
class Config:
    region: Optional[str] = None
    dry_run: bool = True
    verbose: int = 0
