#include "read_json.jsxinc"

/* File > Scripts > Run Script File. Use a fresh, empty, unsaved project. */
(function () {
    var root = new File($.fileName).parent.parent;
    var batch = $.global.DRIFT_BATCH === true;
    var grouped = false;
    function file(path) { return new File(root.fullName + "/" + path); }
    function required(path) {
        var f = file(path);
        if (!f.exists) throw Error("Missing input: " + path);
        return f;
    }
    function imported(f) { return app.project.importFile(new ImportOptions(f)); }
    function requirePlate(item, label, cam) {
        if (item.width !== cam.width || item.height !== cam.height ||
            Math.abs(item.pixelAspect - 1) > .001 ||
            Math.abs(item.frameRate - cam.fps[0] / cam.fps[1]) > .001 ||
            Math.round(item.duration * item.frameRate) !== cam.count) {
            throw Error(label + " must be 1920x1080 square pixels, 192 frames at 24000/1001 fps");
        }
    }
    function posAE(x) { return [960 + 1000*x[0], 540 - 1000*x[1], -1000*x[2]]; }
    function build() {
        var p = app.project;
        if (!p || p.file || p.numItems !== 0 || p.dirty) {
            throw Error("Start with a fresh empty project. Save your current work first.");
        }
        var projectFile = file("Drift_08s.aep");
        var alphaFile = file("Drift_Source_Alpha.mov");
        if (projectFile.exists) throw Error("Drift_08s.aep already exists in the repository root.");
        var cam = driftReadJSON(required("scene/camera_ae.json"));
        var layout = driftReadJSON(required("scene/layout.json"));
        var stab = driftReadJSON(required("scene/stabilize.json"));
        var bounds = driftReadJSON(required("Models/bounds.json"));
        var flaskFile = required("Models/Flask.glb"), cupFile = required("Models/Cup.glb");
        var plateFile = required("Footage/Forest_08s.mov");
        var lightFile = required("Lighting/Forest_FrameLight.hdr");
        var waterFile = required("Water/Water_Refraction.mov");
        if (cam.count !== 192 || cam.width !== 1920 || cam.height !== 1080 ||
            cam.fps[0] !== 24000 || cam.fps[1] !== 1001 || cam.position.length !== cam.count ||
            cam.poi.length !== cam.count || cam.roll.length !== cam.count || cam.probe.length !== cam.count ||
            layout.tracks.length !== 7 || stab.rows.length !== cam.count || !(stab.crop >= 1)) {
            throw Error("Camera, layout or stabilization data does not match the shot");
        }
        var fps = cam.fps[0] / cam.fps[1], duration = cam.count / fps, times = [];
        for (var k = 0; k < cam.count; k++) times.push(k / fps);
        function comp(name) {
            return p.items.addComp(name, cam.width, cam.height, 1, duration, fps);
        }
        function layer(parent, src) {
            var l = parent.layers.add(src);
            l.inPoint = 0; l.outPoint = duration;
            return l;
        }
        app.beginUndoGroup("Build Drift");
        grouped = true;
        p.bitsPerChannel = 32;
        p.workingSpace = "Rec.709 Gamma 2.4";
        var props = comp("04  OBJECTS - HDRI and motion");
        props.renderer = "ADBE Calder";
        if (props.renderer !== "ADBE Calder") throw Error("Enable Advanced 3D in this version of After Effects.");
        var models = {Flask:imported(flaskFile), Cup:imported(cupFile)};
        var plate = imported(plateFile), hdr = imported(lightFile), water = imported(waterFile);
        requirePlate(plate, "Plate", cam);
        requirePlate(water, "Water pass", cam);
        if (!water.mainSource.hasAlpha) throw Error("Water pass has no alpha channel");
        water.mainSource.alphaMode = AlphaMode.STRAIGHT;
        for (var j = 0; j < layout.tracks.length; j++) {
            var data = layout.tracks[j];
            if (data.kind === "Water") continue;
            var model = layer(props, models[data.kind]);
            model.name = data.name;
            model.motionBlur = false;
            var rect = model.sourceRectAtTime(0, false), size = bounds[data.kind];
            var units = (rect.width/size[0] + rect.height/size[1]) / 2;
            if (!isFinite(units) || Math.abs(units - 512) > 8) throw Error("Unexpected GLB scale on " + model.name);
            var scale = 100000 * data.scale / units;
            model.anchorPoint.setValue([0, 0, 0]);
            model.scale.setValue([scale, scale, scale]);
            model.orientation.setValue([0, 0, 0]);
            var positions = [], rx = [], ry = [], rz = [];
            for (k = 0; k < cam.count; k++) {
                positions.push(posAE(data.pos[k]));
                rx.push(data.r[k][0]); ry.push(-data.r[k][1]); rz.push(-data.r[k][2]);
            }
            model.position.setValuesAtTimes(times, positions);
            model.xRotation.setValuesAtTimes(times, rx);
            model.yRotation.setValuesAtTimes(times, ry);
            model.zRotation.setValuesAtTimes(times, rz);
        }
        var ibl = layer(props, hdr);
        ibl.name = "IBL SOURCE - environment"; ibl.enabled = false;
        var env = props.layers.addLight("Panorama - environment", [960, 540]);
        env.lightType = LightType.ENVIRONMENT;
        env.lightSource = ibl;
        env.lightOption.intensity.setValue(92);
        var camera = props.layers.addCamera("COLMAP - tracked camera", [960, 540]);
        camera.autoOrient = AutoOrientType.CAMERA_OR_POINT_OF_INTEREST;
        camera.position.setValuesAtTimes(times, cam.position);
        camera.pointOfInterest.setValuesAtTimes(times, cam.poi);
        camera.zRotation.setValuesAtTimes(times, cam.roll);
        camera.zoom.setValue(cam.zoom);

        var probe = props.layers.addNull();
        var worst = 0;
        try {
            probe.threeDLayer = true;
            probe.position.setValuesAtTimes(times, cam.probe);
            var result = probe.property("ADBE Effect Parade").addProperty("ADBE Point Control").property(1);
            result.expression = "thisLayer.toComp(thisLayer.anchorPoint)";
            for (k = 0; k < cam.count; k++) {
                var uv = result.valueAtTime(times[k], false);
                var dx = uv[0] - cam.expected[0], dy = uv[1] - cam.expected[1];
                worst = Math.max(worst, Math.sqrt(dx*dx + dy*dy));
            }
            if (result.expressionError || !isFinite(worst) || worst > .2) {
                throw Error("Three.js/AE projection check failed: " + worst + " px");
            }
        } finally {
            var nullSource = probe.source;
            probe.remove();
            if (nullSource && nullSource.usedIn.length === 0) nullSource.remove();
        }
        var alpha = comp("03  ALPHA - aligns with source");
        layer(alpha, props);
        layer(alpha, water).name = "WATER - moving plate refraction";
        var source = comp("02  SOURCE - original camera");
        layer(source, plate);
        layer(source, alpha);
        var master = comp("01  DRIFT - stabilized preview");
        var shared = layer(master, source), xy = [], rotation = [];
        shared.name = "Plate and CG - shared stabilization";
        for (k = 0; k < cam.count; k++) {
            xy.push([960 + stab.rows[k].x, 540 + stab.rows[k].y]);
            rotation.push(stab.rows[k].deg);
        }
        shared.position.setValuesAtTimes(times, xy);
        shared.rotation.setValuesAtTimes(times, rotation);
        shared.scale.setValue([100 * stab.crop, 100 * stab.crop]);
        master.time = 94 / fps;
        var queueStatus = "Choose comp 03 for a source-aligned alpha export.";
        if (!alphaFile.exists) {
            var item = p.renderQueue.items.add(alpha), module = item.outputModule(1), available = module.templates;
            var preset = "High Quality with Alpha", found = false;
            for (j = 0; j < available.length; j++) if (available[j] === preset) found = true;
            if (found) {
                module.applyTemplate(preset);
                module.file = alphaFile;
                queueStatus = "Source-aligned alpha queued.";
            } else {
                item.remove();
                queueStatus = "Select an RGB+Alpha output template for comp 03 in your AE language.";
            }
        }
        if (projectFile.exists) throw Error("Output project already exists.");
        p.save(projectFile);
        if (!projectFile.exists) throw Error("Project was not saved.");
        if (!batch) master.openInViewer();
        return "Saved " + projectFile.name + ". Camera projection max " + worst.toFixed(4) + " px. " + queueStatus;
    }
    try {
        var receipt = build();
        if (!batch) alert(receipt);
        return receipt;
    } catch (error) {
        if (batch) throw error;
        alert("Build Drift: " + error.toString());
    } finally {
        if (grouped) app.endUndoGroup();
    }
}());
