# ...existing code...
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Optional, Union
from datetime import datetime
from .base import BaseSource, RawTextItem
import logging
from hashlib import sha256
import os

logger = logging.getLogger("narrative.sources.localfile")

class LocalFileSource(BaseSource):
    def __init__(self, directory: Optional[Union[str, Path]] = "data/narrative/raw"):
        self.directory = Path(directory)
        # diagnostics
        self.last_parse_errors_count = 0
        self.last_error_files: List[Path] = []

    def fetch(self, start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[RawTextItem]:
        items: List[RawTextItem] = []
        self.last_parse_errors_count = 0
        self.last_error_files = []
        if not self.directory.exists():
            return items
        files = sorted(self.directory.glob("*.jsonl"))
        errors_dir = Path("data") / "narrative" / "errors"
        errors_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            error_file = errors_dir / f"{f.stem}_errors.jsonl"
            had_error = False
            with f.open("r", encoding="utf-8") as fh, error_file.open("a", encoding="utf-8") as efh:
                for line_no, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = RawTextItem.parse_raw(line)
                    except Exception as e:
                        # write bad line with basic context; do not raise
                        had_error = True
                        self.last_parse_errors_count += 1
                        err_record = {
                            "source_file": str(f),
                            "line_no": line_no,
                            "line": line,
                            "error": str(e),
                        }
                        efh.write(json.dumps(err_record, ensure_ascii=False) + "\n")
                        continue
                    if start and obj.published_at < start:
                        continue
                    if end and obj.published_at >= end:
                        continue
                    items.append(obj)
            if had_error:
                self.last_error_files.append(error_file)
                logger.warning("parse errors in file %s -> %s", f, error_file)
        # deterministic ordering
        items.sort(key=lambda it: (it.published_at.isoformat(), it.id))
        if self.last_parse_errors_count:
            logger.info("LocalFileSource parse errors: %d written to %d files", self.last_parse_errors_count, len(self.last_error_files))
        return items
# ...existing code...