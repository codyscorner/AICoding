"""Folder organization strategies for File Copy Move Manager application"""

import os
from datetime import datetime
from enum import Enum
from typing import Optional


class FolderStructure(Enum):
    """Folder organization structures"""
    PRESERVE = "preserve"  # Keep original folder structure
    FLAT = "flat"  # No subfolders
    BY_YEAR = "year"  # YYYY/
    BY_YEAR_MONTH = "year_month"  # YYYY/MM/
    BY_YEAR_MONTH_DAY = "year_month_day"  # YYYY/MM/DD/
    BY_DATE = "date"  # YYYY-MM-DD/
    BY_MONTH = "month"  # YYYY-MM/


class FolderOrganizer:
    """Handles folder organization based on file dates"""

    @staticmethod
    def get_destination_subfolder(
        file_path: str,
        structure: FolderStructure,
        source_root: Optional[str] = None,
        use_file_date: bool = True
    ) -> str:
        """
        Get the subfolder path based on organization structure

        Args:
            file_path: Path to the file
            structure: Folder structure to use
            source_root: Root source folder (for preserving structure)
            use_file_date: If True, use file's date; otherwise use current date

        Returns:
            Relative subfolder path (empty string for flat structure)
        """
        if structure == FolderStructure.PRESERVE and source_root:
            # Preserve original folder structure
            file_dir = os.path.dirname(file_path)
            if file_dir.startswith(source_root):
                rel_path = os.path.relpath(file_dir, source_root)
                return "" if rel_path == "." else rel_path
            return ""

        if structure == FolderStructure.FLAT:
            return ""

        # Get datetime
        dt = datetime.now()
        if use_file_date and os.path.exists(file_path):
            try:
                timestamp = os.path.getmtime(file_path)
                dt = datetime.fromtimestamp(timestamp)
            except (OSError, ValueError, OverflowError):
                pass  # Corrupt/zero timestamp — fall back to current date

        return FolderOrganizer._subfolder_for_datetime(dt, structure)

    @staticmethod
    def subfolder_for_mtime(mtime: float, structure: FolderStructure) -> str:
        """
        Same answer as get_destination_subfolder for the date-based structures,
        but from an mtime the caller already has — no stat() call. The copy
        planner uses this so scanning 250K files doesn't stat each one twice.

        An unusable timestamp (corrupt, out of range) falls back to today's
        date, exactly like get_destination_subfolder.
        """
        if structure in (FolderStructure.PRESERVE, FolderStructure.FLAT):
            return ""
        try:
            dt = datetime.fromtimestamp(mtime)
        except (OSError, ValueError, OverflowError):
            dt = datetime.now()
        return FolderOrganizer._subfolder_for_datetime(dt, structure)

    @staticmethod
    def _subfolder_for_datetime(dt: datetime, structure: FolderStructure) -> str:
        """Format a date into the sub-folder path for a date-based structure."""
        if structure == FolderStructure.BY_YEAR:
            return dt.strftime("%Y")

        elif structure == FolderStructure.BY_YEAR_MONTH:
            return os.path.join(dt.strftime("%Y"), dt.strftime("%m"))

        elif structure == FolderStructure.BY_YEAR_MONTH_DAY:
            return os.path.join(
                dt.strftime("%Y"),
                dt.strftime("%m"),
                dt.strftime("%d")
            )

        elif structure == FolderStructure.BY_DATE:
            return dt.strftime("%Y-%m-%d")

        elif structure == FolderStructure.BY_MONTH:
            return dt.strftime("%Y-%m")

        else:
            return ""

    @staticmethod
    def create_folder_structure(
        base_path: str,
        subfolder: str
    ) -> str:
        """
        Create folder structure and return full path

        Args:
            base_path: Base destination path
            subfolder: Relative subfolder path

        Returns:
            Full path to destination folder

        Raises:
            OSError: If folder cannot be created
        """
        if not subfolder:
            return base_path

        full_path = os.path.join(base_path, subfolder)
        os.makedirs(full_path, exist_ok=True)
        return full_path

    @staticmethod
    def get_folder_structure_example(structure: FolderStructure) -> str:
        """
        Get an example of the folder structure

        Args:
            structure: Folder structure type

        Returns:
            Example string
        """
        dt = datetime(2025, 11, 27, 14, 30, 0)
        sep = os.sep  # Use OS-specific separator (\ for Windows, / for Unix)

        if structure == FolderStructure.PRESERVE:
            return f"dest_folder{sep}original{sep}path{sep}"

        if structure == FolderStructure.FLAT:
            return f"dest_folder{sep}"

        elif structure == FolderStructure.BY_YEAR:
            return f"dest_folder{sep}{dt.strftime('%Y')}{sep}"

        elif structure == FolderStructure.BY_YEAR_MONTH:
            return f"dest_folder{sep}{dt.strftime('%Y')}{sep}{dt.strftime('%m')}{sep}"

        elif structure == FolderStructure.BY_YEAR_MONTH_DAY:
            return f"dest_folder{sep}{dt.strftime('%Y')}{sep}{dt.strftime('%m')}{sep}{dt.strftime('%d')}{sep}"

        elif structure == FolderStructure.BY_DATE:
            return f"dest_folder{sep}{dt.strftime('%Y-%m-%d')}{sep}"

        elif structure == FolderStructure.BY_MONTH:
            return f"dest_folder{sep}{dt.strftime('%Y-%m')}{sep}"

        else:
            return f"dest_folder{sep}"
