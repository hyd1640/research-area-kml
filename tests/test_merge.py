import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import shapefile
from pyproj import CRS
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from export_kml import export
from merge_kml_to_shp import merge
from test_export import sample


class MergeTests(unittest.TestCase):
    def prepare(self, folder, multipart=False):
        config = sample()
        config['source'].update(pdf='unrelated_filename.pdf', paper_title='文献正式题名：地形与滑坡')
        if multipart:
            config['polygons'] = [
                {'name':'region with hole', 'boundary_pixels':config['boundary_pixels'],
                 'holes_pixels':[[[2,2],[8,2],[8,8],[2,8]]]},
                {'name':'separate region', 'boundary_pixels':[[12,0],[14,0],[14,2],[12,2]]}]
        export(config, None, folder / 'first')
        entries = [{'paper_id':'01', 'paper_title':config['source']['paper_title'],
                    'title_source':{'type':'pdf_title','page':1},
                    'kml':'first/study_area_WGS84_EPSG4326.kml'}]
        manifest = folder / 'merge_manifest.json'
        manifest.write_text(json.dumps({'sources':entries},ensure_ascii=False),encoding='utf-8')
        return manifest, entries

    def test_actual_title_encoding_geometry_and_projection_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);manifest,entries=self.prepare(folder,multipart=True)
            report=merge(manifest,folder/'merged.shp')
            self.assertEqual((report['input_kml_count'],report['feature_count']),(1,2))
            with shapefile.Reader(str(folder/'merged.shp'),encoding='utf-8') as reader:
                self.assertEqual([r['paper_name'] for r in reader.records()],[entries[0]['paper_title']]*2)
                first=shape(reader.shape(0).__geo_interface__)
                self.assertEqual(len(first.interiors),1)
                self.assertFalse(first.exterior.is_ccw)
                self.assertTrue(first.interiors[0].is_ccw)
            self.assertEqual(CRS.from_wkt((folder/'merged.prj').read_text()).to_epsg(),4326)
            self.assertEqual((folder/'merged.cpg').read_text(),'UTF-8')
            self.assertTrue((folder/'merged.zip').exists())

    def test_multiple_kmls_append_without_dissolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);manifest,entries=self.prepare(folder)
            config=sample();config['source']['paper_title']='A different published article'
            export(config,None,folder/'second')
            entries.append({'paper_id':'02','paper_title':config['source']['paper_title'],
                'title_source':{'type':'pdf_title','page':1},'kml':'second/study_area_WGS84_EPSG4326.kml'})
            manifest.write_text(json.dumps({'sources':entries}),encoding='utf-8')
            report=merge(manifest,folder/'merged.shp')
            self.assertEqual((report['paper_count'],report['feature_count']),(2,2))

    def test_missing_or_filename_based_titles_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);manifest,entries=self.prepare(folder)
            for changes in ({'paper_title':''},{'title_source':{'type':'pdf_filename'}}):
                invalid=copy.deepcopy(entries);invalid[0].update(changes)
                manifest.write_text(json.dumps({'sources':invalid}),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'verified paper_title'):merge(manifest,folder/'merged.shp')
                self.assertFalse((folder/'merged.shp').exists())

    def test_title_mismatch_and_duplicate_sources_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);manifest,entries=self.prepare(folder)
            for invalid in ([{**entries[0],'paper_title':'Incorrect title'}],entries+entries):
                manifest.write_text(json.dumps({'sources':invalid}),encoding='utf-8')
                with self.assertRaises(ValueError):merge(manifest,folder/'merged.shp')
                self.assertFalse((folder/'merged.shp').exists())

    def test_dbf_overflow_cannot_silently_truncate_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);manifest,entries=self.prepare(folder)
            config=sample();config['source']['paper_title']='长标题'*100
            export(config,None,folder/'first')
            entries[0]['paper_title']=config['source']['paper_title']
            manifest.write_text(json.dumps({'sources':entries}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'no text has been truncated'):merge(manifest,folder/'merged.shp')
            self.assertFalse((folder/'merged.shp').exists())


if __name__=='__main__':unittest.main()
