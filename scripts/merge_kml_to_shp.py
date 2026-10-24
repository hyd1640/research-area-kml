"""Append reviewed polygon KMLs to one WGS84 Shapefile with verified paper titles."""
import argparse
import csv
import json
import math
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

import shapefile
from pyproj import CRS, Geod
from shapely.geometry import Polygon, shape
from shapely.geometry.polygon import orient

NS = '{http://www.opengis.net/kml/2.2}'
GEOD = Geod(ellps='WGS84')
FIELDS = [('paper_id', 'C', 32, 0), ('paper_name', 'C', 254, 0),
          ('part_name', 'C', 254, 0), ('area_role', 'C', 32, 0),
          ('confidence', 'C', 8, 0), ('qa_status', 'C', 32, 0),
          ('doi', 'C', 128, 0), ('kml_file', 'C', 254, 0),
          ('area_km2', 'F', 20, 6)]


def read_polygons(path):
    root = ET.parse(path)
    if any(root.findall('.//' + NS + kind) for kind in ('Point', 'LineString', 'Model')):
        raise ValueError(f'{path}: only polygon KMLs can be merged')
    found = []
    for pm in root.findall('.//' + NS + 'Placemark'):
        data = {d.get('name'): d.findtext(NS + 'value', '')
                for d in pm.findall('./' + NS + 'ExtendedData/' + NS + 'Data')}
        for poly in pm.findall('.//' + NS + 'Polygon'):
            rings = []
            if len(poly.findall('./' + NS + 'outerBoundaryIs/' + NS + 'LinearRing/' + NS + 'coordinates')) != 1:
                raise ValueError(f'{path}: polygon needs exactly one outer ring')
            for kind in ('outerBoundaryIs', 'innerBoundaryIs'):
                for node in poly.findall('./' + NS + kind + '/' + NS + 'LinearRing/' + NS + 'coordinates'):
                    coords = [tuple(map(float, p.split(','))) for p in (node.text or '').split()]
                    if len(coords) < 4 or coords[0] != coords[-1]:
                        raise ValueError(f'{path}: unclosed or short polygon ring')
                    if any(len(p) not in (2, 3) or not all(math.isfinite(x) for x in p)
                           or abs(p[0]) > 180 or abs(p[1]) > 90 for p in coords):
                        raise ValueError(f'{path}: invalid WGS84 coordinates')
                    if any(len(p) == 3 and p[2] != 0 for p in coords):
                        raise ValueError(f'{path}: nonzero altitude would be lost in a 2D Shapefile')
                    rings.append([(p[0], p[1]) for p in coords])
            if len(poly.findall(NS + 'outerBoundaryIs')) != 1 or not rings:
                raise ValueError(f'{path}: polygon needs exactly one outer ring')
            geometry = Polygon(rings[0], rings[1:])
            if not geometry.is_valid or geometry.is_empty or geometry.area == 0:
                raise ValueError(f'{path}: invalid polygon')
            found.append((orient(geometry, sign=-1), pm.findtext(NS + 'name', ''), data))
    if not found:
        raise ValueError(f'{path}: no polygon found')
    return found


