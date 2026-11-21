# -*- coding: utf-8 -*-
"""Loading of the SpatiaLite extension across QGIS builds and platforms."""

import os


class SpatialiteLoaderMixin:
    """Finds and loads mod_spatialite into the sqlite3 connection."""

    def _load_spatialite(self):
        """Load the SpatiaLite extension, trying multiple names and paths.

        QGIS 4 macOS bundles ship ``Contents/Frameworks/mod_spatialite.so``;
        SQLite's bare ``"mod_spatialite"`` lookup appends ``.dylib`` there and
        fails, so the explicit ``.so`` name must also be tried.
        """
        errors = []

        # 1. Library names resolved by the dynamic loader (same order as
        #    qgis.utils.spatialite_connect).
        for name in ("mod_spatialite", "mod_spatialite.so", "mod_spatialite.dylib"):
            try:
                self.connection.load_extension(name)
                return
            except Exception as e:
                errors.append(f"{name}: {e}")

        # 2. QGIS Mac Packager's finder (older QGIS 3 bundles)
        try:
            from qgis.find_mod_spatialite import mod_spatialite_path
            self.connection.load_extension(mod_spatialite_path())
            return
        except Exception:
            pass

        # 3. Search next to the running QGIS install (any .app name/version)
        candidates = []
        try:
            from qgis.core import QgsApplication
            prefix = QgsApplication.prefixPath()
            if prefix:
                for rel in ("", "lib", "Frameworks", "../Frameworks",
                            "../../Frameworks", "MacOS/lib", "../MacOS/lib"):
                    candidates.append(os.path.normpath(os.path.join(prefix, rel)))
        except Exception:
            pass
        for app in ("QGIS.app", "QGIS-LTR.app"):
            candidates.append(f"/Applications/{app}/Contents/Frameworks")
            candidates.append(f"/Applications/{app}/Contents/MacOS/lib")

        import glob
        for folder in dict.fromkeys(candidates):
            for path in sorted(glob.glob(os.path.join(folder, "mod_spatialite*"))):
                if not path.endswith((".so", ".dylib", ".dll")):
                    continue
                try:
                    self.connection.load_extension(path)
                    return
                except Exception as e:
                    errors.append(f"{path}: {e}")

        raise Exception(
            "Could not load SpatiaLite extension.\n"
            + "\n".join(errors)
            + "\nMake sure SpatiaLite is installed and accessible."
        )
