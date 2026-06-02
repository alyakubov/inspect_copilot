"""CesiumJS 3D viewer for the Buildings view.

Returns a standalone HTML page (loaded via st.components.v1.html) that:
- pulls CesiumJS from its public CDN
- authenticates via CESIUM_ION_TOKEN to use Cesium World Terrain + Bing imagery
- overlays Cesium OSM Buildings (LOD1 extrusions, global coverage)
- flies the camera to the target building's coordinates with a tilted angle
- drops a labelled marker at the location

The token is embedded in client-side HTML — this is the normal model for Cesium
Ion. Pick a token scope that only grants read access to the assets you ship
(assets:read + assets:limited-list is the right minimum).
"""

from __future__ import annotations

import json
import os


_TOKEN = os.environ.get("CESIUM_ION_TOKEN")


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>3D view</title>
  <script src="https://cesium.com/downloads/cesiumjs/releases/1.123/Build/Cesium/Cesium.js"></script>
  <link href="https://cesium.com/downloads/cesiumjs/releases/1.123/Build/Cesium/Widgets/widgets.css" rel="stylesheet" />
  <style>
    html, body, #cesiumContainer {
      width: 100%; height: 100%; margin: 0; padding: 0; overflow: hidden;
      font-family: sans-serif;
    }
  </style>
</head>
<body>
  <div id="cesiumContainer"></div>
  <script>
    Cesium.Ion.defaultAccessToken = "__TOKEN__";

    (async () => {
      const viewer = new Cesium.Viewer("cesiumContainer", {
        terrain: Cesium.Terrain.fromWorldTerrain(),
        timeline: false,
        animation: false,
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        fullscreenButton: true,
        infoBox: false,
        selectionIndicator: false,
      });

      try {
        const buildings = await Cesium.createOsmBuildingsAsync();
        viewer.scene.primitives.add(buildings);
      } catch (e) {
        console.warn("OSM Buildings tileset failed to load:", e);
      }

      const lat = __LAT__;
      const lon = __LON__;

      const target = viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(lon, lat),
        point: {
          pixelSize: 14,
          color: Cesium.Color.fromCssColorString("#1f77b4"),
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          text: __NAME__,
          font: "14px sans-serif",
          pixelOffset: new Cesium.Cartesian2(0, -22),
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          showBackground: true,
          backgroundColor: Cesium.Color.BLACK.withAlpha(0.6),
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });

      // HeadingPitchRange is relative to the entity, not absolute. The camera
      // ends up 500m away from the marker, tilted 30 degrees downward, with
      // the marker centered in the view.
      viewer.flyTo(target, {
        offset: new Cesium.HeadingPitchRange(
          Cesium.Math.toRadians(0),     // heading
          Cesium.Math.toRadians(-30),   // pitch: look down 30 degrees
          500                            // range: 500m from the target
        ),
        duration: 2.5,
      });
    })();
  </script>
</body>
</html>
"""


def viewer_html(latitude: float, longitude: float, name: str) -> str:
    """Return a standalone HTML page that renders a CesiumJS 3D view of the
    given location, with a labelled marker at (latitude, longitude).

    If CESIUM_ION_TOKEN is missing, returns a friendly notice instead so the UI
    keeps working without a token.
    """
    if not _TOKEN:
        return (
            "<div style='padding:1em;font-family:sans-serif;color:#900;'>"
            "<b>CESIUM_ION_TOKEN is not set.</b><br>"
            "Add a token from <a href='https://cesium.com/ion' target='_blank'>"
            "cesium.com/ion</a> to your <code>.env</code> to enable the 3D view."
            "</div>"
        )
    return (
        _HTML.replace("__TOKEN__", _TOKEN)
             .replace("__LAT__", repr(float(latitude)))
             .replace("__LON__", repr(float(longitude)))
             .replace("__NAME__", json.dumps(name))
    )
