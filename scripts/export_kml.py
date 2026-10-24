"""Export evidence-backed pixel polygons to WGS84 KML. Never repairs geometry silently."""
import argparse
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import CRS, Geod, Transformer
from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.validation import explain_validity

GEOD = Geod(ellps="WGS84")
NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", NS)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def points(value, minimum=3):
    a = np.asarray(value, dtype=float)
    if a.ndim != 2 or a.shape[1] != 2 or len(a) < minimum or not np.isfinite(a).all():
        raise ValueError(f"expected at least {minimum} finite coordinate pairs")
    return a


def validate_geo(a):
    if np.any(np.abs(a[:, 0]) > 180) or np.any(np.abs(a[:, 1]) > 90):
        raise ValueError("coordinates are not WGS84 longitude/latitude degrees")
    if np.ptp(a[:, 0]) > 180:
        raise ValueError("antimeridian crossings require explicit GIS handling")


def affine_fit(pixel, world):
    center = pixel.mean(axis=0)
    scale = np.ptp(pixel, axis=0)
    if np.any(scale == 0):
        raise ValueError("GCPs are collinear")
    a = np.c_[(pixel-center)/scale, np.ones(len(pixel))]
    coef, _, rank, _ = np.linalg.lstsq(a, world, rcond=None)
    if rank < 3 or np.linalg.cond(a) > 1e4:
        raise ValueError("GCPs are collinear or poorly conditioned")
    return lambda x: np.c_[(np.asarray(x)-center)/scale, np.ones(len(x))] @ coef


def registration(config, rings):
    r = config["registration"]
    method = r["method"]
    info = {"method": method}
    warnings = []
    if method in ("axis_ticks", "projected_ticks"):
        if r.get("north_up_confirmed") is not True:
            raise ValueError("axis_ticks requires north_up_confirmed=true after visual inspection")
        fits = []
        for key in ("x_ticks", "y_ticks"):
            t = points(r[key], 2)
            if np.ptp(t[:, 0]) == 0 or np.ptp(t[:, 1]) == 0:
                raise ValueError("ticks need distinct pixel and geographic values")
            coef = np.polyfit(t[:, 0], t[:, 1], 1)
            fits.append(coef)
            info[key+"_fit_rmse"] = float(np.sqrt(np.mean((np.polyval(coef, t[:, 0])-t[:, 1])**2)))
        if fits[0][0] <= 0 or fits[1][0] >= 0:
            raise ValueError("north-up ticks must increase eastward and decrease downward")
        transform = lambda p: np.c_[np.polyval(fits[0], np.asarray(p)[:, 0]), np.polyval(fits[1], np.asarray(p)[:, 1])]
        if method == "projected_ticks":
            crs = CRS.from_user_input(r["map_crs"])
            if not crs.is_projected:
                raise ValueError("projected_ticks requires a projected map_crs")
            reverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            tick_transform = transform
            transform = lambda p: np.column_stack(reverse.transform(*tick_transform(p).T))
            info["map_crs"] = crs.to_string()
            info["tick_residual_units"] = crs.axis_info[0].unit_name
        else:
            info["tick_residual_units"] = "degrees"
        warnings.append("Axis tick fit residuals measure internal consistency, not independent positional accuracy.")
    elif method == "affine_gcps":
        gcps = r["gcps"]
        pixel = points([x["pixel"] for x in gcps])
        geo = points([x["lonlat"] for x in gcps])
        validate_geo(geo)
        target_crs = r.get("fit_crs", "EPSG:4326")
        forward = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
        reverse = Transformer.from_crs(target_crs, "EPSG:4326", always_xy=True)
        world = np.column_stack(forward.transform(geo[:, 0], geo[:, 1]))
        fit = affine_fit(pixel, world)
        transform = lambda p: np.column_stack(reverse.transform(*fit(p).T))
        pred = transform(pixel)
        distances = GEOD.inv(geo[:, 0], geo[:, 1], pred[:, 0], pred[:, 1])[2]
        info.update(fit_crs=target_crs, gcp_count=len(gcps), fit_rmse_m=float(np.sqrt(np.mean(distances**2))), fit_max_m=float(max(distances)))
        if len(gcps) > 3:
            loo = []
            for i in range(len(gcps)):
                keep = np.arange(len(gcps)) != i
                try:
                    estimate = affine_fit(pixel[keep], world[keep])(pixel[i:i+1])[0]
                    lon, lat = reverse.transform(*estimate)
                    loo.append(abs(GEOD.inv(*geo[i], lon, lat)[2]))
                except ValueError:
                    pass
            info["leave_one_out_count"] = len(loo)
            if loo:
                info["leave_one_out_rmse_m"] = float(np.sqrt(np.mean(np.array(loo)**2)))
        hull = MultiPoint(pixel).convex_hull
        vertices = np.vstack(rings)
        outside = sum(not hull.covers(Point(p)) for p in vertices)
        info["vertices_outside_gcp_hull"] = outside
        info["vertex_count_for_extrapolation_check"] = len(vertices)
        if outside:
            warnings.append(f"{outside}/{len(vertices)} boundary vertices lie outside the GCP convex hull; fit residuals do not validate this extrapolation.")
        warnings.append("GCP fit and leave-one-out residuals do not include original map, datum or digitization error.")
    elif method == "outline_bbox_fit":
        if not r.get("extrema_evidence"):
            raise ValueError("outline_bbox_fit requires evidence that text bounds describe outline extrema")
        if config.get("confidence") != "low":
            raise ValueError("outline_bbox_fit must use confidence=low")
        all_points = np.vstack(rings)
        lo, hi = all_points.min(axis=0), all_points.max(axis=0)
        bbox = np.asarray(r["bounds_lonlat"], dtype=float)
        if bbox.shape != (4,) or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]) or np.any(hi == lo):
            raise ValueError("invalid outline or geographic bounds")
        validate_geo(bbox.reshape(2, 2))
        transform = lambda p: np.c_[bbox[0]+(np.asarray(p)[:, 0]-lo[0])/(hi[0]-lo[0])*(bbox[2]-bbox[0]), bbox[3]-(np.asarray(p)[:, 1]-lo[1])/(hi[1]-lo[1])*(bbox[3]-bbox[1])]
        info["independent_accuracy"] = "unavailable"
        warnings.append("LOW CONFIDENCE: text extrema forced to outline extrema; projection, rounding and correspondence unverified.")
    else:
        raise ValueError(f"unsupported registration method: {method}")
    if r.get("checkpoints"):
        cps = r["checkpoints"]
        actual = points([x["lonlat"] for x in cps], 1)
        validate_geo(actual)
        pred = transform(points([x["pixel"] for x in cps], 1))
        errors = GEOD.inv(*actual.T, *pred.T)[2]
        info["checkpoint_errors_m"] = np.asarray(errors).tolist()
    return transform, info, warnings


