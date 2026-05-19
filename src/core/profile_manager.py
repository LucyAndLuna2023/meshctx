"""ProfileManager — multi-profile management for meshctx.

Profiles are stored under {home}/profiles/{name}/.
The active profile is tracked in {home}/active_profile.
The "default" profile always exists and cannot be deleted.
"""

import os
import shutil
from pathlib import Path


class ProfileManager:
    """Manage multiple isolated configuration profiles."""

    def __init__(self, home: str = None):
        """Initialize with a home directory (default ~/.meshctx)."""
        if home is None:
            home = os.path.expanduser("~/.meshctx")
        self.home = home
        self._profiles_dir = os.path.join(home, "profiles")
        os.makedirs(self._profiles_dir, exist_ok=True)

        # Ensure the default profile always exists
        self._ensure_default()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _ensure_default(self) -> None:
        """Create the default profile directory if missing."""
        default_dir = os.path.join(self._profiles_dir, "default")
        os.makedirs(default_dir, exist_ok=True)

    def _active_file(self) -> str:
        return os.path.join(self.home, "active_profile")

    def _read_active(self) -> str:
        """Return the name of the active profile, defaulting to 'default'."""
        af = self._active_file()
        if os.path.isfile(af):
            try:
                with open(af, "r") as fh:
                    name = fh.read().strip()
                    if name:
                        return name
            except OSError:
                pass
        return "default"

    def _write_active(self, name: str) -> None:
        af = self._active_file()
        with open(af, "w") as fh:
            fh.write(name)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @property
    def active(self) -> str:
        """The currently active profile name."""
        return self._read_active()

    def create(self, name: str) -> None:
        """Create a new profile directory.

        Args:
            name: Profile name (must be a simple directory-safe string).
        """
        path = os.path.join(self._profiles_dir, name)
        os.makedirs(path, exist_ok=True)

    def use(self, name: str) -> None:
        """Switch to a different profile.

        Args:
            name: Name of an existing profile.
        """
        # Validate that the profile exists
        path = os.path.join(self._profiles_dir, name)
        if not os.path.isdir(path):
            raise ValueError(f"Profile '{name}' does not exist")
        self._write_active(name)

    def delete(self, name: str) -> None:
        """Delete a profile directory.

        The default profile cannot be deleted.

        Args:
            name: Profile name to delete.

        Raises:
            ValueError: If attempting to delete the default profile.
        """
        if name == "default":
            raise ValueError("Cannot delete the default profile")
        path = os.path.join(self._profiles_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path)

        # If the deleted profile was active, fall back to default
        if self.active == name:
            self._write_active("default")

    def list(self) -> list:
        """Return a sorted list of all profile names."""
        names = []
        if os.path.isdir(self._profiles_dir):
            for entry in os.listdir(self._profiles_dir):
                full = os.path.join(self._profiles_dir, entry)
                if os.path.isdir(full):
                    names.append(entry)
        return sorted(names)

    def clone(self, src: str, dst: str) -> None:
        """Clone an existing profile to a new name via directory copy.

        Args:
            src: Source profile name.
            dst: Destination profile name (created if missing).
        """
        src_path = os.path.join(self._profiles_dir, src)
        dst_path = os.path.join(self._profiles_dir, dst)
        if not os.path.isdir(src_path):
            raise ValueError(f"Source profile '{src}' does not exist")
        shutil.copytree(src_path, dst_path, dirs_exist_ok=True)

    def get_path(self, name: str) -> str:
        """Return the filesystem path for a named profile."""
        return os.path.join(self._profiles_dir, name)

    def get_active_path(self) -> str:
        """Return the filesystem path for the currently active profile."""
        return self.get_path(self.active)
