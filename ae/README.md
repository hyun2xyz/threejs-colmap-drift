# Build the editable After Effects project

1. Follow the repository setup to generate the plate, HDRI, GLBs and water pass. From the repository root, run `python scene/prepare.py` and `python scene/stabilize.py` as described in [the scene guide](../scene/README.md).
2. In an AE version with Advanced 3D, native GLB import and environment lights, start with a fresh, empty, unsaved project. Choose **File → Scripts → Run Script File** and select `ae/Build_Drift.jsx`. Keep the adjacent `read_json.jsxinc` in place.
3. The builder saves `Drift_08s.aep` at the repository root. It requires a free output filename. If an input or native check fails after import, inspect the error and use the **Build Drift** undo group to discard the partial build.

| Comp | Contents |
| --- | --- |
| 01 DRIFT | Stabilized picture, with the same translation, roll and crop applied to plate and CG. |
| 02 SOURCE | Plate and CG in the original camera coordinates. |
| 03 ALPHA | Water above the object pass, with transparency for recompositing. |
| 04 OBJECTS | Six animated GLB layers, a keyed two-node camera, a panorama and an environment light. |

To export a source-aligned overlay, render comp 03 as RGB + Alpha. On an English installation with the **High Quality with Alpha** template, the builder adds the item to the Render Queue when `Drift_Source_Alpha.mov` is available as an output name. Otherwise, choose an alpha-capable preset and a free filename yourself. Interpret the generated water input as straight alpha. For an exported overlay, choose the alpha interpretation that matches the selected output module.

To change the six models' environment, run `ae/Set_Object_HDRI.jsx` and choose an equirectangular HDR/EXR or panorama video. A video freezes at its first frame. To change the reflection or background refraction **inside the water**, rerender the water pass with the replacement inputs, then reload that footage in AE.