def export(config, image_path, outdir, allow_bbox_proxy=False):
    if not config.get("source", {}).get("pdf") or not config["source"].get("figure") or not config["source"].get("pdf_page"):
        raise ValueError("source requires pdf, figure and one-based pdf_page")
    if not isinstance(config['source']['pdf_page'], int) or config['source']['pdf_page'] < 1:
        raise ValueError("pdf_page must be a positive one-based integer")
    if config.get("confidence") not in ("low", "medium", "high"):
        raise ValueError("confidence is required")
    if not config.get("datum_note"):
        raise ValueError("datum_note must state confirmed datum or the assumption")
    if not config.get("boundary_evidence") or not config.get("boundary_role"):
        raise ValueError("explicit boundary evidence and role are required")
    image = Image.open(image_path).convert("RGB") if image_path else None
    if image and list(image.size) != config.get("image_size"):
        raise ValueError("image dimensions differ from config; pixel coordinates cannot be reused")
    if image and config.get("image_sha256") and sha256(image_path) != config["image_sha256"]:
        raise ValueError("image SHA256 differs from config")
    method = config["registration"]["method"]
    if method == "text_bbox_proxy":
        if not allow_bbox_proxy or "BBOX_PROXY_NOT_BOUNDARY" not in config["name"]:
            raise ValueError("text proxy requires --allow-bbox-proxy and BBOX_PROXY_NOT_BOUNDARY in name")
        if config["boundary_role"] != "bbox_proxy" or config["confidence"] != "low":
            raise ValueError("text proxy requires boundary_role=bbox_proxy and confidence=low")
        w, s, e, n = config["registration"]["bounds_lonlat"]
        if not (w < e and s < n):
            raise ValueError("invalid bounding box")
        raw = [{"name": config["name"], "outer_lonlat": [[w,s],[e,s],[e,n],[w,n]], "holes_lonlat": []}]
        info, warnings = {"method": method}, ["BBOX_PROXY_NOT_BOUNDARY: location only; no actual research boundary recovered."]
        pixels = []
    else:
        if config["boundary_role"] == "map_frame_extent":
            if config["confidence"] != "low" or "MAP_FRAME_EXTENT" not in config["name"]:
                raise ValueError("map_frame_extent requires confidence=low and MAP_FRAME_EXTENT in name")
            if method not in ("axis_ticks", "projected_ticks", "affine_gcps"):
                raise ValueError("map_frame_extent requires map-based registration, not text bounds")
            if not image:
                raise ValueError("map_frame_extent requires the source map image")
            frame = np.asarray(config.get("map_frame_pixels"), dtype=float)
            if frame.shape != (4,) or not np.isfinite(frame).all() or not (frame[0] < frame[2] and frame[1] < frame[3]):
                raise ValueError("map_frame_pixels must be finite [left,top,right,bottom]")
            if config.get("polygons") or config.get("boundary_pixels"):
                raise ValueError("map_frame_extent uses map_frame_pixels, not a traced boundary")
            x0,y0,x1,y1 = frame.tolist()
            pixels = [{"name":config["name"], "boundary_pixels":[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]}]
        else:
            pixels = config.get("polygons", [{"name": config["name"], "boundary_pixels": config.get("boundary_pixels", [])}])
        rings = [points(p["boundary_pixels"]) for p in pixels]
        for p in pixels:
            rings.extend(points(h) for h in p.get("holes_pixels", []))
        if image:
            for ring in rings:
                if (ring < 0).any() or (ring[:, 0] >= image.width).any() or (ring[:, 1] >= image.height).any():
                    raise ValueError("pixel coordinates fall outside image")
        if config.get("boundary_complete") is not True and config["boundary_role"] not in ("coverage_footprint", "visible_partial_boundary"):
            raise ValueError("incomplete boundary may not be exported as a complete study area")
        transform, info, warnings = registration(config, rings)
        if config["boundary_role"] == "map_frame_extent":
            info["extent_basis"] = "georeferenced_map_frame"
            warnings.append("MAP_FRAME_EXTENT: the map panel's whole rectangle is adopted as the study area under the fallback policy; it is not an author-delineated boundary.")
        raw = [{"name": p.get("name", config["name"]), "outer_lonlat": transform(points(p["boundary_pixels"])).tolist(), "holes_lonlat": [transform(points(h)).tolist() for h in p.get("holes_pixels", [])]} for p in pixels]
    shapes = []
    for p in raw:
        validate_geo(points(p["outer_lonlat"]))
        for h in p["holes_lonlat"]:
            validate_geo(points(h))
        poly = Polygon(p["outer_lonlat"], p["holes_lonlat"])
        if not poly.is_valid or poly.area == 0:
            raise ValueError("invalid polygon: "+explain_validity(poly))
        shapes.append(orient(poly, sign=1.0))
    multi = MultiPolygon(shapes)
    if not multi.is_valid:
        raise ValueError("invalid multipart geometry: "+explain_validity(multi))
    areas = [abs(GEOD.geometry_area_perimeter(p)[0])/1e6 for p in shapes]
    area = sum(areas)
    warnings += config.get("limitations", [])
    reference = config.get("reference_area_km2")
    difference = 100*(area/reference-1) if reference else None
    if difference is not None and abs(difference) > 10:
        warnings.append(f"Area differs by {difference:+.1f}% from cited {reference:g} km2; do not rescale geometry to force a match.")
    warnings.append("Geometric validation is not independent validation against author GIS ground truth.")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    root = ET.Element(f"{{{NS}}}kml")
    def sub(parent, tag, text=None):
        node = ET.SubElement(parent, f"{{{NS}}}{tag}")
        if text is not None:
            node.text = str(text)
        return node
    document = sub(root, "Document")
    sub(document, "name", config["name"])
    style = sub(document, "Style"); style.set("id", "study")
    line = sub(style, "LineStyle"); sub(line, "color", "ff00a5ff"); sub(line, "width", 2)
    fill = sub(style, "PolyStyle"); sub(fill, "color", "3300a5ff")
    for i, (p, shape) in enumerate(zip(raw, shapes)):
        pm = sub(document, "Placemark")
        sub(pm, "name", p["name"])
        sub(pm, "styleUrl", "#study")
        sub(pm, "description", f"{config['boundary_role']}; confidence={config['confidence']}; figure approximation. "+" | ".join(warnings))
        data = sub(pm, "ExtendedData")
        for key, value in {"crs":"EPSG:4326", "boundary_role":config["boundary_role"], "extent_basis":info.get("extent_basis",config["boundary_role"]), "confidence":config["confidence"], "method":method, "source_pdf":config["source"]["pdf"], "source_figure":config["source"]["figure"], "source_pdf_page":config["source"]["pdf_page"], "paper_title":config["source"].get("paper_title", ""), "doi":config["source"].get("doi", ""), "area_km2":areas[i]}.items():
            node = sub(data, "Data"); node.set("name", key); sub(node, "value", value)
        polygon = sub(pm, "Polygon"); sub(polygon, "tessellate", 1); sub(polygon, "altitudeMode", "clampToGround")
        for j, ring in enumerate([shape.exterior, *shape.interiors]):
            bound = sub(polygon, "outerBoundaryIs" if j == 0 else "innerBoundaryIs")
            lr = sub(bound, "LinearRing")
            sub(lr, "coordinates", " ".join(f"{x:.8f},{y:.8f},0" for x,y in ring.coords))
    ET.indent(root)
    ET.ElementTree(root).write(outdir/"study_area_WGS84_EPSG4326.kml", encoding="utf-8", xml_declaration=True)
    with (outdir/"study_area_coordinates.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f); writer.writerow(["polygon", "ring", "vertex", "longitude", "latitude"])
        for i, shape in enumerate(shapes):
            for j, ring in enumerate([shape.exterior, *shape.interiors]):
                for k, (x,y) in enumerate(ring.coords):writer.writerow([i,j,k,x,y])
    if image:
        layer = Image.new("RGBA", image.size)
        draw = ImageDraw.Draw(layer)
        for p in pixels:
            ring = [tuple(x) for x in p["boundary_pixels"]]
            draw.polygon(ring, fill=(255,90,0,40))
            for h in p.get("holes_pixels", []):draw.polygon([tuple(x) for x in h], fill=(0,0,0,0))
        image = Image.alpha_composite(image.convert("RGBA"), layer)
        draw = ImageDraw.Draw(image)
        for p in pixels:
            for ring in [p["boundary_pixels"], *p.get("holes_pixels", [])]:
                ring = [tuple(x) for x in ring]; draw.line(ring+[ring[0]], fill="#ff6600", width=3)
        controls = config["registration"].get("gcps", [])
        for g in controls:
            x,y=g["pixel"];draw.ellipse((x-5,y-5,x+5,y+5), fill="#00ffff");draw.text((x+6,y),g.get("id", "GCP"),fill="black",stroke_width=1,stroke_fill="white")
        image.convert("RGB").save(outdir/"study_area_overlay.png")
    report = {"config": config, "image_sha256": sha256(image_path) if image_path else None, "registration": info, "geometry": {"valid": True, "polygon_count": len(shapes), "hole_count":sum(len(s.interiors) for s in shapes), "vertex_count":sum(len(s.exterior.coords)-1 for s in shapes), "bounds_lonlat":list(multi.bounds), "geodesic_area_km2":area, "part_areas_km2":areas, "reference_area_km2": reference, "area_difference_percent":difference}, "warnings":warnings, "qa_status":"geometry_valid_requires_source_accuracy_review"}
    (outdir/"study_area_provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    qa = [f"# {config['name']}", "", f"- Source: {config['source']['pdf']}; PDF page {config['source']['pdf_page']}; {config['source']['figure']}", f"- Role: {config['boundary_role']}; confidence: {config['confidence']}", f"- Method: {method}; CRS: WGS84 / EPSG:4326; KML order: longitude,latitude,0", f"- Valid polygons: {len(shapes)}; geodesic area: {area:.4f} km²", f"- Bounds [W,S,E,N]: {list(multi.bounds)}", f"- Datum: {config['datum_note']}", "", "## Evidence", "", config["boundary_evidence"], "", "## Registration diagnostics", "", "```json", json.dumps(info,ensure_ascii=False,indent=2), "```", "", "## Limitations", "", *["- "+w for w in warnings]]
    (outdir/"study_area_QA.md").write_text("\n".join(qa)+"\n", encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--image", type=Path)
    p.add_argument("--outdir", type=Path, required=True)
    p.add_argument("--allow-bbox-proxy", action="store_true")
    a = p.parse_args()
    try:
        result = export(json.loads(a.config.read_text(encoding="utf-8-sig")), a.image, a.outdir, a.allow_bbox_proxy)
    except (ValueError, KeyError) as e:
        p.exit(2, f"ERROR: {e}\n")
    print(json.dumps(result["geometry"], ensure_ascii=False))


if __name__ == "__main__":
    main()