def merge(manifest_path, output_path):
    manifest_path = Path(manifest_path)
    entries = json.loads(manifest_path.read_text(encoding='utf-8-sig'))['sources']
    if not entries:
        raise ValueError('sources must contain at least one individually exported KML')
    rows, seen = [], set()
    for entry in entries:
        title = entry.get('paper_title', '').strip()
        evidence = entry.get('title_source', {})
        if not title or not isinstance(evidence, dict) or evidence.get('type') not in ('pdf_title', 'publisher_title', 'bibliographic_record') or not entry.get('paper_id'):
            raise ValueError('paper_id, verified paper_title and title_source are required; never infer a title from the filename')
        path = (manifest_path.parent / entry['kml']).resolve()
        if path in seen:
            raise ValueError(f'duplicate KML source: {entry["kml"]}')
        seen.add(path)
        for geometry, part, data in read_polygons(path):
            if data.get('paper_title') and data['paper_title'] != title:
                raise ValueError(f'{path}: KML paper_title differs from verified title')
            if data.get('crs') not in (None, '', 'EPSG:4326'):
                raise ValueError(f'{path}: source CRS is not EPSG:4326')
            attrs = {'paper_id': str(entry['paper_id']), 'paper_name': title, 'part_name': part,
                     'area_role': data.get('boundary_role', entry.get('area_role', 'unspecified')),
                     'confidence': data.get('confidence', entry.get('confidence', 'unknown')),
                     'qa_status': entry.get('qa_status', 'approximate'),
                     'doi': entry.get('doi', data.get('doi', '')), 'kml_file': entry['kml'],
                     'area_km2': abs(GEOD.geometry_area_perimeter(geometry)[0]) / 1e6}
            for name, kind, width, _ in FIELDS:
                if kind == 'C' and len(attrs[name].encode('utf-8')) > width:
                    raise ValueError(f'{name} exceeds the chosen {width}-byte DBF width; no text has been truncated')
            rows.append((geometry, attrs))

    output = Path(output_path).with_suffix('.shp')
    output.parent.mkdir(parents=True, exist_ok=True)
    with shapefile.Writer(str(output), shapeType=shapefile.POLYGON, encoding='utf-8') as writer:
        for field in FIELDS:
            writer.field(*field)
        for geometry, attrs in rows:
            writer.poly([list(geometry.exterior.coords), *[list(r.coords) for r in geometry.interiors]])
            writer.record(**attrs)
    output.with_suffix('.prj').write_text(CRS.from_epsg(4326).to_wkt(version='WKT1_ESRI'), encoding='utf-8')
    output.with_suffix('.cpg').write_text('UTF-8', encoding='ascii')

    # Read the actual SHP/DBF files back; detect geometry, title and encoding loss.
    with shapefile.Reader(str(output), encoding='utf-8') as reader:
        if len(reader) != len(rows) or reader.shapeType != shapefile.POLYGON:
            raise ValueError('Shapefile round-trip feature count/type mismatch')
        for record, (expected_geometry, expected) in zip(reader.iterShapeRecords(), rows):
            actual = record.record.as_dict()
            if any(actual[k] != v for k, v in expected.items() if k != 'area_km2'):
                raise ValueError('Shapefile attribute round-trip mismatch')
            geometry = shape(record.shape.__geo_interface__)
            if not geometry.is_valid or not geometry.equals(expected_geometry):
                raise ValueError('Shapefile geometry round-trip mismatch')
            if abs(actual['area_km2'] - expected['area_km2']) > 1e-6:
                raise ValueError('Shapefile area round-trip mismatch')
    if CRS.from_wkt(output.with_suffix('.prj').read_text(encoding='utf-8')).to_epsg() != 4326:
        raise ValueError('Shapefile CRS round-trip mismatch')
    with output.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=[f[0] for f in FIELDS])
        writer.writeheader(); writer.writerows(attrs for _, attrs in rows)
    report = {'crs': 'EPSG:4326', 'encoding': 'UTF-8', 'merge_mode': 'append_one_record_per_polygon',
              'input_kml_count': len(entries), 'paper_count': len({r[1]['paper_id'] for r in rows}),
              'feature_count': len(rows), 'roles': dict(Counter(r[1]['area_role'] for r in rows)),
              'title_field': 'paper_name', 'title_field_meaning': '论文正式标题；从文献标题核对，不从 PDF 文件名生成',
              'fields': [f[0] for f in FIELDS], 'sources': entries, 'round_trip_valid': True}
    output.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(output.with_suffix('.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
        for suffix in ('.shp', '.shx', '.dbf', '.prj', '.cpg', '.csv', '.json'):
            file = output.with_suffix(suffix)
            archive.write(file, file.name)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = merge(args.manifest, args.out)
    except (ValueError, KeyError, OSError, ET.ParseError) as error:
        parser.exit(2, f'ERROR: {error}\n')
    print(json.dumps({k: report[k] for k in ('input_kml_count', 'paper_count', 'feature_count', 'round_trip_valid')}, ensure_ascii=False))
